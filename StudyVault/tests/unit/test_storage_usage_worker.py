from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from studyvault_backend_common.models import StorageUsageSummary, StorageUsageTotals
from tests.conftest import load_service_module


class FakeStorageUsageClient:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def get_storage_usage(self):
        self.calls += 1
        return self.snapshot


class FakeStorageUsageIndexer:
    def __init__(self) -> None:
        self.documents: list[tuple[str, str, dict[str, object]]] = []

    async def index_document(self, *, index_name: str, document_id: str, payload: dict[str, object]) -> None:
        self.documents.append((index_name, document_id, payload))


def test_storage_usage_worker_indexes_user_and_global_snapshots() -> None:
    service_module = load_service_module("storage_usage", module_name="app.services.storage_usage")
    snapshot = service_module.StorageUsageSnapshot(
        users=[
            StorageUsageSummary(
                owner_id="user-a",
                active_bytes=10,
                trashed_bytes=5,
                total_bytes=15,
                active_file_count=1,
                trashed_file_count=1,
                total_file_count=2,
            ),
            StorageUsageSummary(
                owner_id="user-b",
                active_bytes=7,
                trashed_bytes=0,
                total_bytes=7,
                active_file_count=1,
                trashed_file_count=0,
                total_file_count=1,
            ),
        ],
        global_totals=StorageUsageTotals(
            active_bytes=17,
            trashed_bytes=5,
            total_bytes=22,
            active_file_count=2,
            trashed_file_count=1,
            total_file_count=3,
        ),
    )
    client = FakeStorageUsageClient(snapshot)
    indexer = FakeStorageUsageIndexer()
    service = service_module.StorageUsageService(
        client=client,
        indexer=indexer,
        index_prefix="studyvault-storage",
    )

    result = asyncio.run(
        service.run_once(
            now=datetime(2026, 5, 15, tzinfo=timezone.utc),
        )
    )

    assert client.calls == 1
    assert result.indexed_user_documents == 2
    assert result.indexed_global_documents == 1
    assert [entry[0] for entry in indexer.documents] == [
        "studyvault-storage-2026.05.15",
        "studyvault-storage-2026.05.15",
        "studyvault-storage-2026.05.15",
    ]
    assert [entry[1] for entry in indexer.documents] == [
        "user-user-a-20260515T000000Z",
        "user-user-b-20260515T000000Z",
        "global-20260515T000000Z",
    ]
    assert indexer.documents[0][2]["scope"] == "user"
    assert indexer.documents[0][2]["owner_id"] == "user-a"
    assert indexer.documents[0][2]["total_bytes"] == 15
    assert indexer.documents[2][2] == {
        "@timestamp": "2026-05-15T00:00:00Z",
        "scope": "global",
        "active_bytes": 17,
        "trashed_bytes": 5,
        "total_bytes": 22,
        "active_file_count": 2,
        "trashed_file_count": 1,
        "total_file_count": 3,
        "service": "catalog-service",
        "event_name": "storage_usage_snapshot",
    }


def test_storage_usage_worker_defaults_to_once_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    config_module = load_service_module("storage_usage", module_name="app.core.config")
    monkeypatch.delenv("STORAGE_USAGE_RUN_MODE", raising=False)
    monkeypatch.delenv("STORAGE_USAGE_INTERVAL_SECONDS", raising=False)
    config_module.get_settings.cache_clear()

    settings = config_module.get_settings()

    assert settings.storage_usage_run_mode == "once"
    assert settings.storage_usage_interval_seconds == 3600


def test_storage_usage_worker_loop_mode_runs_until_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_service_module("storage_usage")
    service_module = load_service_module("storage_usage", module_name="app.services.storage_usage")
    config_module = load_service_module("storage_usage", module_name="app.core.config")
    monkeypatch.setenv("STORAGE_USAGE_RUN_MODE", "loop")
    monkeypatch.setenv("STORAGE_USAGE_INTERVAL_SECONDS", "5")
    config_module.get_settings.cache_clear()

    snapshot = service_module.StorageUsageSnapshot(
        users=[],
        global_totals=StorageUsageTotals(
            active_bytes=0,
            trashed_bytes=0,
            total_bytes=0,
            active_file_count=0,
            trashed_file_count=0,
            total_file_count=0,
        ),
    )
    client = FakeStorageUsageClient(snapshot)
    indexer = FakeStorageUsageIndexer()
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    result = asyncio.run(module.run_worker(client=client, indexer=indexer, sleep=fake_sleep))

    assert result.indexed_user_documents == 0
    assert result.indexed_global_documents == 1
    assert client.calls == 1
    assert sleep_calls == [5]
