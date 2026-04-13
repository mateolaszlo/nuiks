import asyncio
from datetime import datetime, timezone

import pytest

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.models import DriveItem, FileRecord, FolderRecord
from tests.conftest import load_service_module


class FakeCatalogExportClient:
    def __init__(self, batches=None, *, error: Exception | None = None) -> None:
        self.batches = list(batches or [])
        self.error = error
        self.calls: list[tuple[int, int, bool]] = []

    async def export_items(self, *, offset: int, limit: int, include_trashed: bool = True):
        self.calls.append((offset, limit, include_trashed))
        if self.error is not None:
            raise self.error
        if self.batches:
            return self.batches.pop(0)
        reindex_module = load_service_module("search", module_name="app.reindex")
        return reindex_module.CatalogExportBatch(items=[], next_offset=None, has_more=False)


def test_search_reindex_clears_existing_documents_before_rebuild() -> None:
    search_module = load_service_module("search")
    reindex_module = load_service_module("search", module_name="app.reindex")
    stale_file = FileRecord.create(
        owner_id="test-user",
        filename="stale.txt",
        mime_type="text/plain",
        size=5,
        tags=[],
    )
    fresh_file = FileRecord.create(
        owner_id="test-user",
        filename="fresh.txt",
        mime_type="text/plain",
        size=8,
        tags=["new"],
    )
    repository = search_module.InMemorySearchRepository(seed=[stale_file])
    client = FakeCatalogExportClient(
        batches=[
            reindex_module.CatalogExportBatch(
                items=[DriveItem.from_file(fresh_file)],
                next_offset=None,
                has_more=False,
            )
        ]
    )

    result = asyncio.run(reindex_module.run_reindex(repository=repository, client=client, batch_size=10))

    assert result.indexed_items == 1
    assert result.batches_processed == 1
    assert set(repository._records) == {fresh_file.file_id}


def test_search_reindex_processes_multiple_batches_until_complete() -> None:
    search_module = load_service_module("search")
    reindex_module = load_service_module("search", module_name="app.reindex")
    file_one = FileRecord.create(
        owner_id="test-user",
        filename="one.txt",
        mime_type="text/plain",
        size=1,
        tags=[],
    )
    folder_one = FolderRecord.create(owner_id="test-user", name="Folder One")
    folder_one.created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    folder_one.updated_at = folder_one.created_at
    file_two = FileRecord.create(
        owner_id="test-user",
        filename="two.txt",
        mime_type="text/plain",
        size=2,
        tags=[],
    )
    file_two.trashed_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
    file_two.purge_after = datetime(2026, 5, 11, tzinfo=timezone.utc)

    repository = search_module.InMemorySearchRepository()
    client = FakeCatalogExportClient(
        batches=[
            reindex_module.CatalogExportBatch(
                items=[DriveItem.from_folder(folder_one), DriveItem.from_file(file_one)],
                next_offset=2,
                has_more=True,
            ),
            reindex_module.CatalogExportBatch(
                items=[DriveItem.from_file(file_two)],
                next_offset=None,
                has_more=False,
            ),
        ]
    )

    result = asyncio.run(reindex_module.run_reindex(repository=repository, client=client, batch_size=2))

    assert result.indexed_items == 3
    assert result.batches_processed == 2
    assert client.calls == [(0, 2, True), (2, 2, True)]
    assert repository._records[folder_one.folder_id].kind == "folder"
    assert repository._records[file_two.file_id].trashed_at == datetime(2026, 4, 11, tzinfo=timezone.utc)


def test_search_reindex_handles_empty_export() -> None:
    search_module = load_service_module("search")
    reindex_module = load_service_module("search", module_name="app.reindex")
    repository = search_module.InMemorySearchRepository()
    client = FakeCatalogExportClient(
        batches=[reindex_module.CatalogExportBatch(items=[], next_offset=None, has_more=False)]
    )

    result = asyncio.run(reindex_module.run_reindex(repository=repository, client=client, batch_size=5))

    assert result.indexed_items == 0
    assert result.batches_processed == 1
    assert repository._records == {}


def test_search_reindex_raises_when_catalog_export_fails() -> None:
    search_module = load_service_module("search")
    reindex_module = load_service_module("search", module_name="app.reindex")
    repository = search_module.InMemorySearchRepository()
    client = FakeCatalogExportClient(error=ServiceClientError("GET failed with status 500"))

    with pytest.raises(ServiceClientError):
        asyncio.run(reindex_module.run_reindex(repository=repository, client=client, batch_size=5))


def test_search_reindex_main_returns_non_zero_on_failure(monkeypatch) -> None:
    reindex_module = load_service_module("search", module_name="app.reindex")

    async def failing_run_reindex(*args, **kwargs):
        raise ServiceClientError("GET failed with status 500")

    monkeypatch.setattr(reindex_module, "run_reindex", failing_run_reindex)

    assert reindex_module.main() == 1
