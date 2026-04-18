from __future__ import annotations

import anyio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import FileRecord, FolderRecord, MoveItemRequest, RestoreItemRequest
from tests.conftest import load_service_module


class FakeDownstream:
    def __init__(self) -> None:
        self.catalog_records: list[FileRecord] = []
        self.search_records: list[FileRecord] = []
        self.activity_file_ids: list[str] = []
        self.activity_actions: list[str] = []
        self.activity_item_kinds: list[str] = []
        self.activity_messages: list[str | None] = []
        self.catalog_folders: dict[str, FolderRecord] = {}
        self.move_error: ServiceClientError | None = None

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.catalog_records.append(file_record)

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.search_records.append(file_record)

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        self.search_records = [record for record in self.search_records if record.file_id != item_id]

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        self.activity_file_ids.append(event.item_id)
        self.activity_actions.append(event.action)
        self.activity_item_kinds.append(event.item_kind)
        self.activity_messages.append(getattr(event, "message", None))

    async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord:
        record = self.fetch_existing_file(file_id)
        if record.owner_id != owner_id:
            raise ServiceClientError(f"GET http://catalog.test/internal/catalog/files/{file_id} failed with status 404")
        return record

    def fetch_existing_file(self, file_id: str) -> FileRecord:
        for record in self.catalog_records:
            if record.file_id == file_id:
                return record
        raise ServiceClientError(f"GET http://catalog.test/internal/catalog/files/{file_id} failed with status 404")

    async def fetch_catalog_folder(self, folder_id: str, *, bearer_token: str) -> FolderRecord:
        folder = self.catalog_folders.get(folder_id)
        if folder is None or folder.owner_id != "test-user":
            raise ServiceClientError(f"GET http://catalog.test/api/v1/catalog/folders/{folder_id} failed with status 404")
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
        if self.move_error is not None:
            raise self.move_error
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

    async def restore_catalog_file(
        self,
        file_id: str,
        owner_id: str,
        request: RestoreItemRequest,
        *,
        bearer_token: str,
    ) -> dict[str, object]:
        existing = self.fetch_existing_file(file_id)
        if existing.owner_id != owner_id:
            raise ServiceClientError(
                f"POST http://catalog.test/internal/catalog/files/{file_id}/restore failed with status 404"
            )
        if existing.trashed_at is None:
            raise ServiceClientError(
                f"POST http://catalog.test/internal/catalog/files/{file_id}/restore failed with status 409"
            )

        target_folder = None
        if request.parent_folder_id is not None:
            target_folder = self.catalog_folders.get(request.parent_folder_id)
            if target_folder is None or target_folder.owner_id != owner_id:
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_id}/restore failed with status 404"
                )
            if target_folder.trashed_at is not None:
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_id}/restore failed with status 409 trashed folder"
                )
        elif existing.original_parent_folder_id is not None:
            original_parent = self.catalog_folders.get(existing.original_parent_folder_id)
            if original_parent is not None and original_parent.owner_id == owner_id and original_parent.trashed_at is None:
                target_folder = original_parent

        target_parent_id = None if target_folder is None else target_folder.folder_id
        for sibling in self.catalog_records:
            if (
                sibling.file_id != existing.file_id
                and sibling.parent_folder_id == target_parent_id
                and sibling.trashed_at is None
                and sibling.filename.casefold() == existing.filename.casefold()
            ):
                raise ServiceClientError(
                    f"POST http://catalog.test/internal/catalog/files/{file_id}/restore failed with status 409 restore"
                )

        restored = existing.model_copy(
            update={
                "parent_folder_id": target_parent_id,
                "trashed_at": None,
                "purge_after": None,
                "original_parent_folder_id": None,
                "updated_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            }
        )
        for index, stored in enumerate(self.catalog_records):
            if stored.file_id == file_id:
                self.catalog_records[index] = restored
                break
        return {
            "file_id": file_id,
            "restored_to_parent_folder_id": target_parent_id,
            "restored_to_root": target_parent_id is None,
            "message": (
                "Original parent was unavailable, file restored to root"
                if request.parent_folder_id is None
                and existing.original_parent_folder_id is not None
                and target_parent_id is None
                else ""
            ),
        }

    async def hard_delete_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> None:
        existing = self.fetch_existing_file(file_id)
        if existing.owner_id != owner_id:
            raise ServiceClientError(
                f"DELETE http://catalog.test/internal/catalog/files/{file_id}/hard-delete failed with status 404"
            )
        if existing.trashed_at is None:
            raise ServiceClientError(
                f"DELETE http://catalog.test/internal/catalog/files/{file_id}/hard-delete failed with status 409"
            )
        self.catalog_records = [record for record in self.catalog_records if record.file_id != file_id]


class RecordingJsonClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str | None, str | None]] = []

    async def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
    ) -> dict[str, object]:
        self.calls.append((url, payload, bearer_token, internal_token))
        return FileRecord.create(
            owner_id="test-user",
            filename="notes.txt",
            mime_type="text/plain",
            size=5,
            tags=[],
        ).model_dump(mode="json")


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
    assert downstream.activity_item_kinds == ["file"]


