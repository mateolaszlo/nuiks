from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import FileActivityEvent, FileRecord, FolderRecord, MoveItemRequest
from tests.conftest import load_service_module


class FakeDownstream:
    def __init__(self) -> None:
        self.catalog_records: list[FileRecord] = []
        self.search_records: list[FileRecord] = []
        self.activity_file_ids: list[str] = []
        self.activity_actions: list[str] = []
        self.catalog_folders: dict[str, FolderRecord] = {}

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.catalog_records.append(file_record)

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.search_records.append(file_record)

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        self.activity_file_ids.append(event.file.file_id)
        self.activity_actions.append(event.action)

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        return self.fetch_existing_file(file_id)

    def fetch_existing_file(self, file_id: str) -> FileRecord:
        for record in self.catalog_records:
            if record.file_id == file_id:
                return record
        raise ServiceClientError(f"GET http://catalog.test/internal/catalog/files/{file_id} failed with status 404")

    async def fetch_catalog_folder(self, folder_id: str, *, bearer_token: str) -> FolderRecord:
        folder = self.catalog_folders.get(folder_id)
        if folder is None or folder.owner_id != "test-user":
            raise ServiceClientError(f"GET http://catalog.test/api/catalog/folders/{folder_id} failed with status 404")
        return folder

    async def update_catalog_file(self, file_record: FileRecord, *, bearer_token: str) -> FileRecord:
        existing = self.fetch_existing_file(file_record.file_id)
        if existing.trashed_at is not None:
            raise ServiceClientError(
                f"PATCH http://catalog.test/internal/catalog/files/{file_record.file_id} failed with status 409 trashed"
            )
        for sibling in self.catalog_records:
            if (
                sibling.file_id != file_record.file_id
                and sibling.parent_folder_id == existing.parent_folder_id
                and sibling.trashed_at is None
                and sibling.filename.casefold() == file_record.filename.casefold()
            ):
                raise ServiceClientError(
                    f"PATCH http://catalog.test/internal/catalog/files/{file_record.file_id} failed with status 409 conflict"
                )
        for index, stored in enumerate(self.catalog_records):
            if stored.file_id == file_record.file_id:
                self.catalog_records[index] = file_record
                return file_record
        raise AssertionError("expected file to be present in fake downstream catalog store")

    async def move_catalog_file(
        self,
        file_record: FileRecord,
        request: MoveItemRequest,
        *,
        bearer_token: str,
    ) -> FileRecord:
        existing = self.fetch_existing_file(file_record.file_id)
        if existing.trashed_at is not None:
            raise ServiceClientError(
                f"POST http://catalog.test/internal/catalog/files/{file_record.file_id}/move failed with status 409 trashed"
            )
        if request.parent_folder_id is not None:
            folder = self.catalog_folders.get(request.parent_folder_id)
            if folder is None or folder.owner_id != "test-user":
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_record.file_id}/move failed with status 404"
                )
            if folder.trashed_at is not None:
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_record.file_id}/move failed with status 422"
                )
        for sibling in self.catalog_records:
            if (
                sibling.file_id != file_record.file_id
                and sibling.parent_folder_id == request.parent_folder_id
                and sibling.trashed_at is None
                and sibling.filename.casefold() == existing.filename.casefold()
            ):
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_record.file_id}/move failed with status 409 move"
                )
        moved = existing.model_copy(update={"parent_folder_id": request.parent_folder_id})
        for index, stored in enumerate(self.catalog_records):
            if stored.file_id == file_record.file_id:
                self.catalog_records[index] = moved
                return moved
        raise AssertionError("expected file to be present in fake downstream catalog store")

    async def trash_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord:
        existing = self.fetch_existing_file(file_id)
        if existing.owner_id != owner_id:
            raise ServiceClientError(f"DELETE http://catalog.test/internal/catalog/files/{file_id} failed with status 404")
        if existing.trashed_at is not None:
            return existing
        trashed_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        trashed = existing.model_copy(
            update={
                "updated_at": trashed_at,
                "trashed_at": trashed_at,
                "purge_after": datetime(2026, 5, 11, tzinfo=timezone.utc),
                "original_parent_folder_id": existing.original_parent_folder_id or existing.parent_folder_id,
            }
        )
        for index, stored in enumerate(self.catalog_records):
            if stored.file_id == file_id:
                self.catalog_records[index] = trashed
                return trashed
        raise AssertionError("expected file to be present in fake downstream catalog store")


def test_file_upload_fans_out_to_all_downstream_services() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"tags": "math"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "lecture.txt"
    assert payload["tags"] == ["math"]
    assert payload["parent_folder_id"] is None
    assert len(downstream.catalog_records) == 1
    assert len(downstream.search_records) == 1
    assert downstream.activity_file_ids == [payload["file_id"]]
    assert downstream.activity_actions == ["file_uploaded"]


