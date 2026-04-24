from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import STUDYVAULT_ADMIN_ROLE
from tests.conftest import load_service_module


class FakeJwksCache:
    async def get(self, jwks_url: str) -> dict[str, Any]:
        return {"keys": [{"kid": "test-kid", "alg": "RS256", "kty": "RSA"}]}


class FakeFileDownstream:
    async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str):
        raise ServiceClientError(
            f"GET http://catalog.test/internal/catalog/files/{file_id} failed with status 404",
            status_code=404,
            detail="File not found",
        )


@pytest.mark.parametrize(
    ("service_name", "app_factory", "requester"),
    [
        (
            "catalog",
            lambda module: module.create_app(repository=module.InMemoryCatalogRepository()),
            lambda client: client.get("/api/catalog/files", headers={"authorization": "Bearer fake-token"}),
        ),
        (
            "search",
            lambda module: module.create_app(repository=module.InMemorySearchRepository()),
            lambda client: client.get("/api/search?q=math", headers={"authorization": "Bearer fake-token"}),
        ),
        (
            "activity",
            lambda module: module.create_app(
                repository=module.InMemoryActivityRepository(),
                keycloak_client=module.InMemoryKeycloakAdminGateway(),
                audit_client=module.InMemoryAuditLogGateway(),
                health_client=module.InMemoryServiceHealthGateway(),
            ),
            lambda client: client.get("/api/activity/me", headers={"authorization": "Bearer fake-token"}),
        ),
        (
            "file",
            lambda module: module.create_app(
                object_store=module.InMemoryObjectStoreRepository(),
                downstream=FakeFileDownstream(),
            ),
            lambda client: client.patch(
                "/api/files/missing",
                json={"name": "renamed.txt"},
                headers={"authorization": "Bearer fake-token"},
            ),
        ),
    ],
)
def test_public_services_validate_jwt_audience(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    app_factory,
    requester,
) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "false")
    decode_calls: list[dict[str, Any]] = []

    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )

    def fake_decode(*args, **kwargs):
        decode_calls.append(kwargs)
        return {
            "sub": "user-1",
            "email": "demo@example.com",
            "preferred_username": "demo",
            "realm_access": {"roles": ["user", STUDYVAULT_ADMIN_ROLE]},
            "aud": "studyvault-frontend",
        }

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.decode", fake_decode)

    module = load_service_module(service_name)
    app = app_factory(module)

    with TestClient(app) as client:
        requester(client)

    assert decode_calls, f"expected jwt.decode to be called for {service_name}"
    assert decode_calls[0]["audience"] == "studyvault-frontend"
    assert decode_calls[0]["options"]["verify_aud"] is True
