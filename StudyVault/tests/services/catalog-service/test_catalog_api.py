from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.models import DriveItem, FileRecord, FolderRecord
from tests.conftest import load_service_module


class FakeSearchPublisher:
    def __init__(self) -> None:
        self.published_items: list[DriveItem] = []
        self.deleted_item_ids: list[str] = []
        self.publish_error: Exception | None = None

    async def publish_search_item(self, item: DriveItem, *, bearer_token: str) -> None:
        if self.publish_error is not None:
            raise self.publish_error
        self.published_items.append(item)

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        self.deleted_item_ids.append(item_id)


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


def test_catalog_old_unversioned_public_path_returns_not_found() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/files",
            headers={"authorization": "Bearer fake", "x-test-raw-path": "true"},
        )

    assert response.status_code == 404


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


def test_catalog_internal_file_patch_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)
    updated = record.model_copy(update={"filename": "final.txt", "updated_at": datetime(2026, 4, 10, tzinfo=timezone.utc)})

    with TestClient(app) as client:
        unauthorized = client.patch(
            f"/internal/catalog/files/{record.file_id}",
            json=updated.model_dump(mode="json"),
        )
        authorized = client.patch(
            f"/internal/catalog/files/{record.file_id}",
            json=updated.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json()["filename"] == "final.txt"


def test_catalog_internal_file_patch_rejects_active_sibling_conflict() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    first = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="final.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    first.parent_folder_id = target.folder_id
    second.parent_folder_id = target.folder_id
    repository = module.InMemoryCatalogRepository(seed=[first, second], folder_seed=[target])
    app = module.create_app(repository=repository)
    updated = first.model_copy(update={"filename": "final.txt", "updated_at": datetime(2026, 4, 10, tzinfo=timezone.utc)})

    with TestClient(app) as client:
        response = client.patch(
            f"/internal/catalog/files/{first.file_id}",
            json=updated.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A file named "final.txt" already exists in Target.'
    assert response.json()["code"] == "file_name_conflict"
    assert response.json()["context"]["target_parent_id"] == target.folder_id


def test_catalog_internal_file_patch_rejects_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)
    updated = record.model_copy(update={"filename": "final.txt", "updated_at": datetime(2026, 4, 10, tzinfo=timezone.utc)})

    with TestClient(app) as client:
        response = client.patch(
            f"/internal/catalog/files/{record.file_id}",
            json=updated.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot rename trashed file"


def test_catalog_internal_file_get_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.get(f"/internal/catalog/files/{record.file_id}?owner_id=test-user")
        authorized = client.get(
            f"/internal/catalog/files/{record.file_id}?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json()["file_id"] == record.file_id


def test_catalog_internal_file_get_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/internal/catalog/files/missing-file?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_catalog_internal_export_requires_internal_token() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.get("/internal/catalog/items/export")
        authorized = client.get(
            "/internal/catalog/items/export",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json() == {"items": [], "next_offset": None, "has_more": False}


def test_catalog_internal_export_returns_paginated_drive_items() -> None:
    module = load_service_module("catalog")
    early_folder = FolderRecord.create(owner_id="owner-a", name="Alpha")
    early_folder.created_at = datetime(2026, 4, 10, 8, tzinfo=timezone.utc)
    early_folder.updated_at = early_folder.created_at
    later_file = FileRecord.create(
        owner_id="owner-a",
        filename="notes.txt",
        mime_type="text/plain",
        size=10,
        tags=["study"],
    )
    later_file.created_at = datetime(2026, 4, 10, 9, tzinfo=timezone.utc)
    later_file.updated_at = later_file.created_at
    other_owner_folder = FolderRecord.create(owner_id="owner-b", name="Beta")
    other_owner_folder.created_at = datetime(2026, 4, 10, 7, tzinfo=timezone.utc)
    other_owner_folder.updated_at = other_owner_folder.created_at

    repository = module.InMemoryCatalogRepository(
        seed=[later_file],
        folder_seed=[other_owner_folder, early_folder],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        first_page = client.get(
            "/internal/catalog/items/export?offset=0&limit=2",
            headers={"x-internal-token": "internal-test-token"},
        )
        second_page = client.get(
            "/internal/catalog/items/export?offset=2&limit=2",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert [item["item_id"] for item in first_payload["items"]] == [
        early_folder.folder_id,
        later_file.file_id,
    ]
    assert first_payload["next_offset"] == 2
    assert first_payload["has_more"] is True

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert [item["item_id"] for item in second_payload["items"]] == [other_owner_folder.folder_id]
    assert second_payload["next_offset"] is None
    assert second_payload["has_more"] is False


def test_catalog_internal_export_can_exclude_trashed_items() -> None:
    module = load_service_module("catalog")
    active_file = FileRecord.create(
        owner_id="test-user",
        filename="active.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    trashed_folder = FolderRecord.create(owner_id="test-user", name="Trash Folder")
    trashed_folder.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    trashed_folder.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[active_file], folder_seed=[trashed_folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/internal/catalog/items/export?include_trashed=false",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["item_id"] for item in payload["items"]] == [active_file.file_id]


def test_catalog_internal_file_move_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": None},
        )
        authorized = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": None},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200


def test_catalog_internal_file_move_updates_parent_folder_id() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record], folder_seed=[target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": target.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] == target.folder_id


def test_catalog_internal_file_move_rejects_missing_target_folder() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": "missing-folder"},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_catalog_internal_file_move_rejects_trashed_target_folder() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    target.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record], folder_seed=[target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": target.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot move file into trashed folder"


def test_catalog_internal_file_move_rejects_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": None},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot move trashed file"


def test_catalog_internal_file_move_rejects_target_name_conflict() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    first = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    second.parent_folder_id = target.folder_id
    repository = module.InMemoryCatalogRepository(seed=[first, second], folder_seed=[target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{first.file_id}/move?owner_id=test-user",
            json={"parent_folder_id": target.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A file named "draft.txt" already exists in Target.'
    assert response.json()["code"] == "file_move_conflict"
    assert response.json()["context"]["target_parent_id"] == target.folder_id


def test_catalog_internal_file_trash_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.delete(f"/internal/catalog/files/{record.file_id}?owner_id=test-user")
        authorized = client.delete(
            f"/internal/catalog/files/{record.file_id}?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200


def test_catalog_internal_file_trash_sets_trash_metadata() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.parent_folder_id = "folder-1"
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/files/{record.file_id}?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trashed_at"] is not None
    assert payload["purge_after"] is not None
    assert payload["original_parent_folder_id"] == "folder-1"


def test_catalog_internal_file_trash_is_idempotent_for_already_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/files/{record.file_id}?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    assert response.json()["trashed_at"] == "2026-04-10T00:00:00Z"


def test_catalog_internal_file_trash_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            "/internal/catalog/files/missing-file?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_catalog_internal_file_restore_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={},
        )
        authorized = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200


def test_catalog_internal_file_restore_to_original_parent_succeeds() -> None:
    module = load_service_module("catalog")
    original_parent = FolderRecord.create(owner_id="test-user", name="Original")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.parent_folder_id = "trash-folder"
    record.original_parent_folder_id = original_parent.folder_id
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record], folder_seed=[original_parent])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    assert response.json()["restored_to_parent_folder_id"] == original_parent.folder_id
    restored = repository.get_file("test-user", record.file_id)
    assert restored is not None
    assert restored.parent_folder_id == original_parent.folder_id
    assert restored.trashed_at is None
    assert restored.original_parent_folder_id is None


def test_catalog_internal_file_restore_explicit_target_overrides_original_parent() -> None:
    module = load_service_module("catalog")
    original_parent = FolderRecord.create(owner_id="test-user", name="Original")
    override_parent = FolderRecord.create(owner_id="test-user", name="Override")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.original_parent_folder_id = original_parent.folder_id
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record], folder_seed=[original_parent, override_parent])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={"parent_folder_id": override_parent.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    assert response.json()["restored_to_parent_folder_id"] == override_parent.folder_id


def test_catalog_internal_file_restore_falls_back_to_root_when_original_parent_missing() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.parent_folder_id = "folder-1"
    record.original_parent_folder_id = "missing-folder"
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["restored_to_parent_folder_id"] is None
    assert payload["restored_to_root"] is True
    assert payload["message"] == "Original parent was unavailable, file restored to root"


def test_catalog_internal_file_restore_rejects_non_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File is not trashed"


def test_catalog_internal_file_restore_rejects_missing_explicit_target_folder() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={"parent_folder_id": "missing-folder"},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_catalog_internal_file_restore_rejects_trashed_explicit_target_folder() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    target.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record], folder_seed=[target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={"parent_folder_id": target.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot restore file into trashed folder"


def test_catalog_internal_file_restore_rejects_target_name_conflict() -> None:
    module = load_service_module("catalog")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    existing = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    existing.parent_folder_id = target.folder_id
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record, existing], folder_seed=[target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/internal/catalog/files/{record.file_id}/restore?owner_id=test-user",
            json={"parent_folder_id": target.folder_id},
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A file named "draft.txt" already exists in Target.'
    assert response.json()["code"] == "file_restore_conflict"
    assert response.json()["context"]["target_parent_id"] == target.folder_id


def test_catalog_internal_file_hard_delete_requires_internal_token() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.delete(f"/internal/catalog/files/{record.file_id}/hard-delete?owner_id=test-user")
        authorized = client.delete(
            f"/internal/catalog/files/{record.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 204


def test_catalog_internal_file_hard_delete_removes_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/files/{record.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert repository.get_file("test-user", record.file_id) is None


def test_catalog_internal_file_hard_delete_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            "/internal/catalog/files/missing-file/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_catalog_internal_file_hard_delete_rejects_non_trashed_file() -> None:
    module = load_service_module("catalog")
    record = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    repository = module.InMemoryCatalogRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/files/{record.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File is not trashed"


def test_catalog_internal_folder_hard_delete_requires_internal_token() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Archive")
    folder.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.delete(f"/internal/catalog/folders/{folder.folder_id}/hard-delete?owner_id=test-user")
        authorized = client.delete(
            f"/internal/catalog/folders/{folder.folder_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 204


def test_catalog_internal_folder_hard_delete_removes_trashed_subtree_without_files() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Archive", path_depth=0)
    root.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    root.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    child = FolderRecord.create(owner_id="test-user", name="Child", parent_folder_id=root.folder_id, path_depth=1)
    child.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    child.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/folders/{root.folder_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert repository.get_folder("test-user", root.folder_id) is None
    assert repository.get_folder("test-user", child.folder_id) is None


def test_catalog_internal_folder_hard_delete_returns_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            "/internal/catalog/folders/missing-folder/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_catalog_internal_folder_hard_delete_rejects_non_trashed_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Archive")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/folders/{folder.folder_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Folder is not trashed"


def test_catalog_internal_folder_hard_delete_rejects_subtree_with_files() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Archive", path_depth=0)
    root.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    root.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    child = FolderRecord.create(owner_id="test-user", name="Child", parent_folder_id=root.folder_id, path_depth=1)
    child.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    child.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="leftover.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    file_record.parent_folder_id = child.folder_id
    repository = module.InMemoryCatalogRepository(seed=[file_record], folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/folders/{root.folder_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Folder subtree still contains files"
    assert repository.get_folder("test-user", root.folder_id) is not None
    assert repository.get_folder("test-user", child.folder_id) is not None


def test_catalog_internal_expired_trash_requires_internal_token() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.get("/internal/catalog/trash/expired?before=2026-04-08T00:00:00Z")
        authorized = client.get(
            "/internal/catalog/trash/expired?before=2026-04-08T00:00:00Z",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json() == {"files": [], "folders": []}


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


def test_catalog_gets_folder_for_authenticated_user() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Coursework")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert response.json()["folder_id"] == folder.folder_id
    assert response.json()["name"] == "Coursework"


def test_catalog_get_folder_returns_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/folders/missing-folder",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_catalog_get_folder_returns_not_found_for_other_users_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


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


def test_catalog_breadcrumbs_return_root_to_leaf_chain() -> None:
    module = load_service_module("catalog")
    root_child = FolderRecord.create(owner_id="test-user", name="Projects")
    leaf = FolderRecord.create(
        owner_id="test-user",
        name="2026",
        parent_folder_id=root_child.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[root_child, leaf])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/breadcrumbs/{leaf.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["breadcrumbs"] == [
        {"folder_id": None, "name": "My Drive"},
        {"folder_id": root_child.folder_id, "name": "Projects"},
        {"folder_id": leaf.folder_id, "name": "2026"},
    ]


def test_catalog_breadcrumbs_return_root_and_folder_for_direct_child() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/breadcrumbs/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["breadcrumbs"] == [
        {"folder_id": None, "name": "My Drive"},
        {"folder_id": folder.folder_id, "name": "Projects"},
    ]


def test_catalog_breadcrumbs_return_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/breadcrumbs/missing-folder",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_breadcrumbs_hide_other_users_folder() -> None:
    module = load_service_module("catalog")
    other_user_folder = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[other_user_folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/catalog/breadcrumbs/{other_user_folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_trash_lists_trashed_items_for_authenticated_user_only() -> None:
    module = load_service_module("catalog")
    active_folder = FolderRecord.create(owner_id="test-user", name="Active Folder")
    trashed_folder = FolderRecord.create(owner_id="test-user", name="Folder Trash")
    trashed_folder.trashed_at = datetime(2026, 4, 7, tzinfo=timezone.utc)
    trashed_folder.purge_after = datetime(2026, 5, 7, tzinfo=timezone.utc)
    active_file = FileRecord.create(
        owner_id="test-user",
        filename="active.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    trashed_file = FileRecord.create(
        owner_id="test-user",
        filename="draft.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=42111,
        tags=[],
    )
    trashed_file.trashed_at = datetime(2026, 3, 11, 12, tzinfo=timezone.utc)
    trashed_file.purge_after = datetime(2026, 4, 10, 12, tzinfo=timezone.utc)
    other_user_trashed = FileRecord.create(
        owner_id="other-user",
        filename="secret.txt",
        mime_type="text/plain",
        size=1,
        tags=[],
    )
    other_user_trashed.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(
        seed=[active_file, trashed_file, other_user_trashed],
        folder_seed=[active_folder, trashed_folder],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/catalog/trash", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert [(item["kind"], item["name"]) for item in payload["items"]] == [
        ("file", "draft.docx"),
        ("folder", "Folder Trash"),
    ]


def test_catalog_trash_returns_empty_list_when_no_trashed_items_exist() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository(
        seed=[
            FileRecord.create(
                owner_id="test-user",
                filename="notes.txt",
                mime_type="text/plain",
                size=5,
                tags=[],
            )
        ],
        folder_seed=[FolderRecord.create(owner_id="test-user", name="Projects")],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/catalog/trash", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_catalog_internal_expired_trash_returns_only_expired_items() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository(
        seed=[
            FileRecord(
                file_id="file-expired",
                owner_id="test-user",
                filename="expired.txt",
                mime_type="text/plain",
                size=5,
                tags=[],
                object_key="test-user/file-expired",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, tzinfo=timezone.utc),
            ),
            FileRecord(
                file_id="file-fresh",
                owner_id="test-user",
                filename="fresh.txt",
                mime_type="text/plain",
                size=6,
                tags=[],
                object_key="test-user/file-fresh",
                trashed_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 9, tzinfo=timezone.utc),
            ),
        ],
        folder_seed=[
            FolderRecord(
                folder_id="folder-expired",
                owner_id="test-user",
                name="Expired Folder",
                normalized_name="expired folder",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, tzinfo=timezone.utc),
            ),
            FolderRecord(
                folder_id="folder-fresh",
                owner_id="test-user",
                name="Fresh Folder",
                normalized_name="fresh folder",
                trashed_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 9, tzinfo=timezone.utc),
            ),
        ],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/internal/catalog/trash/expired?before=2026-04-08T00:00:00Z&limit=10",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["file_id"] for item in payload["files"]] == ["file-expired"]
    assert [item["folder_id"] for item in payload["folders"]] == ["folder-expired"]


def test_catalog_internal_expired_trash_applies_limit_per_collection() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository(
        seed=[
            FileRecord(
                file_id="file-1",
                owner_id="test-user",
                filename="a.txt",
                mime_type="text/plain",
                size=1,
                tags=[],
                object_key="test-user/file-1",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc),
            ),
            FileRecord(
                file_id="file-2",
                owner_id="test-user",
                filename="b.txt",
                mime_type="text/plain",
                size=1,
                tags=[],
                object_key="test-user/file-2",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc),
            ),
        ],
        folder_seed=[
            FolderRecord(
                folder_id="folder-1",
                owner_id="test-user",
                name="Folder One",
                normalized_name="folder one",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc),
            ),
            FolderRecord(
                folder_id="folder-2",
                owner_id="test-user",
                name="Folder Two",
                normalized_name="folder two",
                trashed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                purge_after=datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc),
            ),
        ],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/internal/catalog/trash/expired?before=2026-04-09T00:00:00Z&limit=1",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["file_id"] for item in payload["files"]] == ["file-1"]
    assert [item["folder_id"] for item in payload["folders"]] == ["folder-1"]


def test_catalog_internal_expired_trash_rejects_invalid_limit() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        too_small = client.get(
            "/internal/catalog/trash/expired?before=2026-04-08T00:00:00Z&limit=0",
            headers={"x-internal-token": "internal-test-token"},
        )
        too_large = client.get(
            "/internal/catalog/trash/expired?before=2026-04-08T00:00:00Z&limit=501",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert too_small.status_code == 422
    assert too_large.status_code == 422


def test_catalog_creates_root_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Projects", "parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Projects"
    assert payload["parent_folder_id"] is None
    assert payload["path_depth"] == 0
    assert repository.get_folder("test-user", payload["folder_id"]) is not None


def test_catalog_creates_nested_folder_with_parent_depth() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects", path_depth=2)
    repository = module.InMemoryCatalogRepository(folder_seed=[parent])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Week 1", "parent_folder_id": parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["parent_folder_id"] == parent.folder_id
    assert payload["path_depth"] == 3
    assert payload["name"] == "Week 1"


def test_catalog_create_folder_returns_not_found_for_unknown_parent() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Week 1", "parent_folder_id": "missing-folder"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_create_folder_rejects_trashed_parent() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Trash Parent")
    parent.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[parent])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Child", "parent_folder_id": parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot create folder inside trashed folder"
    assert response.json()["code"] == "cannot_create_in_trashed_folder"
    assert response.json()["category"] == "validation"
    assert response.json()["context"]["parent_folder_id"] == parent.folder_id


def test_catalog_create_folder_rejects_duplicate_active_sibling_name() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    existing = FolderRecord.create(owner_id="test-user", name="Week 1", parent_folder_id=parent.folder_id, path_depth=1)
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, existing])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "week 1", "parent_folder_id": parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A folder named "week 1" already exists in Projects.'
    assert response.json()["code"] == "folder_name_conflict"
    assert response.json()["context"]["target_location"] == "Projects"


def test_catalog_create_folder_allows_same_name_under_different_parent() -> None:
    module = load_service_module("catalog")
    first_parent = FolderRecord.create(owner_id="test-user", name="Projects")
    second_parent = FolderRecord.create(owner_id="test-user", name="Archives")
    existing = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=first_parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[first_parent, second_parent, existing])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Week 1", "parent_folder_id": second_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["parent_folder_id"] == second_parent.folder_id


def test_catalog_create_folder_hides_other_users_parent() -> None:
    module = load_service_module("catalog")
    other_user_parent = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[other_user_parent])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Child", "parent_folder_id": other_user_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_renames_root_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Archives"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Archives"
    assert payload["parent_folder_id"] is None
    assert payload["normalized_name"] == "archives"
    assert payload["updated_at"] != folder.updated_at.isoformat().replace("+00:00", "Z")


def test_catalog_renames_nested_folder_without_changing_location() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Week One"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Week One"
    assert payload["parent_folder_id"] == parent.folder_id
    assert payload["path_depth"] == 1


def test_catalog_rename_folder_allows_case_only_change() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Projects"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "projects"
    assert payload["normalized_name"] == "projects"


def test_catalog_rename_folder_returns_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            "/api/catalog/folders/missing-folder",
            json={"name": "Archives"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_rename_folder_hides_other_users_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Shared"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_rename_folder_rejects_trashed_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Trash Me")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Still Trash"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot rename trashed folder"
    assert response.json()["code"] == "cannot_rename_trashed_folder"
    assert response.json()["category"] == "validation"
    assert response.json()["context"]["folder_id"] == folder.folder_id


def test_catalog_rename_folder_rejects_duplicate_active_sibling_name() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    sibling = FolderRecord.create(
        owner_id="test-user",
        name="Week 2",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder, sibling])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "week 2"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A folder named "week 2" already exists in Projects.'
    assert response.json()["code"] == "folder_name_conflict"
    assert response.json()["context"]["target_parent_id"] == parent.folder_id
    assert response.json()["context"]["target_location"] == "Projects"


def test_catalog_rename_folder_allows_name_used_under_different_parent() -> None:
    module = load_service_module("catalog")
    first_parent = FolderRecord.create(owner_id="test-user", name="Projects")
    second_parent = FolderRecord.create(owner_id="test-user", name="Archives")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Drafts",
        parent_folder_id=first_parent.folder_id,
        path_depth=1,
    )
    other_branch_folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 2",
        parent_folder_id=second_parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(
        folder_seed=[first_parent, second_parent, folder, other_branch_folder]
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Week 2"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Week 2"


def test_catalog_trashes_root_folder_and_returns_no_content() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    stored = repository.get_folder("test-user", folder.folder_id)
    assert stored is not None
    assert stored.trashed_at is not None
    assert stored.purge_after is not None
    assert stored.deleted_by_cascade is False
    assert stored.original_parent_folder_id is None


def test_catalog_trash_folder_sets_original_parent_for_nested_root() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    stored = repository.get_folder("test-user", folder.folder_id)
    assert stored is not None
    assert stored.original_parent_folder_id == parent.folder_id
    assert stored.parent_folder_id == parent.folder_id
    assert stored.deleted_by_cascade is False


def test_catalog_trash_folder_cascades_to_descendant_folders_and_files() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=root.folder_id,
        path_depth=1,
    )
    grandchild = FolderRecord.create(
        owner_id="test-user",
        name="Drafts",
        parent_folder_id=child.folder_id,
        path_depth=2,
    )
    child_file = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    child_file.parent_folder_id = child.folder_id
    grandchild_file = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=11,
        tags=[],
    )
    grandchild_file.parent_folder_id = grandchild.folder_id
    repository = module.InMemoryCatalogRepository(
        seed=[child_file, grandchild_file],
        folder_seed=[root, child, grandchild],
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{root.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    stored_root = repository.get_folder("test-user", root.folder_id)
    stored_child = repository.get_folder("test-user", child.folder_id)
    stored_grandchild = repository.get_folder("test-user", grandchild.folder_id)
    stored_child_file = repository.get_file("test-user", child_file.file_id)
    stored_grandchild_file = repository.get_file("test-user", grandchild_file.file_id)
    assert stored_root is not None and stored_root.trashed_at is not None
    assert stored_child is not None and stored_child.trashed_at == stored_root.trashed_at
    assert stored_grandchild is not None and stored_grandchild.trashed_at == stored_root.trashed_at
    assert stored_child.deleted_by_cascade is True
    assert stored_grandchild.deleted_by_cascade is True
    assert stored_child_file is not None and stored_child_file.trashed_at == stored_root.trashed_at
    assert stored_grandchild_file is not None and stored_grandchild_file.trashed_at == stored_root.trashed_at
    assert stored_child_file.original_parent_folder_id == child.folder_id
    assert stored_grandchild_file.original_parent_folder_id == grandchild.folder_id


def test_catalog_trashed_subtree_disappears_from_active_listing() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=root.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        delete_response = client.delete(
            f"/api/catalog/folders/{root.folder_id}",
            headers={"authorization": "Bearer fake"},
        )
        list_response = client.get("/api/catalog/items", headers={"authorization": "Bearer fake"})

    assert delete_response.status_code == 204
    assert list_response.status_code == 200
    assert list_response.json() == {"parent_folder_id": None, "items": []}


def test_catalog_trashed_subtree_appears_in_trash_listing() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=root.folder_id,
        path_depth=1,
    )
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    file_record.parent_folder_id = child.folder_id
    repository = module.InMemoryCatalogRepository(seed=[file_record], folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        delete_response = client.delete(
            f"/api/catalog/folders/{root.folder_id}",
            headers={"authorization": "Bearer fake"},
        )
        trash_response = client.get("/api/catalog/trash", headers={"authorization": "Bearer fake"})

    assert delete_response.status_code == 204
    assert trash_response.status_code == 200
    assert {(item["kind"], item["name"]) for item in trash_response.json()["items"]} == {
        ("folder", "Projects"),
        ("folder", "Week 1"),
        ("file", "notes.txt"),
    }


def test_catalog_trash_folder_returns_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            "/api/catalog/folders/missing-folder",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_trash_folder_hides_other_users_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_trash_folder_is_idempotent_when_already_trashed() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    stored = repository.get_folder("test-user", folder.folder_id)
    assert stored is not None
    assert stored.trashed_at == datetime(2026, 4, 8, tzinfo=timezone.utc)


def test_catalog_moves_root_folder_into_target_parent() -> None:
    module = load_service_module("catalog")
    target_parent = FolderRecord.create(owner_id="test-user", name="Archives", path_depth=0)
    folder = FolderRecord.create(owner_id="test-user", name="Projects", path_depth=0)
    repository = module.InMemoryCatalogRepository(folder_seed=[target_parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": target_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] == target_parent.folder_id
    assert payload["path_depth"] == 1


def test_catalog_moves_nested_folder_to_root() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects", path_depth=0)
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] is None
    assert payload["path_depth"] == 0


def test_catalog_move_folder_updates_descendant_depths() -> None:
    module = load_service_module("catalog")
    target_parent = FolderRecord.create(owner_id="test-user", name="Archive", path_depth=2)
    folder = FolderRecord.create(owner_id="test-user", name="Projects", path_depth=0)
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=folder.folder_id,
        path_depth=1,
    )
    grandchild = FolderRecord.create(
        owner_id="test-user",
        name="Drafts",
        parent_folder_id=child.folder_id,
        path_depth=2,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[target_parent, folder, child, grandchild])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": target_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    moved_child = repository.get_folder("test-user", child.folder_id)
    moved_grandchild = repository.get_folder("test-user", grandchild.folder_id)
    assert moved_child is not None and moved_child.path_depth == 4
    assert moved_grandchild is not None and moved_grandchild.path_depth == 5


def test_catalog_move_folder_is_noop_for_same_parent() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects", path_depth=0)
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] == parent.folder_id
    assert payload["path_depth"] == 1


def test_catalog_move_folder_returns_not_found_for_unknown_source() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders/missing-folder/move",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_move_folder_hides_other_users_source() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="other-user", name="Private")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_move_folder_returns_not_found_for_unknown_target() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": "missing-target"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_move_folder_rejects_trashed_source() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot move trashed folder"
    assert response.json()["code"] == "cannot_move_trashed_folder"
    assert response.json()["category"] == "validation"
    assert response.json()["context"]["folder_id"] == folder.folder_id


def test_catalog_move_folder_rejects_trashed_target() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    target = FolderRecord.create(owner_id="test-user", name="Archive")
    target.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder, target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": target.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot move folder into trashed folder"
    assert response.json()["code"] == "cannot_move_into_trashed_folder"
    assert response.json()["category"] == "validation"
    assert response.json()["context"]["target_parent_id"] == target.folder_id


def test_catalog_move_folder_rejects_move_into_itself() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": folder.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot move folder into itself or its descendant"
    assert response.json()["code"] == "invalid_folder_move_target"
    assert response.json()["category"] == "conflict"
    assert response.json()["context"]["folder_id"] == folder.folder_id
    assert response.json()["context"]["target_parent_id"] == folder.folder_id


def test_catalog_move_folder_rejects_move_into_descendant() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=folder.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[folder, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": child.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot move folder into itself or its descendant"
    assert response.json()["code"] == "invalid_folder_move_target"
    assert response.json()["category"] == "conflict"
    assert response.json()["context"]["folder_id"] == folder.folder_id
    assert response.json()["context"]["target_parent_id"] == child.folder_id


def test_catalog_move_folder_rejects_conflicting_name_in_target_parent() -> None:
    module = load_service_module("catalog")
    source_parent = FolderRecord.create(owner_id="test-user", name="Source")
    target_parent = FolderRecord.create(owner_id="test-user", name="Target")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Projects",
        parent_folder_id=source_parent.folder_id,
        path_depth=1,
    )
    conflict = FolderRecord.create(
        owner_id="test-user",
        name="projects",
        parent_folder_id=target_parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[source_parent, target_parent, folder, conflict])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": target_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A folder named "Projects" already exists in Target.'
    assert response.json()["code"] == "folder_move_conflict"
    assert response.json()["context"]["target_parent_id"] == target_parent.folder_id
    assert response.json()["context"]["target_location"] == "Target"


def test_catalog_move_folder_allows_non_conflicting_target_parent() -> None:
    module = load_service_module("catalog")
    source_parent = FolderRecord.create(owner_id="test-user", name="Source")
    target_parent = FolderRecord.create(owner_id="test-user", name="Target")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Projects",
        parent_folder_id=source_parent.folder_id,
        path_depth=1,
    )
    other_target_child = FolderRecord.create(
        owner_id="test-user",
        name="Archive",
        parent_folder_id=target_parent.folder_id,
        path_depth=1,
    )
    repository = module.InMemoryCatalogRepository(folder_seed=[source_parent, target_parent, folder, other_target_child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/move",
            json={"parent_folder_id": target_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] == target_parent.folder_id


def test_catalog_restores_folder_to_original_parent() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    folder.original_parent_folder_id = parent.folder_id
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "folder_id": folder.folder_id,
        "restored_to_parent_folder_id": parent.folder_id,
        "restored_to_root": False,
        "message": "",
    }
    restored = repository.get_folder("test-user", folder.folder_id)
    assert restored is not None
    assert restored.trashed_at is None
    assert restored.purge_after is None
    assert restored.original_parent_folder_id is None


def test_catalog_restore_folder_falls_back_to_root_when_original_parent_missing() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id="missing-parent",
        path_depth=1,
    )
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    folder.original_parent_folder_id = "missing-parent"
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "folder_id": folder.folder_id,
        "restored_to_parent_folder_id": None,
        "restored_to_root": True,
        "message": "Original parent was unavailable, item restored to root",
    }
    restored = repository.get_folder("test-user", folder.folder_id)
    assert restored is not None
    assert restored.parent_folder_id is None
    assert restored.path_depth == 0


def test_catalog_restore_folder_allows_explicit_target_override() -> None:
    module = load_service_module("catalog")
    original_parent = FolderRecord.create(owner_id="test-user", name="Projects")
    override_parent = FolderRecord.create(owner_id="test-user", name="Archive")
    folder = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=original_parent.folder_id,
        path_depth=1,
    )
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    folder.original_parent_folder_id = original_parent.folder_id
    repository = module.InMemoryCatalogRepository(folder_seed=[original_parent, override_parent, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": override_parent.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    restored = repository.get_folder("test-user", folder.folder_id)
    assert restored is not None
    assert restored.parent_folder_id == override_parent.folder_id
    assert restored.path_depth == 1


def test_catalog_restore_folder_restores_descendants_and_files() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=root.folder_id,
        path_depth=1,
    )
    child.deleted_by_cascade = True
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    file_record.parent_folder_id = child.folder_id
    for folder in (root, child):
        folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
        folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
        folder.original_parent_folder_id = folder.parent_folder_id
    file_record.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    file_record.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    file_record.original_parent_folder_id = child.folder_id
    repository = module.InMemoryCatalogRepository(seed=[file_record], folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{root.folder_id}/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )
        active_response = client.get("/api/catalog/items", headers={"authorization": "Bearer fake"})
        trash_response = client.get("/api/catalog/trash", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    restored_child = repository.get_folder("test-user", child.folder_id)
    restored_file = repository.get_file("test-user", file_record.file_id)
    assert restored_child is not None and restored_child.trashed_at is None
    assert restored_child.deleted_by_cascade is False
    assert restored_child.original_parent_folder_id is None
    assert restored_file is not None and restored_file.trashed_at is None
    assert restored_file.original_parent_folder_id is None
    assert active_response.status_code == 200
    assert {(item["kind"], item["name"]) for item in active_response.json()["items"]} == {("folder", "Projects")}
    assert trash_response.status_code == 200
    assert trash_response.json() == {"items": []}


def test_catalog_restore_folder_returns_not_found_for_unknown_folder() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders/missing-folder/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_restore_folder_returns_not_found_for_unknown_target() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": "missing-target"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Folder not found"}


def test_catalog_restore_folder_rejects_non_trashed_folder() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Folder is not trashed"}


def test_catalog_restore_folder_rejects_trashed_target_parent() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    target = FolderRecord.create(owner_id="test-user", name="Archive")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    target.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder, target])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": target.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot restore folder into trashed folder"
    assert response.json()["code"] == "cannot_restore_into_trashed_folder"
    assert response.json()["category"] == "conflict"
    assert response.json()["context"]["folder_id"] == folder.folder_id
    assert response.json()["context"]["target_parent_id"] == target.folder_id


def test_catalog_restore_folder_rejects_restore_into_descendant() -> None:
    module = load_service_module("catalog")
    root = FolderRecord.create(owner_id="test-user", name="Projects")
    child = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=root.folder_id,
        path_depth=1,
    )
    for folder in (root, child):
        folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
        folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[root, child])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{root.folder_id}/restore",
            json={"parent_folder_id": child.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot restore folder into itself or its descendant"
    assert response.json()["code"] == "invalid_folder_restore_target"
    assert response.json()["category"] == "conflict"
    assert response.json()["context"]["folder_id"] == root.folder_id
    assert response.json()["context"]["target_parent_id"] == child.folder_id


def test_catalog_restore_folder_rejects_conflicting_active_sibling_name() -> None:
    module = load_service_module("catalog")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    active_conflict = FolderRecord.create(
        owner_id="test-user",
        name="Week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    folder = FolderRecord.create(
        owner_id="test-user",
        name="week 1",
        parent_folder_id=parent.folder_id,
        path_depth=1,
    )
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    folder.original_parent_folder_id = parent.folder_id
    repository = module.InMemoryCatalogRepository(folder_seed=[parent, active_conflict, folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={"parent_folder_id": None},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == 'A folder named "week 1" already exists in Projects.'
    assert response.json()["code"] == "folder_restore_conflict"
    assert response.json()["context"]["target_parent_id"] == parent.folder_id
    assert response.json()["context"]["target_location"] == "Projects"


def test_catalog_create_folder_publishes_folder_search_item() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Projects"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 201
    assert len(downstream.published_items) == 1
    published = downstream.published_items[0]
    assert published.kind == "folder"
    assert published.name == "Projects"
    assert published.item_id == response.json()["folder_id"]


def test_catalog_create_folder_returns_success_when_search_publish_fails_after_persist() -> None:
    module = load_service_module("catalog")
    repository = module.InMemoryCatalogRepository()
    downstream = FakeSearchPublisher()
    downstream.publish_error = RuntimeError("search unavailable")
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/catalog/folders",
            json={"name": "Projects"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Projects"
    assert repository.get_folder("test-user", payload["folder_id"]) is not None
    assert downstream.published_items == []


def test_catalog_rename_folder_publishes_updated_folder_search_item() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/catalog/folders/{folder.folder_id}",
            json={"name": "Archives"},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert downstream.published_items[-1].item_id == folder.folder_id
    assert downstream.published_items[-1].name == "Archives"


def test_catalog_move_folder_publishes_updated_parent_folder_id() -> None:
    module = load_service_module("catalog")
    source = FolderRecord.create(owner_id="test-user", name="Projects")
    target = FolderRecord.create(owner_id="test-user", name="Archive")
    repository = module.InMemoryCatalogRepository(folder_seed=[source, target])
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{source.folder_id}/move",
            json={"parent_folder_id": target.folder_id},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert downstream.published_items[-1].item_id == source.folder_id
    assert downstream.published_items[-1].parent_folder_id == target.folder_id


def test_catalog_trash_folder_publishes_trashed_folder_search_item() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/catalog/folders/{folder.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    assert downstream.published_items[-1].item_id == folder.folder_id
    assert downstream.published_items[-1].trashed_at is not None


def test_catalog_restore_folder_publishes_active_folder_search_item() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/catalog/folders/{folder.folder_id}/restore",
            json={},
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    assert downstream.published_items[-1].item_id == folder.folder_id
    assert downstream.published_items[-1].trashed_at is None


def test_catalog_internal_hard_delete_folder_deletes_search_item() -> None:
    module = load_service_module("catalog")
    folder = FolderRecord.create(owner_id="test-user", name="Projects")
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    folder.purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    repository = module.InMemoryCatalogRepository(folder_seed=[folder])
    downstream = FakeSearchPublisher()
    app = module.create_app(repository=repository, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/catalog/folders/{folder.folder_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert downstream.deleted_item_ids == [folder.folder_id]
