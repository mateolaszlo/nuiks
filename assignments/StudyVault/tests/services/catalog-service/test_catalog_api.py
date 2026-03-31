from datetime import timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.models import FileRecord
from tests.conftest import load_service_module


def test_catalog_lists_files_for_authenticated_user_only() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository(
        seed=[
            FileRecord.create(
                owner_id="test-user",
                filename="algorithms.pdf",
                mime_type="application/pdf",
                size=200,
                tags=["cs"],
            ),
            FileRecord.create(
                owner_id="other-user",
                filename="private.pdf",
                mime_type="application/pdf",
                size=99,
                tags=["secret"],
            ),
        ]
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/catalog/files", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["owner_id"] == "test-user"
    assert payload[0]["filename"] == "algorithms.pdf"


def test_catalog_internal_create_requires_internal_token() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)
    record = FileRecord.create(
        owner_id="test-user",
        filename="week1.txt",
        mime_type="text/plain",
        size=10,
        tags=["week1"],
    )

    with TestClient(app) as client:
        unauthorized = client.post("/internal/catalog/files", json=record.model_dump(mode="json"))
        authorized = client.post(
            "/internal/catalog/files",
            json=record.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert repository.get_file("test-user", record.file_id) is not None