def test_file_old_unversioned_public_path_returns_not_found() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake", "x-test-raw-path": "true"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
        )

    assert response.status_code == 404


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
    assert downstream.activity_actions[-1] == "item_renamed"
    assert downstream.activity_item_kinds[-1] == "file"


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
    assert downstream.activity_actions[-1] == "item_moved"
    assert downstream.activity_item_kinds[-1] == "file"


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


def test_file_move_returns_generic_invalid_request_for_non_trashed_folder_422() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    target = FolderRecord.create(owner_id="test-user", name="Target")
    downstream.catalog_folders[target.folder_id] = target
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    downstream.catalog_records.append(stored)
    downstream.move_error = ServiceClientError(
        f"POST http://catalog.test/internal/catalog/files/{stored.file_id}/move failed with status 422 "
        '{"detail":"Field required","errors":[{"loc":["query","owner_id"]}]}'
    )
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/move",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "File move request was invalid"


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


def test_http_downstream_move_catalog_file_sends_owner_id_as_query_param() -> None:
    module = load_service_module("file")
    client = RecordingJsonClient()
    downstream = module.HttpDownstreamPublisher(
        catalog_url="http://catalog.test",
        search_url="http://search.test",
        activity_url="http://activity.test",
        internal_token="internal-test-token",
        client=client,
    )
    record = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )

    anyio.run(
        lambda: downstream.move_catalog_file(
            record,
            MoveItemRequest(parent_folder_id="target-folder"),
            bearer_token="fake",
        )
    )

    assert len(client.calls) == 1
    url, payload, bearer_token, internal_token = client.calls[0]
    assert url == f"http://catalog.test/internal/catalog/files/{record.file_id}/move?owner_id=test-user"
    assert payload == {"parent_folder_id": "target-folder"}
    assert bearer_token == "fake"
    assert internal_token == "internal-test-token"


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
    assert downstream.activity_actions[-1] == "item_trashed"
    assert downstream.activity_item_kinds[-1] == "file"


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


def test_file_restore_to_original_parent_succeeds_and_emits_downstream_events() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    original_parent = FolderRecord.create(owner_id="test-user", name="Original")
    downstream.catalog_folders[original_parent.folder_id] = original_parent
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.parent_folder_id = "trash-parent"
    stored.original_parent_folder_id = original_parent.folder_id
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_id"] == stored.file_id
    assert payload["restored_to_parent_folder_id"] == original_parent.folder_id
    assert payload["restored_to_root"] is False
    assert downstream.catalog_records[0].parent_folder_id == original_parent.folder_id
    assert downstream.catalog_records[0].trashed_at is None
    assert downstream.catalog_records[0].original_parent_folder_id is None
    assert downstream.search_records[-1].trashed_at is None
    assert downstream.activity_actions[-1] == "item_restored"
    assert downstream.activity_item_kinds[-1] == "file"


