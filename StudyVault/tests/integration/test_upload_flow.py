from __future__ import annotations

import anyio
from fastapi import HTTPException

from studyvault_backend_common.models import ActivityRecord, AuthenticatedUser, FileRecord, UserStorageUsage
from tests.conftest import load_service_module


class FakeDownstream:
    def __init__(self) -> None:
        self.catalog_records: dict[str, FileRecord] = {}
        self.search_records: dict[str, FileRecord] = {}
        self.activity_records: list[ActivityRecord] = []
        self.storage_usage = UserStorageUsage(owner_id="test-user", used_bytes=0, max_bytes=1024 * 1024 * 1024)

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.catalog_records[file_record.file_id] = file_record

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.search_records[file_record.file_id] = file_record

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        self.activity_records.append(
            ActivityRecord(
                owner_id=event.owner_id,
                action=event.action,
                item_id=event.item_id,
                item_kind=event.item_kind,
                item_name=event.item_name,
                file_id=event.file_id,
                filename=event.filename,
                created_at=event.created_at,
            )
        )

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        return self.catalog_records[file_id]

    async def fetch_user_storage_usage(self, owner_id: str, *, bearer_token: str) -> UserStorageUsage:
        return self.storage_usage.model_copy(update={"owner_id": owner_id})


class FakeUpload:
    def __init__(self, *, filename: str, content: bytes, content_type: str) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._offset = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def test_upload_flow_produces_metadata_search_and_activity_views() -> None:
    service_module = load_service_module("file", "app.services.files")
    object_store_module = load_service_module("file", "app.repositories.object_store")
    object_store = object_store_module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()

    async def immediate_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    service_module.run_in_threadpool = immediate_run_in_threadpool
    service = service_module.FileService(
        object_store=object_store,
        downstream=downstream,
        max_upload_bytes=1000,
    )
    user = AuthenticatedUser(
        subject="test-user",
        email="test@example.com",
        username="test-user",
        roles=["user"],
        token="fake",
    )
    upload = FakeUpload(filename="summary.md", content=b"# summary", content_type="text/markdown")

    payload = anyio.run(
        lambda: service.upload_file(
            user=user,
            upload=upload,
            tags=["revision"],
            parent_folder_id=None,
        )
    )

    file_id = payload.file_id
    assert file_id in downstream.catalog_records
    assert file_id in downstream.search_records
    assert downstream.activity_records[0].file_id == file_id
    assert object_store.get(downstream.catalog_records[file_id].object_key) == b"# summary"
    assert upload.closed is True


def test_upload_flow_rejects_when_quota_would_be_exceeded() -> None:
    service_module = load_service_module("file", "app.services.files")
    object_store_module = load_service_module("file", "app.repositories.object_store")
    object_store = object_store_module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    downstream.storage_usage = UserStorageUsage(owner_id="test-user", used_bytes=98, max_bytes=100)

    async def immediate_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    service_module.run_in_threadpool = immediate_run_in_threadpool
    service = service_module.FileService(
        object_store=object_store,
        downstream=downstream,
        max_upload_bytes=1000,
    )
    user = AuthenticatedUser(
        subject="test-user",
        email="test@example.com",
        username="test-user",
        roles=["user"],
        token="fake",
    )
    upload = FakeUpload(filename="quota.md", content=b"abcde", content_type="text/markdown")

    try:
        anyio.run(
            lambda: service.upload_file(
                user=user,
                upload=upload,
                tags=["revision"],
                parent_folder_id=None,
            )
        )
    except HTTPException as exc:
        response = exc
    else:
        raise AssertionError("expected quota-exceeded upload to raise HTTPException")

    assert response.status_code == 413
    assert response.detail == "Upload exceeds remaining quota: 2 bytes left, rejected file is 5 bytes."
    assert response.code == "quota_exceeded"
    assert response.category == "validation"
    assert response.context == {
        "max_bytes": 100,
        "used_bytes": 98,
        "remaining_bytes": 2,
        "incoming_file_bytes": 5,
        "exceeded_by_bytes": 3,
    }
    assert downstream.catalog_records == {}
    assert downstream.search_records == {}
    assert downstream.activity_records == []
    assert object_store._objects == {}
    assert upload.closed is True
