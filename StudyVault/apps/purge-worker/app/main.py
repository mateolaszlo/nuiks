from __future__ import annotations

import asyncio

from studyvault_backend_common.logging import configure_logging, get_logger

from app.core.config import get_settings
from app.services.purge import HttpPurgeClient, PurgeService, PurgeRunResult

logger = get_logger(__name__)


def create_service(client=None, batch_size: int | None = None) -> PurgeService:
    settings = get_settings()
    configure_logging(settings.service_name)
    if client is None:
        client = HttpPurgeClient(
            catalog_url=settings.catalog_internal_url,
            file_url=settings.file_internal_url,
            search_url=settings.search_internal_url,
            internal_token=settings.internal_token,
        )
    return PurgeService(client, batch_size=batch_size or settings.purge_batch_size)


async def run_purge_pass(client=None, batch_size: int | None = None) -> PurgeRunResult:
    service = create_service(client=client, batch_size=batch_size)
    return await service.run_once()


async def run_purge_loop(
    client=None,
    batch_size: int | None = None,
    *,
    interval_seconds: int | None = None,
    sleep=asyncio.sleep,
) -> PurgeRunResult:
    settings = get_settings()
    effective_interval = interval_seconds if interval_seconds is not None else settings.purge_interval_seconds
    latest_result = PurgeRunResult()

    logger.info(
        "purge worker loop started",
        event_name="purge_loop_started",
        event_category="purge",
        mode="loop",
        interval_seconds=effective_interval,
        status="started",
    )

    try:
        while True:
            latest_result = await run_purge_pass(client=client, batch_size=batch_size)
            await sleep(effective_interval)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info(
            "purge worker loop stopped",
            event_name="purge_loop_stopped",
            event_category="purge",
            mode="loop",
            interval_seconds=effective_interval,
            status="stopped",
        )
        return latest_result


async def run_worker(
    client=None,
    batch_size: int | None = None,
    *,
    sleep=asyncio.sleep,
) -> PurgeRunResult:
    settings = get_settings()
    if settings.purge_run_mode == "loop":
        return await run_purge_loop(
            client=client,
            batch_size=batch_size,
            interval_seconds=settings.purge_interval_seconds,
            sleep=sleep,
        )
    return await run_purge_pass(client=client, batch_size=batch_size)


def main() -> int:
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
