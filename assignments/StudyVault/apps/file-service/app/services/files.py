from __future__ import annotations

from tempfile import TemporaryFile

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    MAX_FILENAME_LENGTH,
    MAX_TAG_COUNT,
    MAX_TAG_LENGTH,
    AuthenticatedUser,
    FileActivityEvent,
    FileRecord,
    FolderRecord,
    RenameItemRequest,
    has_control_chars,
    utcnow,
)

from app.repositories.object_store import ObjectStoreRepository
from app.repositories.object_store import ObjectStoreNotFoundError, ObjectStoreUnavailableError
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
    def _map_catalog_folder_lookup_error(exc: ServiceClientError) -> HTTPException:
        message = str(exc)
        if "status 404" in message:
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
        if "status 422" in message:
            return HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot upload file into trashed folder",
            )
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Folder lookup failed",
        )

    @staticmethod
    def _map_catalog_file_error(exc: ServiceClientError) -> HTTPException:
        message = str(exc)
        if "status 404" in message:
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        if "status 409" in message:
            if "trashed" in message.lower():
                return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot rename trashed file")
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File rename conflict")
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File metadata update failed",
        )

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
        parent_folder_id: str | None,
    ) -> FileRecord:
        filename = upload.filename or "unnamed-file"
        normalized_tags = self._validate_upload_metadata(filename=filename, tags=tags)
        parent_folder: FolderRecord | None = None
        if parent_folder_id is not None:
            try:
                parent_folder = await self.downstream.fetch_catalog_folder(
                    parent_folder_id,
                    bearer_token=user.token or "",
                )
            except ServiceClientError as exc:
                logger.warning(
                    "file upload rejected: parent folder lookup failed",
                    event_name="file_upload_failed",
                    event_category="file",
                    owner_id=user.subject,
                    owner_username=user.username,
                    owner_email=user.email,
                    filename=filename,
                    parent_folder_id=parent_folder_id,
                    status="rejected",
                    error=str(exc),
                )
                raise self._map_catalog_folder_lookup_error(exc) from exc

            if parent_folder.trashed_at is not None:
                logger.warning(
                    "file upload rejected: parent folder trashed",
                    event_name="file_upload_failed",
                    event_category="file",
                    owner_id=user.subject,
                    owner_username=user.username,
                    owner_email=user.email,
                    filename=filename,
                    parent_folder_id=parent_folder_id,
                    status="rejected",
                    error="Cannot upload file into trashed folder",
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Cannot upload file into trashed folder",
                )
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
                file_record.parent_folder_id = parent_folder.folder_id if parent_folder is not None else None
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
                    parent_folder_id=file_record.parent_folder_id,
                    status="started",
                )
                await run_in_threadpool(self.object_store.store, file_record, buffered_upload, total_size)
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
                FileActivityEvent(file=file_record),
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
            parent_folder_id=file_record.parent_folder_id,
            status="succeeded",
        )

        return file_record

    async def rename_file(
        self,
        *,
        user: AuthenticatedUser,
        file_id: str,
        request: RenameItemRequest,
    ) -> FileRecord:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        if file_record.trashed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot rename trashed file")

        if request.name.casefold() == file_record.filename.casefold():
            return file_record

        updated_record = file_record.model_copy(
            update={
                "filename": request.name,
                "updated_at": utcnow(),
            }
        )

        try:
            updated_record = await self.downstream.update_catalog_file(
                updated_record,
                bearer_token=user.token or "",
            )
            await self.downstream.publish_search(updated_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                FileActivityEvent(action="file_renamed", file=updated_record),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        return updated_record

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
        try:
            content = await run_in_threadpool(self.object_store.get, file_record.object_key)
        except ObjectStoreNotFoundError as exc:
            logger.warning(
                "file download failed: object missing",
                event_name="file_download_failed",
                event_category="file",
                file_id=file_id,
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                status="not_found",
                error="File content missing",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc
        except ObjectStoreUnavailableError as exc:
            logger.error(
                "file download failed: object store unavailable",
                event_name="file_download_failed",
                event_category="file",
                file_id=file_id,
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                status="failed",
                error="File storage unavailable",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="File storage unavailable",
            ) from exc
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
