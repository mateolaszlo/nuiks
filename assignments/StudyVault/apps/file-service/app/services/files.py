from __future__ import annotations

from tempfile import TemporaryFile

from fastapi import HTTPException, UploadFile, status

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    MAX_FILENAME_LENGTH,
    MAX_TAG_COUNT,
    MAX_TAG_LENGTH,
    AuthenticatedUser,
    FileRecord,
    UploadActivityEvent,
    has_control_chars,
)

from app.repositories.object_store import ObjectStoreRepository
from app.services.downstream import DownstreamPublisher


logger = get_logger(__name__)
UPLOAD_CHUNK_SIZE = 1024 * 1024


class FileService:
    def __init__(
        self,
        object_store: ObjectStoreRepository,
        downstream: DownstreamPublisher,
        *,
        max_upload_bytes: int,
    ) -> None:
        self.object_store = object_store
        self.downstream = downstream
        self.max_upload_bytes = max_upload_bytes

    @staticmethod
    def _validate_upload_metadata(*, filename: str, tags: list[str]) -> list[str]:
        if not filename.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename must not be empty")
        if len(filename) > MAX_FILENAME_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Filename must be at most {MAX_FILENAME_LENGTH} characters",
            )
        if has_control_chars(filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename must not contain control characters",
            )
        if "/" in filename or "\\" in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename must not contain path separators",
            )
        if len(tags) > MAX_TAG_COUNT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tags must contain at most {MAX_TAG_COUNT} items",
            )

        normalized_tags: list[str] = []
        for tag in tags:
            normalized_tag = tag.strip()
            if not normalized_tag:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tags must not be empty")
            if len(normalized_tag) > MAX_TAG_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tags must be at most {MAX_TAG_LENGTH} characters",
                )
            if has_control_chars(normalized_tag):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tags must not contain control characters",
                )
            normalized_tags.append(normalized_tag)
        return normalized_tags

    async def upload_file(
        self,
        *,
        user: AuthenticatedUser,
        upload: UploadFile,
        tags: list[str],
    ) -> FileRecord:
        filename = upload.filename or "unnamed-file"
        normalized_tags = self._validate_upload_metadata(filename=filename, tags=tags)
        try:
            with TemporaryFile() as buffered_upload:
                total_size = 0
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > self.max_upload_bytes:
                        logger.warning(
                            "file upload rejected: size limit exceeded",
                            event_name="file_upload_failed",
                            event_category="file",
                            owner_id=user.subject,
                            owner_username=user.username,
                            owner_email=user.email,
                            filename=filename,
                            mime_type=upload.content_type or "application/octet-stream",
                            tags_count=len(normalized_tags),
                            status="rejected",
                            error="Uploaded file exceeds the maximum allowed size",
                            max_upload_bytes=self.max_upload_bytes,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="Uploaded file exceeds the maximum allowed size",
                        )
                    buffered_upload.write(chunk)

                if total_size == 0:
                    logger.warning(
                        "file upload rejected: empty content",
                        event_name="file_upload_failed",
                        event_category="file",
                        owner_id=user.subject,
                        owner_username=user.username,
                        owner_email=user.email,
                        filename=filename,
                        mime_type=upload.content_type or "application/octet-stream",
                        tags_count=len(normalized_tags),
                        status="rejected",
                        error="Uploaded file is empty",
                    )
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

                buffered_upload.seek(0)
                file_record = FileRecord.create(
                    owner_id=user.subject,
                    filename=filename,
                    mime_type=upload.content_type or "application/octet-stream",
                    size=total_size,
                    tags=normalized_tags,
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
                self.object_store.store(file_record, buffered_upload, total_size)
        finally:
            await upload.close()

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
