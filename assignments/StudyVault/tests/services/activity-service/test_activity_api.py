from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from studyvault_backend_common.models import (
    ActivityRecord,
    AdminAuditEvent,
    AdminErrorRecord,
    AdminServiceHealth,
    AdminUserSummary,
    STUDYVAULT_ADMIN_ROLE,
)
from tests.conftest import load_service_module


def test_activity_returns_recent_events_for_user() -> None:
    module = load_service_module("activity")
    repository = module.InMemoryActivityRepository(
        seed=[
            ActivityRecord(owner_id="test-user", action="file_uploaded", file_id="a", filename="a.txt"),
            ActivityRecord(owner_id="other-user", action="file_uploaded", file_id="b", filename="b.txt"),
        ]
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/activity/me", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["owner_id"] == "test-user"


def test_admin_routes_require_admin_role() -> None:
    module = load_service_module("activity")
    app = module.create_app(
        repository=module.InMemoryActivityRepository(),
        keycloak_client=module.InMemoryKeycloakAdminGateway(),
        audit_client=module.InMemoryAuditLogGateway(),
        health_client=module.InMemoryServiceHealthGateway(),
    )

    with TestClient(app) as client:
        response = client.get("/api/admin/users", headers={"authorization": "Bearer fake"})

    assert response.status_code == 403


def test_admin_routes_return_users_audit_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "false")

    class FakeCache:
        async def get(self, _: str):
            return {"keys": [{"kid": "test-kid", "alg": "RS256", "kty": "RSA"}]}

    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.decode",
        lambda *args, **kwargs: {
            "sub": "admin-user",
            "email": "admin@example.com",
            "preferred_username": "admin",
            "realm_access": {"roles": ["user", STUDYVAULT_ADMIN_ROLE]},
        },
    )

    module = load_service_module("activity")
    admin_user = AdminUserSummary(
        user_id="user-1",
        username="demo",
        email="demo@example.com",
        enabled=True,
        roles=["user"],
        created_at=datetime.now(UTC),
    )
    admin_event = AdminAuditEvent(
        event_id="audit-1",
        event_type="file_upload_succeeded",
        category="file",
        actor_user_id="user-1",
        actor_username="demo",
        target_user_id="user-1",
        target_username="demo",
        filename="notes.txt",
        message="file upload succeeded",
        created_at=datetime.now(UTC),
    )
    app = module.create_app(
        repository=module.InMemoryActivityRepository(),
        keycloak_client=module.InMemoryKeycloakAdminGateway(users=[admin_user], auth_events=[admin_event]),
        audit_client=module.InMemoryAuditLogGateway(
            audit_events=[admin_event],
            errors=[
                AdminErrorRecord(
                    event_id="error-1",
                    service="file-service",
                    message="Upload failed",
                    created_at=datetime.now(UTC),
                )
            ],
            counts={"uploads": 3, "downloads": 2, "searches": 4, "errors": 1},
        ),
        health_client=module.InMemoryServiceHealthGateway(
            services=[AdminServiceHealth(service="file-service", status="healthy", detail="ok")]
        ),
    )

    with TestClient(app) as client:
        users_response = client.get("/api/admin/users", headers={"authorization": "Bearer admin-token"})
        health_response = client.get("/api/admin/health", headers={"authorization": "Bearer admin-token"})
        audit_response = client.get("/api/admin/audit", headers={"authorization": "Bearer admin-token"})
        disable_response = client.post(
            "/api/admin/users/user-1/disable",
            headers={"authorization": "Bearer admin-token"},
        )
        reset_response = client.post(
            "/api/admin/users/user-1/reset-password",
            headers={"authorization": "Bearer admin-token"},
        )

    assert users_response.status_code == 200
    assert users_response.json()[0]["username"] == "demo"
    assert health_response.status_code == 200
    assert health_response.json()["recent_uploads"] == 3
    assert audit_response.status_code == 200
    assert audit_response.json()[0]["event_type"] == "file_upload_succeeded"
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    assert reset_response.status_code == 200
    assert reset_response.json()["temporary_password"] == "sv-test-reset"