def test_file_rename_updates_filename_and_emits_downstream_events() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=5,
        tags=["notes"],
    )
    stored.parent_folder_id = "folder-1"
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/files/{stored.file_id}",
            headers={"authorization": "Bearer fake"},
            json={"name": "final.txt"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "final.txt"
    assert payload["parent_folder_id"] == "folder-1"
    assert payload["object_key"] == stored.object_key
    assert downstream.catalog_records[0].filename == "final.txt"
    assert downstream.search_records[-1].filename == "final.txt"
    assert downstream.activity_actions[-1] == "file_renamed"


def test_file_rename_is_noop_for_same_normalized_name() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="Draft.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/files/{stored.file_id}",
            headers={"authorization": "Bearer fake"},
            json={"name": "draft.txt"},
        )

    assert response.status_code == 200
    assert response.json()["filename"] == "Draft.txt"
    assert downstream.search_records == []
    assert downstream.activity_actions == []


def test_file_rename_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            "/api/files/missing-file",
            headers={"authorization": "Bearer fake"},
            json={"name": "final.txt"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_file_rename_rejects_trashed_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/files/{stored.file_id}",
            headers={"authorization": "Bearer fake"},
            json={"name": "final.txt"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot rename trashed file"


def test_file_rename_rejects_same_parent_name_conflict() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    first = FileRecord.create(
        owner_id="test-user",
        filename="draft.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="final.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    first.parent_folder_id = "folder-1"
    second.parent_folder_id = "folder-1"
    downstream.catalog_records.extend([first, second])
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.patch(
            f"/api/files/{first.file_id}",
            headers={"authorization": "Bearer fake"},
            json={"name": "final.txt"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File rename conflict"


def test_file_move_updates_parent_and_emits_downstream_events() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    source = FolderRecord.create(owner_id="test-user", name="Source")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    downstream.catalog_folders[source.folder_id] = source
    downstream.catalog_folders[target.folder_id] = target
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.parent_folder_id = source.folder_id
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] == target.folder_id
    assert downstream.catalog_records[0].parent_folder_id == target.folder_id
    assert downstream.search_records[-1].parent_folder_id == target.folder_id
    assert downstream.activity_actions[-1] == "file_moved"


def test_file_move_to_root_succeeds() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    source = FolderRecord.create(owner_id="test-user", name="Source")
    downstream.catalog_folders[source.folder_id] = source
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.parent_folder_id = source.folder_id
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": None},
        )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] is None


def test_file_move_same_parent_is_noop() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    source = FolderRecord.create(owner_id="test-user", name="Source")
    downstream.catalog_folders[source.folder_id] = source
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.parent_folder_id = source.folder_id
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": source.folder_id},
        )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] == source.folder_id
    assert downstream.search_records == []
    assert downstream.activity_actions == []


def test_file_move_returns_not_found_for_unknown_target_folder() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": "missing-folder"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_file_move_rejects_trashed_target_folder() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    target = FolderRecord.create(owner_id="test-user", name="Target")
    target.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    downstream.catalog_folders[target.folder_id] = target
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot move file into trashed folder"


def test_file_move_rejects_trashed_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": None},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot move trashed file"


