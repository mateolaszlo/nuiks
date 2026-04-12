from __future__ import annotations

import asyncio

from studyvault_backend_common.logging import configure_logging

from app.core.config import get_settings
from app.services.purge import HttpPurgeClient, PurgeService, PurgeRunResult


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


def main() -> int:
    asyncio.run(run_purge_pass())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
