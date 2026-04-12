from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import FileRecord, FolderRecord
from tests.conftest import load_service_module


class FakePurgeClient:
    def __init__(
        self,
        batches=None,
        *,
        list_error: Exception | None = None,
        file_errors=None,
        folder_errors=None,
        search_errors=None,
    ) -> None:
        self.batches = list(batches or [])
        self.list_error = list_error
        self.file_errors = file_errors or {}
        self.folder_errors = folder_errors or {}
        self.search_errors = search_errors or {}
        self.deleted_files: list[tuple[str, str]] = []
        self.deleted_folders: list[tuple[str, str]] = []
        self.deleted_search_items: list[str] = []
        self.list_calls = 0

    async def list_expired_trash(self, *, before: datetime, limit: int):
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        if self.batches:
            return self.batches.pop(0)
        module = load_service_module("purge", module_name="app.services.purge")
        return module.ExpiredTrashBatch(files=[], folders=[])

    async def hard_delete_file(self, *, owner_id: str, file_id: str) -> None:
        error = self.file_errors.get(file_id)
        if error is not None:
            raise error
        self.deleted_files.append((owner_id, file_id))

    async def delete_search_item(self, *, item_id: str) -> None:
        error = self.search_errors.get(item_id)
        if error is not None:
            raise error
        self.deleted_search_items.append(item_id)

    async def hard_delete_folder(self, *, owner_id: str, folder_id: str) -> None:
        error = self.folder_errors.get(folder_id)
        if error is not None:
            raise error
        self.deleted_folders.append((owner_id, folder_id))


def test_purge_worker_returns_success_for_empty_expired_trash() -> None:
    module = load_service_module("purge")
    client = FakePurgeClient()

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.batches_processed == 0
    assert result.deleted_files == 0
    assert result.failed_files == 0
    assert result.deleted_folders == 0
    assert result.failed_folders == 0


def test_purge_worker_hard_deletes_expired_files() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="expired.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    batch = service_module.ExpiredTrashBatch(files=[file_record], folders=[])
    client = FakePurgeClient(batches=[batch])

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.batches_processed == 1
    assert result.deleted_files == 1
    assert client.deleted_files == [("test-user", file_record.file_id)]


def test_purge_worker_processes_multiple_batches_until_empty() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    first = FileRecord.create(
        owner_id="test-user",
        filename="first.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="second.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    client = FakePurgeClient(
        batches=[
            service_module.ExpiredTrashBatch(files=[first], folders=[]),
            service_module.ExpiredTrashBatch(files=[second], folders=[]),
            service_module.ExpiredTrashBatch(files=[], folders=[]),
        ]
    )

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=1))

    assert result.batches_processed == 2
    assert result.deleted_files == 2
    assert [file_id for _, file_id in client.deleted_files] == [first.file_id, second.file_id]


def test_purge_worker_hard_deletes_expired_folders_after_search_delete() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    folder = FolderRecord.create(owner_id="test-user", name="Expired")
    client = FakePurgeClient(batches=[service_module.ExpiredTrashBatch(files=[], folders=[folder])])

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.deleted_files == 0
    assert result.deleted_folders == 1
    assert client.deleted_search_items == [folder.folder_id]
    assert client.deleted_folders == [("test-user", folder.folder_id)]


def test_purge_worker_continues_after_per_file_failure() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    first = FileRecord.create(
        owner_id="test-user",
        filename="first.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    second = FileRecord.create(
        owner_id="test-user",
        filename="second.txt",
        mime_type="text/plain",
        size=10,
        tags=[],
    )
    client = FakePurgeClient(
        batches=[service_module.ExpiredTrashBatch(files=[first, second], folders=[])],
        file_errors={first.file_id: ServiceClientError("DELETE failed with status 500")},
    )

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.deleted_files == 1
    assert result.failed_files == 1
    assert client.deleted_files == [("test-user", second.file_id)]


def test_purge_worker_continues_after_per_folder_failure() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    first = FolderRecord.create(owner_id="test-user", name="First")
    second = FolderRecord.create(owner_id="test-user", name="Second")
    client = FakePurgeClient(
        batches=[service_module.ExpiredTrashBatch(files=[], folders=[first, second])],
        folder_errors={first.folder_id: ServiceClientError("DELETE failed with status 409")},
    )

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.deleted_folders == 1
    assert result.failed_folders == 1
    assert client.deleted_search_items == [first.folder_id, second.folder_id]
    assert client.deleted_folders == [("test-user", second.folder_id)]


def test_purge_worker_treats_missing_descendant_folder_as_idempotent() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    root = FolderRecord.create(owner_id="test-user", name="Root", path_depth=0)
    child = FolderRecord.create(owner_id="test-user", name="Child", parent_folder_id=root.folder_id, path_depth=1)
    client = FakePurgeClient(
        batches=[service_module.ExpiredTrashBatch(files=[], folders=[child, root])],
        folder_errors={child.folder_id: ServiceClientError("DELETE failed with status 404")},
    )

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.deleted_folders == 1
    assert result.failed_folders == 0
    assert client.deleted_search_items == [root.folder_id, child.folder_id]
    assert client.deleted_folders == [("test-user", root.folder_id)]


def test_purge_worker_raises_when_catalog_lookup_fails() -> None:
    module = load_service_module("purge")
    client = FakePurgeClient(list_error=ServiceClientError("GET failed with status 500"))

    with pytest.raises(ServiceClientError):
        asyncio.run(module.run_purge_pass(client=client, batch_size=10))
