from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.models import FileRecord, FolderRecord
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


def test_catalog_lists_root_items_for_authenticated_user_only() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository(
        seed=[
            FileRecord.create(
                owner_id="test-user",
                filename="syllabus.pdf",
                mime_type="application/pdf",
                size=120,
                tags=["school"],
            ),
            FileRecord.create(
                owner_id="other-user",
                filename="private.pdf",
                mime_type="application/pdf",
                size=42,
                tags=[],
            ),
        ],
        folder_seed=[
            FolderRecord.create(owner_id="test-user", name="Projects"),
            FolderRecord.create(owner_id="other-user", name="Secrets"),
        ],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/catalog/items", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] is None
    assert [(item["kind"], item["name"]) for item in payload["items"]] == [
        ("folder", "Projects"),
        ("file", "syllabus.pdf"),
    ]


def test_catalog_lists_nested_items_for_requested_parent() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Coursework")
    child = FolderRecord.create(owner_id="test-user", name="Week 1", parent_folder_id=parent.folder_id, path_depth=1)
    nested_file = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    nested_file.parent_folder_id = parent.folder_id
    repository = module.InMemoryCatalogRepository(seed=[nested_file], folder_seed=[parent, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/items?parent_id={parent.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] == parent.folder_id
    assert [(item["kind"], item["name"]) for item in payload["items"]] == [
        ("folder", "Week 1"),
        ("file", "notes.txt"),
    ]


def test_catalog_item_listing_excludes_trashed_items_by_default() -> None:
    module = load_service_module("catalog")
    active_file = FileRecord.create(
        owner_id="test-user",
        filename="active.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    trashed_file = FileRecord.create(
        owner_id="test-user",
        filename="trashed.txt",
        mime_type="text/plain",
        size=6,
        tags=[],
    )
    trashed_file.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[active_file, trashed_file])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/catalog/items", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload["items"]] == ["active.txt"]


def test_catalog_item_listing_can_return_trashed_items() -> None:
    module = load_service_module("catalog")
    active_folder = FolderRecord.create(owner_id="test-user", name="Active Folder")
    trashed_folder = FolderRecord.create(owner_id="test-user", name="Trashed Folder")
    trashed_folder.trashed_at = datetime(2026, 4, 7, tzinfo=timezone.utc)
    trashed_folder.purge_after = datetime(2026, 5, 7, tzinfo=timezone.utc)
    trashed_file = FileRecord.create(
        owner_id="test-user",
        filename="trashed.txt",
        mime_type="text/plain",
        size=8,
        tags=[],
    )
    trashed_file.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    trashed_file.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    other_user_trashed = FileRecord.create(
        owner_id="other-user",
        filename="secret.txt",
        mime_type="text/plain",
        size=1,
        tags=[],
    )
    other_user_trashed.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(
        seed=[trashed_file, other_user_trashed],
        folder_seed=[active_folder, trashed_folder],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/items?include_trashed=true",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] is None
    assert [(item["kind"], item["name"]) for item in payload["items"]] == [
        ("folder", "Trashed Folder"),
        ("file", "trashed.txt"),
    ]


def test_catalog_item_listing_returns_not_found_for_unknown_parent() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/items?parent_id=missing-folder",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}
