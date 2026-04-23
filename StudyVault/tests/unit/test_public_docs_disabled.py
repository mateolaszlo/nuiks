from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import load_service_module


class FakeFileDownstream:
    async def publish_catalog(self, file_record, *, bearer_token: str) -> None:
        return None

    async def publish_search(self, file_record, *, bearer_token: str) -> None:
        return None

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        return None

    async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream fetches")

    async def fetch_catalog_folder(self, folder_id: str, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream fetches")

    async def update_catalog_file(self, file_record, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream updates")

    async def move_catalog_file(self, file_record, request, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream moves")

    async def trash_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream trash")

    async def restore_catalog_file(self, file_id: str, owner_id: str, request, *, bearer_token: str):
        raise AssertionError("Docs exposure tests should not call file downstream restore")

    async def hard_delete_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> None:
        raise AssertionError("Docs exposure tests should not call file downstream hard delete")

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        raise AssertionError("Docs exposure tests should not call search deletion")


def _assert_docs_disabled(app) -> None:
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json", "/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json"):
            response = client.get(path)
            assert response.status_code == 404, path


def test_file_service_does_not_expose_generated_docs() -> None:
    module = load_service_module("file")
    app = module.create_app(
        object_store=module.InMemoryObjectStoreRepository(),
        downstream=FakeFileDownstream(),
    )
    _assert_docs_disabled(app)


def test_catalog_service_does_not_expose_generated_docs() -> None:
    module = load_service_module("catalog")
    app = module.create_app(repository=module.InMemoryCatalogRepository())
    _assert_docs_disabled(app)


def test_search_service_does_not_expose_generated_docs() -> None:
    module = load_service_module("search")
    app = module.create_app(repository=module.InMemorySearchRepository())
    _assert_docs_disabled(app)


def test_activity_service_does_not_expose_generated_docs() -> None:
    module = load_service_module("activity")
    app = module.create_app(
        repository=module.InMemoryActivityRepository(),
        keycloak_client=module.InMemoryKeycloakAdminGateway(),
        audit_client=module.InMemoryAuditLogGateway(),
        health_client=module.InMemoryServiceHealthGateway(),
    )
    _assert_docs_disabled(app)
