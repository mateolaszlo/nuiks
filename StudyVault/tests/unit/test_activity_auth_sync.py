from __future__ import annotations

import asyncio
from datetime import timezone, datetime

import pytest

from studyvault_backend_common.models import AdminAuditEvent, AuthenticatedUser, STUDYVAULT_ADMIN_ROLE
from tests.conftest import load_service_module


def test_keycloak_admin_client_normalizes_success_and_failure_auth_events(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_service_module("activity", "app.services.admin_integrations")
    client = module.KeycloakAdminClient(
        base_url="http://keycloak:8080",
        realm="studyvault",
        username="admin",
        password="admin",
    )

    async def fake_request(method: str, path: str, **kwargs):
        assert method == "GET"
        assert "type=LOGIN_ERROR" in path
        return [
            {
                "id": "event-login-ok",
                "type": "LOGIN",
                "time": 1_717_100_000_000,
                "userId": "user-1",
                "ipAddress": "203.0.113.10",
                "details": {"username": "demo", "email": "demo@example.com"},
            },
            {
                "id": "event-login-failed",
                "type": "LOGIN_ERROR",
                "time": 1_717_100_001_000,
                "userId": "user-1",
                "clientId": "studyvault-frontend",
                "ipAddress": "203.0.113.11",
                "error": "invalid_user_credentials",
                "details": {"username": "demo", "email": "demo@example.com"},
            },
        ]

    monkeypatch.setattr(client, "_request", fake_request)

    events = asyncio.run(client.list_auth_events(10))

    assert [event.event_type for event in events] == ["auth_login", "auth_login_failed"]
    assert [event.status for event in events] == ["succeeded", "failed"]
    assert events[1].metadata["client_id"] == "studyvault-frontend"
    assert events[0].metadata["client_ip"] == "203.0.113.10"
    assert events[1].metadata["error"] == "invalid_user_credentials"


def test_keycloak_admin_client_preserves_sparse_failure_reason_without_username(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_service_module("activity", "app.services.admin_integrations")
    client = module.KeycloakAdminClient(
        base_url="http://keycloak:8080",
        realm="studyvault",
        username="admin",
        password="admin",
    )

    async def fake_request(method: str, path: str, **kwargs):
        assert method == "GET"
        return [
            {
                "id": "event-login-already-logged-in",
                "type": "LOGIN_ERROR",
                "time": 1_717_100_002_000,
                "ipAddress": "203.0.113.12",
                "error": "already_logged_in",
                "details": {
                    "response_type": "code",
                    "redirect_uri": "https://studyvault.dev",
                },
            }
        ]

    monkeypatch.setattr(client, "_request", fake_request)

    events = asyncio.run(client.list_auth_events(10))

    assert len(events) == 1
    assert events[0].event_type == "auth_login_failed"
    assert events[0].metadata["error"] == "already_logged_in"
    assert events[0].metadata["client_ip"] == "203.0.113.12"
    assert events[0].actor_username is None


def test_keycloak_auth_sync_seeds_future_only_checkpoint() -> None:
    main = load_service_module("activity")
    integrations = load_service_module("activity", "app.services.admin_integrations")
    repository = main.InMemoryActivityRepository()
    old_event = AdminAuditEvent(
        event_id="old-login",
        event_type="auth_login",
        category="auth",
        actor_user_id="user-1",
        actor_username="demo",
        target_user_id="user-1",
        target_username="demo",
        status="succeeded",
        service="keycloak",
        message="Keycloak login succeeded",
        created_at=datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
    )
    keycloak = main.InMemoryKeycloakAdminGateway(auth_events=[old_event])
    emitted: list[AdminAuditEvent] = []
    now = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    sync = integrations.KeycloakAuthEventSync(
        keycloak=keycloak,
        checkpoint_store=repository,
        batch_size=50,
        interval_seconds=30,
        emit_event=emitted.append,
        now=lambda: now,
    )

    synced = asyncio.run(sync.sync_once())

    assert synced == 0
    assert emitted == []
    assert repository.get_auth_event_sync_checkpoint() == (now, "")


def test_keycloak_auth_sync_emits_only_new_events_after_checkpoint() -> None:
    main = load_service_module("activity")
    integrations = load_service_module("activity", "app.services.admin_integrations")
    repository = main.InMemoryActivityRepository()
    checkpoint_time = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    repository.save_auth_event_sync_checkpoint(checkpoint_time, "event-a")

    keycloak = main.InMemoryKeycloakAdminGateway(
        auth_events=[
            AdminAuditEvent(
                event_id="event-a",
                event_type="auth_login",
                category="auth",
                actor_user_id="user-1",
                actor_username="demo",
                target_user_id="user-1",
                target_username="demo",
                status="succeeded",
                service="keycloak",
                message="Keycloak login succeeded",
                created_at=checkpoint_time,
            ),
            AdminAuditEvent(
                event_id="event-b",
                event_type="auth_login_failed",
                category="auth",
                actor_user_id="user-1",
                actor_username="demo",
                target_user_id="user-1",
                target_username="demo",
                status="failed",
                service="keycloak",
                message="Keycloak login failed",
                created_at=checkpoint_time,
            ),
            AdminAuditEvent(
                event_id="event-c",
                event_type="auth_register",
                category="auth",
                actor_user_id="user-2",
                actor_username="new-user",
                target_user_id="user-2",
                target_username="new-user",
                status="succeeded",
                service="keycloak",
                message="Keycloak register succeeded",
                created_at=datetime(2026, 4, 30, 18, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    emitted: list[AdminAuditEvent] = []
    sync = integrations.KeycloakAuthEventSync(
        keycloak=keycloak,
        checkpoint_store=repository,
        batch_size=50,
        interval_seconds=30,
        emit_event=emitted.append,
    )

    synced = asyncio.run(sync.sync_once())
    synced_again = asyncio.run(sync.sync_once())

    assert synced == 2
    assert [event.event_id for event in emitted] == ["event-b", "event-c"]
    assert repository.get_auth_event_sync_checkpoint() == (
        datetime(2026, 4, 30, 18, 1, tzinfo=timezone.utc),
        "event-c",
    )
    assert synced_again == 0


def test_elasticsearch_audit_client_queries_indexed_auth_events() -> None:
    integrations = load_service_module("activity", "app.services.admin_integrations")
    client = integrations.ElasticsearchAuditClient(elasticsearch_url="http://elasticsearch:9200")
    captured_payload: dict[str, object] = {}

    async def fake_search(payload: dict[str, object]) -> dict[str, object]:
        nonlocal captured_payload
        captured_payload = payload
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "auth-1",
                        "_source": {
                            "@timestamp": "2026-05-02T10:24:13.101Z",
                            "event_name": "auth_login_failed",
                            "event_category": "auth",
                            "service": "keycloak",
                            "status": "failed",
                            "message": "Keycloak login failed",
                            "username": "demo",
                            "email": "demo@example.com",
                            "actor_user_id": "user-1",
                            "actor_username": "demo",
                            "actor_email": "demo@example.com",
                            "target_user_id": "user-1",
                            "target_username": "demo",
                            "target_email": "demo@example.com",
                            "client_ip": "203.0.113.10",
                            "error": "invalid_user_credentials",
                        },
                    }
                ]
            }
        }

    client._search = fake_search  # type: ignore[method-assign]

    events = asyncio.run(client.list_app_audit_events(25))

    assert captured_payload["size"] == 25
    query_terms = captured_payload["query"]["terms"]["event_name.keyword"]  # type: ignore[index]
    for event_name in [
        "auth_login",
        "auth_login_failed",
        "auth_register",
        "auth_register_failed",
        "admin_password_reset",
    ]:
        assert event_name in query_terms
    assert len(events) == 1
    assert events[0].event_type == "auth_login_failed"
    assert events[0].service == "keycloak"
    assert events[0].actor_username == "demo"
    assert events[0].metadata == {
        "client_ip": "203.0.113.10",
        "error": "invalid_user_credentials",
    }


def test_admin_service_audit_uses_indexed_events_not_live_keycloak() -> None:
    activity = load_service_module("activity")
    admin_module = load_service_module("activity", "app.services.admin")

    class ExplodingKeycloakGateway:
        async def list_users(self):
            raise AssertionError("list_users should not be called")

        async def set_enabled(self, user_id: str, enabled: bool):
            raise AssertionError("set_enabled should not be called")

        async def set_admin_role(self, user_id: str, make_admin: bool):
            raise AssertionError("set_admin_role should not be called")

        async def reset_password(self, user_id: str):
            raise AssertionError("reset_password should not be called")

        async def list_auth_events(self, limit: int):
            raise AssertionError("list_auth_events should not be called")

    indexed_event = AdminAuditEvent(
        event_id="auth-1",
        event_type="auth_login",
        category="auth",
        actor_user_id="user-1",
        actor_username="demo",
        target_user_id="user-1",
        target_username="demo",
        status="succeeded",
        service="keycloak",
        message="Keycloak login succeeded",
        created_at=datetime(2026, 5, 2, 10, 24, 13, tzinfo=timezone.utc),
    )
    audit_gateway = activity.InMemoryAuditLogGateway(audit_events=[indexed_event])
    service = admin_module.AdminService(
        keycloak=ExplodingKeycloakGateway(),
        audit_logs=audit_gateway,
        service_health=activity.InMemoryServiceHealthGateway(),
    )
    actor = AuthenticatedUser(
        subject="admin-1",
        username="admin",
        roles=[STUDYVAULT_ADMIN_ROLE],
    )

    events = asyncio.run(service.list_audit_events(actor, limit=50))

    assert events == [indexed_event]
