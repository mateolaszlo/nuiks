from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from studyvault_backend_common.models import (
    AdminAuditEvent,
    AdminErrorRecord,
    AdminPasswordResetResult,
    AdminServiceHealth,
    AdminUserSummary,
    STUDYVAULT_ADMIN_ROLE,
)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


class KeycloakAdminGateway(Protocol):
    async def list_users(self) -> list[AdminUserSummary]: ...

    async def set_enabled(self, user_id: str, enabled: bool) -> AdminUserSummary: ...

    async def set_admin_role(self, user_id: str, make_admin: bool) -> AdminUserSummary: ...

    async def reset_password(self, user_id: str) -> AdminPasswordResetResult: ...

    async def list_auth_events(self, limit: int) -> list[AdminAuditEvent]: ...


class AuditLogGateway(Protocol):
    async def list_app_audit_events(self, limit: int) -> list[AdminAuditEvent]: ...

    async def list_recent_errors(self, limit: int) -> list[AdminErrorRecord]: ...

    async def summarize_counts(self) -> dict[str, int]: ...


class ServiceHealthGateway(Protocol):
    async def check_services(self) -> list[AdminServiceHealth]: ...


class KeycloakAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        username: str,
        password: str,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.username = username
        self.password = password
        self.timeout = timeout

    async def _get_admin_token(self) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/realms/master/protocol/openid-connect/token",
                data={
                    "client_id": "admin-cli",
                    "grant_type": "password",
                    "username": self.username,
                    "password": self.password,
                },
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()["access_token"]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await self._get_admin_token()
        headers = kwargs.pop("headers", {})
        headers["authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None

    async def _get_realm_roles(self, user_id: str) -> list[str]:
        payload = await self._request(
            "GET",
            f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm",
        )
        return [role["name"] for role in payload]

    async def _build_user_summary(self, payload: dict[str, Any]) -> AdminUserSummary:
        roles = await self._get_realm_roles(payload["id"])
        return AdminUserSummary(
            user_id=payload["id"],
            username=payload.get("username") or "unknown",
            email=payload.get("email"),
            enabled=payload.get("enabled", True),
            email_verified=payload.get("emailVerified", False),
            roles=sorted(roles),
            created_at=_parse_datetime(payload.get("createdTimestamp")),
        )

    async def list_users(self) -> list[AdminUserSummary]:
        payload = await self._request("GET", f"/admin/realms/{self.realm}/users?max=200")
        users = [await self._build_user_summary(user) for user in payload]
        return sorted(users, key=lambda item: item.username.lower())

    async def _get_user(self, user_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/admin/realms/{self.realm}/users/{user_id}")

    async def set_enabled(self, user_id: str, enabled: bool) -> AdminUserSummary:
        payload = await self._get_user(user_id)
        payload["enabled"] = enabled
        await self._request("PUT", f"/admin/realms/{self.realm}/users/{user_id}", json=payload)
        return await self._build_user_summary(await self._get_user(user_id))

    async def _get_admin_role_representation(self) -> dict[str, Any]:
        return await self._request("GET", f"/admin/realms/{self.realm}/roles/{STUDYVAULT_ADMIN_ROLE}")

    async def set_admin_role(self, user_id: str, make_admin: bool) -> AdminUserSummary:
        role = await self._get_admin_role_representation()
        path = f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm"
        if make_admin:
            await self._request("POST", path, json=[role])
        else:
            await self._request("DELETE", path, json=[role])
        return await self._build_user_summary(await self._get_user(user_id))

    async def reset_password(self, user_id: str) -> AdminPasswordResetResult:
        payload = await self._get_user(user_id)
        temporary_password = f"sv-{secrets.token_urlsafe(8)}"
        await self._request(
            "PUT",
            f"/admin/realms/{self.realm}/users/{user_id}/reset-password",
            json={"type": "password", "temporary": True, "value": temporary_password},
        )
        return AdminPasswordResetResult(
            user_id=user_id,
            username=payload.get("username") or "unknown",
            temporary_password=temporary_password,
        )

    async def list_auth_events(self, limit: int) -> list[AdminAuditEvent]:
        payload = await self._request(
            "GET",
            f"/admin/realms/{self.realm}/events?max={limit}&type=LOGIN&type=REGISTER",
        )
        events: list[AdminAuditEvent] = []
        for item in payload:
            details = item.get("details") or {}
            username = details.get("username")
            event_type = (item.get("type") or "").lower()
            events.append(
                AdminAuditEvent(
                    event_id=item.get("id") or f"kc-{item.get('time')}",
                    event_type=f"auth_{event_type}",
                    category="auth",
                    actor_user_id=item.get("userId"),
                    actor_username=username,
                    actor_email=details.get("email"),
                    target_user_id=item.get("userId"),
                    target_username=username,
                    target_email=details.get("email"),
                    status="succeeded" if event_type in {"login", "register"} else "unknown",
                    service="keycloak",
                    message=f"Keycloak {event_type}",
                    metadata=details,
                    created_at=_parse_datetime(item.get("time")) or datetime.now(UTC),
                )
            )
        return events


class ElasticsearchAuditClient:
    def __init__(self, *, elasticsearch_url: str, timeout: float = 10.0) -> None:
        self.elasticsearch_url = elasticsearch_url.rstrip("/")
        self.timeout = timeout

    async def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.elasticsearch_url}/studyvault-logs-*/_search",
                json=payload,
                headers={"content-type": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    async def list_app_audit_events(self, limit: int) -> list[AdminAuditEvent]:
        payload = await self._search(
            {
                "size": limit,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "query": {
                    "terms": {
                        "event_name.keyword": [
                            "file_upload_succeeded",
                            "file_download_succeeded",
                            "search_executed",
                            "admin_user_state_changed",
                            "admin_role_changed",
                            "admin_password_reset",
                        ]
                    }
                },
            }
        )
        events: list[AdminAuditEvent] = []
        for hit in payload.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            username = source.get("owner_id")
            events.append(
                AdminAuditEvent(
                    event_id=hit.get("_id", ""),
                    event_type=source.get("event_name", "unknown_event"),
                    category=source.get("event_category", "application"),
                    actor_user_id=source.get("owner_id"),
                    actor_username=source.get("actor_username", username),
                    actor_email=source.get("actor_email", source.get("owner_email", source.get("email"))),
                    target_user_id=source.get("target_user_id", source.get("owner_id")),
                    target_username=source.get("target_username", username),
                    target_email=source.get("target_email", source.get("owner_email", source.get("email"))),
                    owner_username=source.get("owner_username", source.get("username")),
                    owner_email=source.get("owner_email", source.get("email")),
                    file_id=source.get("file_id"),
                    filename=source.get("filename"),
                    status=source.get("status"),
                    service=source.get("service"),
                    message=source.get("message", "Application event"),
                    metadata={
                        key: source[key]
                        for key in ("query", "result_count", "mime_type", "tags_count", "size")
                        if key in source
                    },
                    created_at=_parse_datetime(source.get("@timestamp")) or datetime.now(UTC),
                )
            )
        return events

    async def list_recent_errors(self, limit: int) -> list[AdminErrorRecord]:
        payload = await self._search(
            {
                "size": limit,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"log_level.keyword": "error"}},
                            {"term": {"status.keyword": "failed"}},
                            {"wildcard": {"event_name.keyword": "*_failed"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            }
        )
        records: list[AdminErrorRecord] = []
        for hit in payload.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            records.append(
                AdminErrorRecord(
                    event_id=hit.get("_id", ""),
                    service=source.get("service", "unknown-service"),
                    message=source.get("message", "Error event"),
                    request_id=source.get("request_id"),
                    event_name=source.get("event_name"),
                    status=source.get("status"),
                    created_at=_parse_datetime(source.get("@timestamp")) or datetime.now(UTC),
                )
            )
        return records

    async def summarize_counts(self) -> dict[str, int]:
        payload = await self._search(
            {
                "size": 0,
                "aggs": {
                    "events": {
                        "filters": {
                            "filters": {
                                "uploads": {"term": {"event_name.keyword": "file_upload_succeeded"}},
                                "downloads": {"term": {"event_name.keyword": "file_download_succeeded"}},
                                "searches": {"term": {"event_name.keyword": "search_executed"}},
                                "errors": {
                                    "bool": {
                                        "should": [
                                            {"term": {"log_level.keyword": "error"}},
                                            {"term": {"status.keyword": "failed"}},
                                            {"wildcard": {"event_name.keyword": "*_failed"}},
                                        ],
                                        "minimum_should_match": 1,
                                    }
                                },
                            }
                        }
                    }
                },
            }
        )
        buckets = payload.get("aggregations", {}).get("events", {}).get("buckets", {})
        return {
            "uploads": buckets.get("uploads", {}).get("doc_count", 0),
            "downloads": buckets.get("downloads", {}).get("doc_count", 0),
            "searches": buckets.get("searches", {}).get("doc_count", 0),
            "errors": buckets.get("errors", {}).get("doc_count", 0),
        }


class HttpServiceHealthClient:
    def __init__(self, service_urls: dict[str, str], timeout: float = 5.0) -> None:
        self.service_urls = service_urls
        self.timeout = timeout

    async def check_services(self) -> list[AdminServiceHealth]:
        results: list[AdminServiceHealth] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for service, url in self.service_urls.items():
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    detail = response.text
                    results.append(AdminServiceHealth(service=service, status="healthy", detail=detail))
                except Exception as exc:
                    results.append(AdminServiceHealth(service=service, status="unhealthy", detail=str(exc)))
        return results


class InMemoryKeycloakAdminGateway:
    def __init__(
        self,
        users: Iterable[AdminUserSummary] | None = None,
        auth_events: Iterable[AdminAuditEvent] | None = None,
    ) -> None:
        self.users = {user.user_id: user for user in users or []}
        self.auth_events = list(auth_events or [])

    async def list_users(self) -> list[AdminUserSummary]:
        return sorted(self.users.values(), key=lambda item: item.username.lower())

    async def set_enabled(self, user_id: str, enabled: bool) -> AdminUserSummary:
        user = self.users[user_id]
        updated = user.model_copy(update={"enabled": enabled})
        self.users[user_id] = updated
        return updated

    async def set_admin_role(self, user_id: str, make_admin: bool) -> AdminUserSummary:
        user = self.users[user_id]
        roles = set(user.roles)
        if make_admin:
            roles.add(STUDYVAULT_ADMIN_ROLE)
        else:
            roles.discard(STUDYVAULT_ADMIN_ROLE)
        updated = user.model_copy(update={"roles": sorted(roles)})
        self.users[user_id] = updated
        return updated

    async def reset_password(self, user_id: str) -> AdminPasswordResetResult:
        user = self.users[user_id]
        return AdminPasswordResetResult(
            user_id=user.user_id,
            username=user.username,
            temporary_password="sv-test-reset",
        )

    async def list_auth_events(self, limit: int) -> list[AdminAuditEvent]:
        return self.auth_events[:limit]


class InMemoryAuditLogGateway:
    def __init__(
        self,
        audit_events: Iterable[AdminAuditEvent] | None = None,
        errors: Iterable[AdminErrorRecord] | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        self.audit_events = list(audit_events or [])
        self.errors = list(errors or [])
        self.counts = counts or {"uploads": 0, "downloads": 0, "searches": 0, "errors": 0}

    async def list_app_audit_events(self, limit: int) -> list[AdminAuditEvent]:
        return self.audit_events[:limit]

    async def list_recent_errors(self, limit: int) -> list[AdminErrorRecord]:
        return self.errors[:limit]

    async def summarize_counts(self) -> dict[str, int]:
        return self.counts


class InMemoryServiceHealthGateway:
    def __init__(self, services: Iterable[AdminServiceHealth] | None = None) -> None:
        self.services = list(services or [])

    async def check_services(self) -> list[AdminServiceHealth]:
        return self.services
