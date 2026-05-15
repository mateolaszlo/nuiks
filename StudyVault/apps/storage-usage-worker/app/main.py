from __future__ import annotations

import asyncio

from studyvault_backend_common.logging import configure_logging, get_logger

from app.core.config import get_settings
from app.services.storage_usage import (
    HttpCatalogStorageUsageClient,
    HttpElasticsearchStorageUsageIndexer,
    StorageUsageRunResult,
    StorageUsageService,
)


logger = get_logger(__name__)


def create_service(client=None, indexer=None, *, index_prefix: str | None = None) -> StorageUsageService:
    settings = get_settings()
    configure_logging(settings.service_name)
    if client is None:
        client = HttpCatalogStorageUsageClient(
            catalog_url=settings.catalog_internal_url,
            internal_token=settings.internal_token,
        )
    if indexer is None:
        indexer = HttpElasticsearchStorageUsageIndexer(elasticsearch_url=settings.elasticsearch_url)
    return StorageUsageService(
        client=client,
        indexer=indexer,
        index_prefix=index_prefix or settings.storage_usage_index_prefix,
    )


async def run_snapshot_pass(client=None, indexer=None, *, index_prefix: str | None = None) -> StorageUsageRunResult:
    service = create_service(client=client, indexer=indexer, index_prefix=index_prefix)
    return await service.run_once()


async def run_snapshot_loop(
    client=None,
    indexer=None,
    *,
    index_prefix: str | None = None,
    interval_seconds: int | None = None,
    sleep=asyncio.sleep,
) -> StorageUsageRunResult:
    settings = get_settings()
    effective_interval = (
        interval_seconds if interval_seconds is not None else settings.storage_usage_interval_seconds
    )
    latest_result = StorageUsageRunResult()

    logger.info(
        "storage usage worker loop started",
        event_name="storage_usage_loop_started",
        event_category="observability",
        mode="loop",
        interval_seconds=effective_interval,
        status="started",
    )

    try:
        while True:
            latest_result = await run_snapshot_pass(client=client, indexer=indexer, index_prefix=index_prefix)
            await sleep(effective_interval)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info(
            "storage usage worker loop stopped",
            event_name="storage_usage_loop_stopped",
            event_category="observability",
            mode="loop",
            interval_seconds=effective_interval,
            status="stopped",
        )
        return latest_result


async def run_worker(client=None, indexer=None, *, index_prefix: str | None = None, sleep=asyncio.sleep) -> StorageUsageRunResult:
    settings = get_settings()
    if settings.storage_usage_run_mode == "loop":
        return await run_snapshot_loop(
            client=client,
            indexer=indexer,
            index_prefix=index_prefix,
            interval_seconds=settings.storage_usage_interval_seconds,
            sleep=sleep,
        )
    return await run_snapshot_pass(client=client, indexer=indexer, index_prefix=index_prefix)


def main() -> int:
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