def test_file_move_rejects_target_name_conflict() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    source = FolderRecord.create(owner_id="test-user", name="Source")
    target = FolderRecord.create(owner_id="test-user", name="Target")
    downstream.catalog_folders[source.folder_id] = source
    downstream.catalog_folders[target.folder_id] = target
    first = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    first.parent_folder_id = source.folder_id
    second.parent_folder_id = target.folder_id
    downstream.catalog_records.extend([first, second])
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{first.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File move conflict"


def test_file_trash_marks_file_trashed_and_emits_downstream_events() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.parent_folder_id = "folder-1"
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/files/{stored.file_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    assert downstream.catalog_records[0].trashed_at is not None
    assert downstream.catalog_records[0].purge_after is not None
    assert downstream.catalog_records[0].original_parent_folder_id == "folder-1"
    assert downstream.search_records[-1].trashed_at is not None
    assert downstream.activity_actions[-1] == "file_trashed"


def test_file_trash_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            "/api/files/missing-file",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_file_trash_is_idempotent_for_already_trashed_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/api/files/{stored.file_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 204
    assert downstream.search_records == []
    assert downstream.activity_actions == []


def test_file_upload_accepts_parent_folder_id() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    folder = FolderRecord.create(owner_id="test-user", name="Coursework")
    downstream.catalog_folders[folder.folder_id] = folder
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"parent_folder_id": folder.folder_id},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parent_folder_id"] == folder.folder_id
    assert downstream.catalog_records[0].parent_folder_id == folder.folder_id
    assert downstream.search_records[0].parent_folder_id == folder.folder_id
    assert downstream.activity_file_ids == [payload["file_id"]]


def test_file_upload_rejects_unknown_parent_folder() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"parent_folder_id": "missing-folder"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_trashed_parent_folder() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    folder = FolderRecord.create(owner_id="test-user", name="Archived")
    folder.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    downstream.catalog_folders[folder.folder_id] = folder
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"parent_folder_id": folder.folder_id},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot upload file into trashed folder"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_treats_other_users_parent_folder_as_not_found() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    folder = FolderRecord.create(owner_id="other-user", name="Private")
    downstream.catalog_folders[folder.folder_id] = folder
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"parent_folder_id": folder.folder_id},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_empty_content() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_oversize_content() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream, max_upload_bytes=100)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("large.txt", b"x" * 101, "text/plain")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file exceeds the maximum allowed size"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_filename_with_path_separator() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("nested/lecture.txt", b"hello studyvault", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Filename must not contain path separators"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_filename_longer_than_maximum() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)
    long_filename = f"{'a' * 256}.txt"

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": (long_filename, b"hello studyvault", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Filename must be at most 255 characters"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_too_many_tags() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)
    multipart_payload = [("file", ("lecture.txt", b"hello studyvault", "text/plain"))]
    multipart_payload.extend(("tags", (None, f"tag-{index}")) for index in range(21))

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files=multipart_payload,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Tags must contain at most 20 items"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_overlong_tag() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"tags": "x" * 65},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Tags must be at most 64 characters"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_download_streams_content_from_object_store() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
        )
        file_id = upload_response.json()["file_id"]
        download_response = client.get(
            f"/api/files/{file_id}/download",
            headers={"authorization": "Bearer fake"},
        )

    assert download_response.status_code == 200
    assert download_response.content == b"hello studyvault"
    assert download_response.headers["content-type"].startswith("text/plain")
    assert (
        download_response.headers["content-disposition"]
        == 'attachment; filename="lecture.txt"; filename*=UTF-8\'\'lecture.txt'
    )


def test_file_download_sanitizes_unsafe_filename_in_content_disposition() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    legacy_record = FileRecord.model_construct(
        file_id="legacy-file",
        owner_id="test-user",
        filename='bad"\r\nname.txt',
        mime_type="text/plain",
        size=len(b"hello studyvault"),
        tags=[],
        object_key="test-user/legacy-file",
    )

    class LegacyDownstream(FakeDownstream):
        async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
            return legacy_record

    downstream = LegacyDownstream()
    object_store._objects[legacy_record.object_key] = b"hello studyvault"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        download_response = client.get(
            "/api/files/legacy-file/download",
            headers={"authorization": "Bearer fake"},
        )

    header = download_response.headers["content-disposition"]
    assert download_response.status_code == 200
    assert "\r" not in header
    assert "\n" not in header
    assert 'filename="badname.txt"' in header
    assert "filename*=UTF-8''badname.txt" in header


def test_file_download_returns_not_found_when_object_content_is_missing() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
        )
        file_record = downstream.catalog_records[0]
        object_store._objects.pop(file_record.object_key)
        download_response = client.get(
            f"/api/files/{upload_response.json()['file_id']}/download",
            headers={"authorization": "Bearer fake"},
        )

    assert download_response.status_code == 404
    assert download_response.json()["detail"] == "File not found"


def test_file_download_returns_bad_gateway_when_object_store_is_unavailable() -> None:
    module = load_service_module("file")

    class UnavailableObjectStore(module.InMemoryObjectStoreRepository):
        def get(self, object_key: str) -> bytes:
            raise module.ObjectStoreUnavailableError("backend down")

    object_store = UnavailableObjectStore()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
        )
        file_record = downstream.catalog_records[0]
        object_store._objects[file_record.object_key] = b"hello studyvault"
        download_response = client.get(
            f"/api/files/{upload_response.json()['file_id']}/download",
            headers={"authorization": "Bearer fake"},
        )

    assert download_response.status_code == 502
    assert download_response.json()["detail"] == "File storage unavailable"


def test_file_download_emits_encoded_filename_for_non_ascii_name() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("žetón notes.pdf", b"hello studyvault", "application/pdf")},
        )
        file_id = upload_response.json()["file_id"]
        download_response = client.get(
            f"/api/files/{file_id}/download",
            headers={"authorization": "Bearer fake"},
        )

    header = download_response.headers["content-disposition"]
    assert download_response.status_code == 200
    assert 'filename="zeton notes.pdf"' in header
    assert "filename*=UTF-8''%C5%BEet%C3%B3n%20notes.pdf" in header
