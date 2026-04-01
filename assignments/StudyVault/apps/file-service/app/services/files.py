from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import AuthenticatedUser, FileRecord, UploadActivityEvent

from app.repositories.object_store import ObjectStoreRepository
from app.services.downstream import DownstreamPublisher


logger = get_logger(__name__)


class FileService:
    def __init__(
        self,
        object_store: ObjectStoreRepository,
        downstream: DownstreamPublisher,
    ) -> None:
        self.object_store = object_store
        self.downstream = downstream

    async def upload_file(
        self,
        *,
        user: AuthenticatedUser,
        upload: UploadFile,
        tags: list[str],
    ) -> FileRecord:
        content = await upload.read()
        if not content:
            logger.warning(
                "file upload rejected: empty content",
                event_name="file_upload_failed",
                event_category="file",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                filename=upload.filename or "unnamed-file",
                mime_type=upload.content_type or "application/octet-stream",
                tags_count=len(tags),
                status="rejected",
                error="Uploaded file is empty",
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

        file_record = FileRecord.create(
            owner_id=user.subject,
            filename=upload.filename or "unnamed-file",
            mime_type=upload.content_type or "application/octet-stream",
            size=len(content),
            tags=tags,
        )
        logger.info(
            "file upload started",
            event_name="file_upload_started",
            event_category="file",
            file_id=file_record.file_id,
            owner_id=file_record.owner_id,
            owner_username=user.username,
            owner_email=user.email,
            filename=file_record.filename,
            mime_type=file_record.mime_type,
            size=file_record.size,
            tags_count=len(file_record.tags),
            status="started",
        )
        self.object_store.store(file_record, content)

        try:
            await self.downstream.publish_catalog(file_record, bearer_token=user.token or "")
            logger.info(
                "downstream sync succeeded",
                event_name="downstream_sync_succeeded",
                event_category="downstream",
                file_id=file_record.file_id,
                owner_id=file_record.owner_id,
                owner_username=user.username,
                owner_email=user.email,
                downstream_service="catalog-service",
                status="succeeded",
            )
            await self.downstream.publish_search(file_record, bearer_token=user.token or "")
            logger.info(
                "downstream sync succeeded",
                event_name="downstream_sync_succeeded",
                event_category="downstream",
                file_id=file_record.file_id,
                owner_id=file_record.owner_id,
                owner_username=user.username,
                owner_email=user.email,
                downstream_service="search-service",
                status="succeeded",
            )
            await self.downstream.publish_activity(
                UploadActivityEvent(file=file_record),
                bearer_token=user.token or "",
            )
            logger.info(
                "downstream sync succeeded",
                event_name="downstream_sync_succeeded",
                event_category="downstream",
                file_id=file_record.file_id,
                owner_id=file_record.owner_id,
                owner_username=user.username,
                owner_email=user.email,
                downstream_service="activity-service",
                status="succeeded",
            )
        except ServiceClientError as exc:
            logger.error(
                "downstream sync failed",
                event_name="downstream_sync_failed",
                event_category="downstream",
                file_id=file_record.file_id,
                owner_id=file_record.owner_id,
                owner_username=user.username,
                owner_email=user.email,
                filename=file_record.filename,
                downstream_service="unknown",
                status="failed",
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload stored, but downstream synchronization failed",
            ) from exc

        logger.info(
            "file upload succeeded",
            event_name="file_upload_succeeded",
            event_category="file",
            file_id=file_record.file_id,
            owner_id=file_record.owner_id,
            owner_username=user.username,
            owner_email=user.email,
            filename=file_record.filename,
            mime_type=file_record.mime_type,
            size=file_record.size,
            tags_count=len(file_record.tags),
            status="succeeded",
        )

        return file_record

    async def download_file(self, *, user: AuthenticatedUser, file_id: str) -> tuple[FileRecord, bytes]:
        file_record = await self.downstream.fetch_catalog_file(file_id, bearer_token=user.token or "")
        if file_record.owner_id != user.subject:
            logger.warning(
                "file download rejected: owner mismatch",
                event_name="file_download_failed",
                event_category="file",
                file_id=file_id,
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                status="forbidden",
                error="File owner mismatch",
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File owner mismatch")
        content = self.object_store.get(file_record.object_key)
        logger.info(
            "file download succeeded",
            event_name="file_download_succeeded",
            event_category="file",
            file_id=file_record.file_id,
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            filename=file_record.filename,
            mime_type=file_record.mime_type,
            size=file_record.size,
            status="succeeded",
        )
        return file_record, content
