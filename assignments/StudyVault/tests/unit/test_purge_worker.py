from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import FileRecord, FolderRecord
from tests.conftest import load_service_module


class FakePurgeClient:
    def __init__(self, batches=None, *, list_error: Exception | None = None, file_errors=None) -> None:
        self.batches = list(batches or [])
        self.list_error = list_error
        self.file_errors = file_errors or {}
        self.deleted: list[tuple[str, str]] = []
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
        self.deleted.append((owner_id, file_id))


def test_purge_worker_returns_success_for_empty_expired_trash() -> None:
    module = load_service_module("purge")
    client = FakePurgeClient()

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.batches_processed == 0
    assert result.deleted_files == 0
    assert result.failed_files == 0
    assert result.ignored_folders == 0


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
    assert client.deleted == [("test-user", file_record.file_id)]


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
    assert [file_id for _, file_id in client.deleted] == [first.file_id, second.file_id]


def test_purge_worker_ignores_expired_folders_in_this_phase() -> None:
    module = load_service_module("purge")
    service_module = load_service_module("purge", module_name="app.services.purge")
    folder = FolderRecord.create(owner_id="test-user", name="Expired")
    client = FakePurgeClient(batches=[service_module.ExpiredTrashBatch(files=[], folders=[folder])])

    result = asyncio.run(module.run_purge_pass(client=client, batch_size=10))

    assert result.deleted_files == 0
    assert result.ignored_folders == 1
    assert client.deleted == []


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
    assert client.deleted == [("test-user", second.file_id)]


def test_purge_worker_raises_when_catalog_lookup_fails() -> None:
    module = load_service_module("purge")
    client = FakePurgeClient(list_error=ServiceClientError("GET failed with status 500"))

    with pytest.raises(ServiceClientError):
        asyncio.run(module.run_purge_pass(client=client, batch_size=10))
