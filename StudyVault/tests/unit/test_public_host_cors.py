from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from studyvault_backend_common.http import ServiceClientError
from tests.conftest import load_service_module


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
            lambda client: client.get("/api/catalog/files"),
        ),
        (
            "search",
            lambda module: module.create_app(repository=module.InMemorySearchRepository()),
            lambda client: client.get("/api/search?q=math"),
        ),
        (
            "activity",
            lambda module: module.create_app(
                repository=module.InMemoryActivityRepository(),
                keycloak_client=module.InMemoryKeycloakAdminGateway(),
                audit_client=module.InMemoryAuditLogGateway(),
                health_client=module.InMemoryServiceHealthGateway(),
            ),
            lambda client: client.get("/api/activity/me"),
        ),
        (
            "file",
            lambda module: module.create_app(
                object_store=module.InMemoryObjectStoreRepository(),
                downstream=FakeFileDownstream(),
            ),
            lambda client: client.get("/health"),
        ),
    ],
)
def test_public_services_allow_expected_host(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    app_factory: Callable[[Any], Any],
    requester: Callable[[TestClient], object],
) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", "http://localhost:8080/realms/studyvault")

    module = load_service_module(service_name)
    app = app_factory(module)

    with TestClient(app, base_url="http://localhost") as client:
        response = requester(client)

    assert response.status_code != 400


@pytest.mark.parametrize(
    ("service_name", "app_factory"),
    [
        ("catalog", lambda module: module.create_app(repository=module.InMemoryCatalogRepository())),
        ("search", lambda module: module.create_app(repository=module.InMemorySearchRepository())),
        (
            "activity",
            lambda module: module.create_app(
                repository=module.InMemoryActivityRepository(),
                keycloak_client=module.InMemoryKeycloakAdminGateway(),
                audit_client=module.InMemoryAuditLogGateway(),
                health_client=module.InMemoryServiceHealthGateway(),
            ),
        ),
        (
            "file",
            lambda module: module.create_app(
                object_store=module.InMemoryObjectStoreRepository(),
                downstream=FakeFileDownstream(),
            ),
        ),
    ],
)
def test_public_services_reject_unexpected_host(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    app_factory: Callable[[Any], Any],
) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", "http://localhost:8080/realms/studyvault")

    module = load_service_module(service_name)
    app = app_factory(module)

    with TestClient(app) as client:
        response = client.get("/health", headers={"host": "evil.example"})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_public_services_allow_only_configured_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", "http://localhost:8080/realms/studyvault")

    module = load_service_module("search")
    app = module.create_app(repository=module.InMemorySearchRepository())

    with TestClient(app, base_url="http://localhost") as client:
        allowed = client.options(
            "/api/search",
            headers={
                "origin": "http://localhost:8080",
                "access-control-request-method": "GET",
            },
        )
        blocked = client.options(
            "/api/search",
            headers={
                "origin": "http://evil.example",
                "access-control-request-method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert blocked.status_code == 400
    assert blocked.text == "Disallowed CORS origin"
    assert "access-control-allow-origin" not in blocked.headers
