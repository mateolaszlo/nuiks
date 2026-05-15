from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import quote

from studyvault_backend_common.http import JsonServiceClient
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import StorageUsageSummary, StorageUsageTotals, utcnow


logger = get_logger(__name__)


@dataclass(slots=True)
class StorageUsageSnapshot:
    users: list[StorageUsageSummary]
    global_totals: StorageUsageTotals


@dataclass(slots=True)
class StorageUsageRunResult:
    indexed_user_documents: int = 0
    indexed_global_documents: int = 0


class StorageUsageClient(Protocol):
    async def get_storage_usage(self) -> StorageUsageSnapshot: ...


class StorageUsageIndexer(Protocol):
    async def index_document(self, *, index_name: str, document_id: str, payload: dict[str, object]) -> None: ...


class HttpCatalogStorageUsageClient:
    def __init__(self, catalog_url: str, internal_token: str, http_client: JsonServiceClient | None = None) -> None:
        self.catalog_url = catalog_url.rstrip("/")
        self.internal_token = internal_token
        self.http_client = http_client or JsonServiceClient()

    async def get_storage_usage(self) -> StorageUsageSnapshot:
        payload = await self.http_client.get_json(
            f"{self.catalog_url}/internal/catalog/storage-usage",
            internal_token=self.internal_token,
        )
        return StorageUsageSnapshot(
            users=[StorageUsageSummary(**item) for item in payload.get("users", [])],
            global_totals=StorageUsageTotals(**payload.get("global_totals", {})),
        )


class HttpElasticsearchStorageUsageIndexer:
    def __init__(self, elasticsearch_url: str, http_client: JsonServiceClient | None = None) -> None:
        self.elasticsearch_url = elasticsearch_url.rstrip("/")
        self.http_client = http_client or JsonServiceClient()

    async def index_document(self, *, index_name: str, document_id: str, payload: dict[str, object]) -> None:
        encoded_id = quote(document_id, safe="")
        await self.http_client.put_json(
            f"{self.elasticsearch_url}/{index_name}/_doc/{encoded_id}",
            payload,
        )


class StorageUsageService:
    def __init__(
        self,
        client: StorageUsageClient,
        indexer: StorageUsageIndexer,
        *,
        index_prefix: str,
    ) -> None:
        self.client = client
        self.indexer = indexer
        self.index_prefix = index_prefix

    async def run_once(self, *, now: datetime | None = None) -> StorageUsageRunResult:
        snapshot_time = now or utcnow()
        timestamp = snapshot_time.isoformat().replace("+00:00", "Z")
        snapshot = await self.client.get_storage_usage()
        index_name = f"{self.index_prefix}-{snapshot_time:%Y.%m.%d}"
        result = StorageUsageRunResult()

        logger.info(
            "storage usage snapshot started",
            event_name="storage_usage_snapshot_started",
            event_category="observability",
            index_name=index_name,
            owner_count=len(snapshot.users),
            status="started",
        )

        for user_usage in snapshot.users:
            await self.indexer.index_document(
                index_name=index_name,
                document_id=f"user-{user_usage.owner_id}-{snapshot_time:%Y%m%dT%H%M%SZ}",
                payload={
                    "@timestamp": timestamp,
                    "scope": "user",
                    "owner_id": user_usage.owner_id,
                    "active_bytes": user_usage.active_bytes,
                    "trashed_bytes": user_usage.trashed_bytes,
                    "total_bytes": user_usage.total_bytes,
                    "active_file_count": user_usage.active_file_count,
                    "trashed_file_count": user_usage.trashed_file_count,
                    "total_file_count": user_usage.total_file_count,
                    "service": "catalog-service",
                    "event_name": "storage_usage_snapshot",
                },
            )
            result.indexed_user_documents += 1

        await self.indexer.index_document(
            index_name=index_name,
            document_id=f"global-{snapshot_time:%Y%m%dT%H%M%SZ}",
            payload={
                "@timestamp": timestamp,
                "scope": "global",
                "active_bytes": snapshot.global_totals.active_bytes,
                "trashed_bytes": snapshot.global_totals.trashed_bytes,
                "total_bytes": snapshot.global_totals.total_bytes,
                "active_file_count": snapshot.global_totals.active_file_count,
                "trashed_file_count": snapshot.global_totals.trashed_file_count,
                "total_file_count": snapshot.global_totals.total_file_count,
                "service": "catalog-service",
                "event_name": "storage_usage_snapshot",
            },
        )
        result.indexed_global_documents = 1

        logger.info(
            "storage usage snapshot finished",
            event_name="storage_usage_snapshot_finished",
            event_category="observability",
            index_name=index_name,
            indexed_user_documents=result.indexed_user_documents,
            indexed_global_documents=result.indexed_global_documents,
            total_bytes=snapshot.global_totals.total_bytes,
            status="succeeded",
        )
        return result
