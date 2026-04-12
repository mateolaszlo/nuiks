from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from studyvault_backend_common.http import JsonServiceClient, ServiceClientError
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import FileRecord, FolderRecord, utcnow


logger = get_logger(__name__)


@dataclass
class ExpiredTrashBatch:
    files: list[FileRecord]
    folders: list[FolderRecord]


@dataclass
class PurgeRunResult:
    batches_processed: int = 0
    deleted_files: int = 0
    failed_files: int = 0
    ignored_folders: int = 0


class PurgeClient(Protocol):
    async def list_expired_trash(self, *, before: datetime, limit: int) -> ExpiredTrashBatch: ...

    async def hard_delete_file(self, *, owner_id: str, file_id: str) -> None: ...


class HttpPurgeClient:
    def __init__(
        self,
        *,
        catalog_url: str,
        file_url: str,
        internal_token: str,
        client: JsonServiceClient | None = None,
    ) -> None:
        self.catalog_url = catalog_url.rstrip("/")
        self.file_url = file_url.rstrip("/")
        self.internal_token = internal_token
        self.client = client or JsonServiceClient()

    async def list_expired_trash(self, *, before: datetime, limit: int) -> ExpiredTrashBatch:
        payload = await self.client.get_json(
            f"{self.catalog_url}/internal/catalog/trash/expired?before={before.isoformat()}&limit={limit}",
            internal_token=self.internal_token,
        )
        return ExpiredTrashBatch(
            files=[FileRecord(**record) for record in payload.get("files", [])],
            folders=[FolderRecord(**record) for record in payload.get("folders", [])],
        )

    async def hard_delete_file(self, *, owner_id: str, file_id: str) -> None:
        await self.client.delete_json(
            f"{self.file_url}/internal/files/{file_id}/hard-delete",
            internal_token=self.internal_token,
            query_params={"owner_id": owner_id},
        )


class PurgeService:
    def __init__(self, client: PurgeClient, *, batch_size: int) -> None:
        self.client = client
        self.batch_size = batch_size

    async def run_once(self, *, before: datetime | None = None) -> PurgeRunResult:
        effective_before = before or utcnow()
        result = PurgeRunResult()

        while True:
            batch = await self.client.list_expired_trash(before=effective_before, limit=self.batch_size)
            if not batch.files:
                if batch.folders:
                    result.ignored_folders += len(batch.folders)
                    logger.info(
                        "purge batch ignored expired folders",
                        event_name="purge_batch_ignored_folders",
                        event_category="purge",
                        ignored_folder_count=len(batch.folders),
                        status="skipped",
                    )
                break

            result.batches_processed += 1
            result.ignored_folders += len(batch.folders)
            logger.info(
                "purge batch started",
                event_name="purge_batch_started",
                event_category="purge",
                batch_number=result.batches_processed,
                expired_file_count=len(batch.files),
                ignored_folder_count=len(batch.folders),
                status="started",
            )

            for file_record in batch.files:
                try:
                    await self.client.hard_delete_file(owner_id=file_record.owner_id, file_id=file_record.file_id)
                except ServiceClientError as exc:
                    result.failed_files += 1
                    logger.error(
                        "purge file failed",
                        event_name="purge_file_failed",
                        event_category="purge",
                        file_id=file_record.file_id,
                        owner_id=file_record.owner_id,
                        status="failed",
                        error=str(exc),
                    )
                    continue

                result.deleted_files += 1
                logger.info(
                    "purge file deleted",
                    event_name="purge_file_deleted",
                    event_category="purge",
                    file_id=file_record.file_id,
                    owner_id=file_record.owner_id,
                    status="succeeded",
                )

        logger.info(
            "purge run finished",
            event_name="purge_run_finished",
            event_category="purge",
            batches_processed=result.batches_processed,
            deleted_files=result.deleted_files,
            failed_files=result.failed_files,
            ignored_folders=result.ignored_folders,
            status="succeeded",
        )
        return result
