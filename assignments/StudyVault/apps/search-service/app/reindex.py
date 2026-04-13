from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from studyvault_backend_common.http import JsonServiceClient, ServiceClientError
from studyvault_backend_common.logging import configure_logging, get_logger
from studyvault_backend_common.models import DriveItem

from app.core.config import get_settings
from app.repositories.search import MongoSearchRepository, SearchRepository


logger = get_logger(__name__)


@dataclass(slots=True)
class CatalogExportBatch:
    items: list[DriveItem]
    next_offset: int | None
    has_more: bool


@dataclass(slots=True)
class SearchReindexResult:
    indexed_items: int = 0
    batches_processed: int = 0


class CatalogExportClient(Protocol):
    async def export_items(
        self,
        *,
        offset: int,
        limit: int,
        include_trashed: bool = True,
    ) -> CatalogExportBatch: ...


class HttpCatalogExportClient:
    def __init__(self, catalog_url: str, internal_token: str, http_client: JsonServiceClient | None = None) -> None:
        self.catalog_url = catalog_url.rstrip("/")
        self.internal_token = internal_token
        self.http_client = http_client or JsonServiceClient()

    async def export_items(
        self,
        *,
        offset: int,
        limit: int,
        include_trashed: bool = True,
    ) -> CatalogExportBatch:
        query = f"offset={offset}&limit={limit}&include_trashed={'true' if include_trashed else 'false'}"
        payload = await self.http_client.get_json(
            f"{self.catalog_url}/internal/catalog/items/export?{query}",
            internal_token=self.internal_token,
        )
        return CatalogExportBatch(
            items=[DriveItem(**item) for item in payload["items"]],
            next_offset=payload.get("next_offset"),
            has_more=payload.get("has_more", False),
        )


class SearchReindexService:
    def __init__(
        self,
        repository: SearchRepository,
        client: CatalogExportClient,
        *,
        batch_size: int,
    ) -> None:
        self.repository = repository
        self.client = client
        self.batch_size = batch_size

    async def run_once(self) -> SearchReindexResult:
        logger.info(
            "search reindex started",
            event_name="search_reindex_started",
            event_category="search",
            batch_size=self.batch_size,
            status="started",
        )
        self.repository.clear_all()
        logger.info(
            "search index cleared",
            event_name="search_index_cleared",
            event_category="search",
            status="succeeded",
        )

        result = SearchReindexResult()
        offset = 0
        while True:
            batch = await self.client.export_items(
                offset=offset,
                limit=self.batch_size,
                include_trashed=True,
            )
            result.batches_processed += 1
            for item in batch.items:
                self.repository.index_item(item)
            result.indexed_items += len(batch.items)

            logger.info(
                "search reindex batch processed",
                event_name="search_reindex_batch_processed",
                event_category="search",
                offset=offset,
                batch_size=self.batch_size,
                result_count=len(batch.items),
                has_more=batch.has_more,
                status="succeeded",
            )

            if not batch.has_more or batch.next_offset is None:
                break
            offset = batch.next_offset

        logger.info(
            "search reindex finished",
            event_name="search_reindex_finished",
            event_category="search",
            indexed_items=result.indexed_items,
            batches_processed=result.batches_processed,
            status="succeeded",
        )
        return result


def create_service(
    repository: SearchRepository | None = None,
    client: CatalogExportClient | None = None,
    *,
    batch_size: int | None = None,
) -> SearchReindexService:
    settings = get_settings()
    configure_logging(settings.service_name)
    if repository is None:
        repository = MongoSearchRepository(settings.search_mongodb_url, settings.search_database_name)
    if client is None:
        client = HttpCatalogExportClient(
            catalog_url=settings.catalog_internal_url,
            internal_token=settings.internal_token,
        )
    return SearchReindexService(
        repository=repository,
        client=client,
        batch_size=batch_size or settings.search_reindex_batch_size,
    )


async def run_reindex(
    repository: SearchRepository | None = None,
    client: CatalogExportClient | None = None,
    *,
    batch_size: int | None = None,
) -> SearchReindexResult:
    service = create_service(repository=repository, client=client, batch_size=batch_size)
    return await service.run_once()


def main() -> int:
    try:
        asyncio.run(run_reindex())
    except ServiceClientError:
        logger.exception(
            "search reindex failed",
            event_name="search_reindex_failed",
            event_category="search",
            status="failed",
        )
        return 1
    return 0


__all__ = [
    "CatalogExportBatch",
    "CatalogExportClient",
    "HttpCatalogExportClient",
    "SearchReindexResult",
    "SearchReindexService",
    "create_service",
    "main",
    "run_reindex",
]