def test_file_restore_explicit_target_overrides_original_parent() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    original_parent = FolderRecord.create(owner_id="test-user", name="Original")
    override_parent = FolderRecord.create(owner_id="test-user", name="Override")
    downstream.catalog_folders[original_parent.folder_id] = original_parent
    downstream.catalog_folders[override_parent.folder_id] = override_parent
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.original_parent_folder_id = original_parent.folder_id
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": override_parent.folder_id},
        )

    assert response.status_code == 200
    assert response.json()["restored_to_parent_folder_id"] == override_parent.folder_id
    assert downstream.catalog_records[0].parent_folder_id == override_parent.folder_id


def test_file_restore_falls_back_to_root_when_original_parent_is_missing() -> None:
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
    stored.original_parent_folder_id = "missing-folder"
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["restored_to_parent_folder_id"] is None
    assert payload["restored_to_root"] is True
    assert payload["message"] == "Original parent was unavailable, file restored to root"
    assert downstream.catalog_records[0].parent_folder_id is None


def test_file_restore_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files/missing-file/restore",
            headers={"authorization": "Bearer fake"},
            json={},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_file_restore_rejects_non_trashed_file() -> None:
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
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File is not trashed"


def test_file_restore_rejects_missing_explicit_target_folder() -> None:
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
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": "missing-folder"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_file_restore_rejects_trashed_explicit_target_folder() -> None:
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
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot restore file into trashed folder"


def test_file_restore_rejects_destination_name_conflict() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    target = FolderRecord.create(owner_id="test-user", name="Target")
    downstream.catalog_folders[target.folder_id] = target
    stored = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    conflict = FileRecord.create(
        owner_id="test-user",
        filename="notes.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    conflict.parent_folder_id = target.folder_id
    downstream.catalog_records.extend([stored, conflict])
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            f"/api/files/{stored.file_id}/restore",
            headers={"authorization": "Bearer fake"},
            json={"parent_folder_id": target.folder_id},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File restore conflict"


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
        async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord:
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


def test_file_hard_delete_requires_internal_token() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        unauthorized = client.delete(f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user")
        authorized = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 204


def test_file_hard_delete_removes_object_and_metadata() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    downstream.search_records.append(stored)
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert stored.object_key not in object_store._objects
    assert downstream.catalog_records == []
    assert downstream.search_records == []


def test_file_hard_delete_returns_not_found_for_unknown_file() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            "/internal/files/missing-file/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_file_hard_delete_rejects_non_trashed_file() -> None:
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
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "File is not trashed"
    assert stored.object_key in object_store._objects


def test_file_hard_delete_succeeds_when_object_content_is_already_missing() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    downstream.search_records.append(stored)
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert downstream.catalog_records == []
    assert downstream.search_records == []


def test_file_hard_delete_returns_bad_gateway_when_object_store_delete_fails() -> None:
    module = load_service_module("file")

    class UnavailableDeleteObjectStore(module.InMemoryObjectStoreRepository):
        def delete(self, object_key: str) -> None:
            raise module.ObjectStoreUnavailableError("backend down")

    object_store = UnavailableDeleteObjectStore()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "File storage unavailable"
    assert downstream.catalog_records[0].file_id == stored.file_id


def test_file_hard_delete_succeeds_when_search_item_is_already_missing() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204
    assert downstream.catalog_records == []
    assert downstream.search_records == []


def test_file_hard_delete_returns_bad_gateway_when_search_delete_fails() -> None:
    module = load_service_module("file")

    class SearchDeleteFailureDownstream(FakeDownstream):
        async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
            raise ServiceClientError(f"DELETE http://search.test/internal/search/items/{item_id} failed with status 500")

    object_store = module.InMemoryObjectStoreRepository()
    downstream = SearchDeleteFailureDownstream()
    stored = FileRecord.create(
        owner_id="test-user",
        filename="trash.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    stored.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    stored.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    downstream.catalog_records.append(stored)
    downstream.search_records.append(stored)
    object_store._objects[stored.object_key] = b"hello"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.delete(
            f"/internal/files/{stored.file_id}/hard-delete?owner_id=test-user",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Search delete failed"
    assert stored.object_key not in object_store._objects
    assert downstream.catalog_records == []
    assert downstream.search_records[0].file_id == stored.file_id


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
