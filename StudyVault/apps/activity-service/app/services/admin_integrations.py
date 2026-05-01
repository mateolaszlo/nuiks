from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterable
from collections.abc import Callable
from dataclasses import dataclass
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
from studyvault_backend_common.logging import get_logger


logger = get_logger(__name__)
KEYCLOAK_AUTH_EVENT_TYPE_MAP = {
    "LOGIN": "auth_login",
    "LOGIN_ERROR": "auth_login_failed",
    "REGISTER": "auth_register",
    "REGISTER_ERROR": "auth_register_failed",
}
KEYCLOAK_AUTH_SUCCESS_EVENT_NAMES = {"auth_login", "auth_register"}


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


class AuthEventSyncCheckpointStore(Protocol):
    def get_auth_event_sync_checkpoint(self) -> tuple[datetime, str] | None: ...

    def save_auth_event_sync_checkpoint(self, created_at: datetime, event_id: str) -> None: ...


@dataclass(frozen=True)
class AuthEventSyncCheckpoint:
    created_at: datetime
    event_id: str


def _normalize_keycloak_auth_event(item: dict[str, Any]) -> AdminAuditEvent | None:
    raw_event_type = str(item.get("type") or "").upper()
    normalized_event_type = KEYCLOAK_AUTH_EVENT_TYPE_MAP.get(raw_event_type)
    if normalized_event_type is None:
        return None

    details = dict(item.get("details") or {})
    username = details.get("username")
    email = details.get("email")
    client_ip = item.get("ipAddress")
    if client_ip:
        details["client_ip"] = client_ip
    error = details.get("error")
    if error:
        details["error"] = error
    action = "login" if raw_event_type.startswith("LOGIN") else "register"
    status = "succeeded" if normalized_event_type in KEYCLOAK_AUTH_SUCCESS_EVENT_NAMES else "failed"
    return AdminAuditEvent(
        event_id=item.get("id") or f"kc-{item.get('time')}",
        event_type=normalized_event_type,
        category="auth",
        actor_user_id=item.get("userId"),
        actor_username=username,
        actor_email=email,
        target_user_id=item.get("userId"),
        target_username=username,
        target_email=email,
        status=status,
        service="keycloak",
        message=f"Keycloak {action} {'succeeded' if status == 'succeeded' else 'failed'}",
        metadata=details,
        created_at=_parse_datetime(item.get("time")) or datetime.now(UTC),
    )


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
            (
                f"/admin/realms/{self.realm}/events?max={limit}"
                "&type=LOGIN&type=LOGIN_ERROR&type=REGISTER&type=REGISTER_ERROR"
            ),
        )
        events: list[AdminAuditEvent] = []
        for item in payload:
            event = _normalize_keycloak_auth_event(item)
            if event is not None:
                events.append(event)
        return events


class KeycloakAuthEventSync:
    def __init__(
        self,
        *,
        keycloak: KeycloakAdminGateway,
        checkpoint_store: AuthEventSyncCheckpointStore,
        batch_size: int,
        interval_seconds: float,
        emit_event: Callable[[AdminAuditEvent], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.keycloak = keycloak
        self.checkpoint_store = checkpoint_store
        self.batch_size = batch_size
        self.interval_seconds = interval_seconds
        self.emit_event = emit_event or self._emit_event
        self.now = now or (lambda: datetime.now(UTC))

    def initialize_checkpoint(self) -> AuthEventSyncCheckpoint:
        existing = self._checkpoint()
        if existing is not None:
            return existing
        checkpoint = AuthEventSyncCheckpoint(created_at=self.now(), event_id="")
        self._save_checkpoint(checkpoint)
        return checkpoint

    async def sync_once(self) -> int:
        checkpoint = self.initialize_checkpoint()
        events = await self.keycloak.list_auth_events(self.batch_size)
        new_events = [
            event
            for event in sorted(events, key=lambda item: (item.created_at, item.event_id))
            if self._is_after_checkpoint(event, checkpoint)
        ]
        for event in new_events:
            self.emit_event(event)
            checkpoint = AuthEventSyncCheckpoint(created_at=event.created_at, event_id=event.event_id)
            self._save_checkpoint(checkpoint)
        return len(new_events)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        self.initialize_checkpoint()
        while not stop_event.is_set():
            try:
                await self.sync_once()
            except Exception as exc:
                logger.exception(
                    "keycloak auth sync failed",
                    event_name="keycloak_auth_sync_failed",
                    event_category="auth",
                    service="activity-service",
                    status="failed",
                    error=str(exc),
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _checkpoint(self) -> AuthEventSyncCheckpoint | None:
        stored = self.checkpoint_store.get_auth_event_sync_checkpoint()
        if stored is None:
            return None
        created_at, event_id = stored
        return AuthEventSyncCheckpoint(created_at=created_at, event_id=event_id)

    def _save_checkpoint(self, checkpoint: AuthEventSyncCheckpoint) -> None:
        self.checkpoint_store.save_auth_event_sync_checkpoint(checkpoint.created_at, checkpoint.event_id)

    @staticmethod
    def _is_after_checkpoint(event: AdminAuditEvent, checkpoint: AuthEventSyncCheckpoint) -> bool:
        return (event.created_at, event.event_id) > (checkpoint.created_at, checkpoint.event_id)

    @staticmethod
    def _emit_event(event: AdminAuditEvent) -> None:
        metadata = event.metadata or {}
        logger.info(
            event.message,
            timestamp=event.created_at.isoformat(),
            event_name=event.event_type,
            event_category=event.category,
            service=event.service,
            status=event.status,
            actor_user_id=event.actor_user_id,
            actor_username=event.actor_username,
            actor_email=event.actor_email,
            target_user_id=event.target_user_id,
            target_username=event.target_username,
            target_email=event.target_email,
            username=event.actor_username or event.target_username,
            email=event.actor_email or event.target_email,
            client_ip=metadata.get("client_ip"),
            error=metadata.get("error"),
        )


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
