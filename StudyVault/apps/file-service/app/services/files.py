from __future__ import annotations

from tempfile import TemporaryFile

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from studyvault_backend_common.errors import api_error
from studyvault_backend_common.http import ServiceClientError
from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    MAX_FILENAME_LENGTH,
    MAX_TAG_COUNT,
    MAX_TAG_LENGTH,
    AuthenticatedUser,
    FileRecord,
    FileRestoreResponse,
    FolderRecord,
    ItemActivityEvent,
    MoveItemRequest,
    RenameItemRequest,
    RestoreItemRequest,
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
        status_code = exc.status_code
        message = str(exc)
        if status_code is None and "status 404" in message:
            status_code = status.HTTP_404_NOT_FOUND
        if status_code is None and "status 422" in message:
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        if status_code == status.HTTP_404_NOT_FOUND:
            return api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.detail or "Folder not found",
                code=exc.code or "folder_not_found",
                category="not_found",
                context=exc.context,
            )
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            return api_error(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=exc.detail or "Cannot upload file into trashed folder",
                code=exc.code or "cannot_upload_into_trashed_folder",
                category="validation",
                context=exc.context,
            )
        return api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Folder lookup failed",
            code="folder_lookup_failed",
            category="unavailable",
            recoverable=False,
            context=exc.context,
        )

    @staticmethod
    def _map_catalog_file_error(exc: ServiceClientError) -> HTTPException:
        status_code = exc.status_code
        message = str(exc)
        if status_code is None and "status 404" in message:
            status_code = status.HTTP_404_NOT_FOUND
        if status_code is None and "status 422" in message:
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        if status_code is None and "status 409" in message:
            status_code = status.HTTP_409_CONFLICT
        if status_code == status.HTTP_404_NOT_FOUND:
            return api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.detail or "File not found",
                code=exc.code or "file_not_found",
                category="not_found",
                context=exc.context,
            )
        if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            return api_error(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=exc.detail or "File move request was invalid",
                code=exc.code or "invalid_move_request",
                category="validation",
                context=exc.context,
            )
        if status_code == status.HTTP_409_CONFLICT:
            return api_error(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail or "File operation conflict",
                code=exc.code or "conflict",
                category="conflict",
                context=exc.context,
            )
        return api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File metadata update failed",
            code="file_metadata_update_failed",
            category="unavailable",
            recoverable=False,
            context=exc.context,
        )

    @staticmethod
    def _map_catalog_file_hard_delete_error(exc: ServiceClientError) -> HTTPException:
        status_code = exc.status_code
        message = str(exc)
        if status_code is None and "status 404" in message:
            status_code = status.HTTP_404_NOT_FOUND
        if status_code is None and "status 409" in message:
            status_code = status.HTTP_409_CONFLICT
        if status_code == status.HTTP_404_NOT_FOUND:
            return api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.detail or "File not found",
                code=exc.code or "file_not_found",
                category="not_found",
                context=exc.context,
            )
        if status_code == status.HTTP_409_CONFLICT:
            return api_error(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail or "File is not trashed",
                code=exc.code or "file_not_trashed",
                category="conflict",
                context=exc.context,
            )
        return api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File hard delete failed",
            code="file_hard_delete_failed",
            category="unavailable",
            recoverable=False,
            context=exc.context,
        )

    @staticmethod
    def _map_search_delete_error(exc: ServiceClientError) -> HTTPException:
        status_code = exc.status_code
        message = str(exc)
        if status_code is None and "status 404" in message:
            status_code = status.HTTP_404_NOT_FOUND
        if status_code == status.HTTP_404_NOT_FOUND:
            return HTTPException(status_code=status.HTTP_204_NO_CONTENT)
        return api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Search delete failed",
            code="search_delete_failed",
            category="unavailable",
            recoverable=False,
            context=exc.context,
        )

    @staticmethod
    def _map_catalog_file_restore_error(exc: ServiceClientError) -> HTTPException:
        status_code = exc.status_code
        message = str(exc)
        if status_code is None and "status 404" in message:
            status_code = status.HTTP_404_NOT_FOUND
        if status_code is None and "status 409" in message:
            status_code = status.HTTP_409_CONFLICT
        if status_code == status.HTTP_404_NOT_FOUND:
            return api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.detail or "Folder not found",
                code=exc.code or "folder_not_found",
                category="not_found",
                context=exc.context,
            )
        if status_code == status.HTTP_409_CONFLICT:
            return api_error(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail or "File restore conflict",
                code=exc.code or "file_restore_conflict",
                category="conflict",
                context=exc.context,
            )
        return api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File metadata update failed",
            code="file_metadata_update_failed",
            category="unavailable",
            recoverable=False,
            context=exc.context,
        )

    @staticmethod
    def _log_downstream_sync_failure(
        *,
        user: AuthenticatedUser,
        file_record: FileRecord,
        downstream_service: str,
        operation: str,
        exc: ServiceClientError,
    ) -> None:
        logger.error(
            "downstream sync failed",
            event_name="downstream_sync_failed",
            event_category="downstream",
            file_id=file_record.file_id,
            owner_id=file_record.owner_id,
            owner_username=user.username,
            owner_email=user.email,
            filename=file_record.filename,
            downstream_service=downstream_service,
            operation=operation,
            status="failed",
            error=str(exc),
        )

    @staticmethod
    def _validate_upload_metadata(*, filename: str, tags: list[str]) -> list[str]:
        if not filename.strip():
            raise api_error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename must not be empty",
                code="invalid_upload_filename",
                category="validation",
            )
        if len(filename) > MAX_FILENAME_LENGTH:
            raise api_error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Filename must be at most {MAX_FILENAME_LENGTH} characters",
                code="invalid_upload_filename",
                category="validation",
            )
        if has_control_chars(filename):
            raise api_error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename must not contain control characters",
                code="invalid_upload_filename",
                category="validation",
            )
        if "/" in filename or "\\" in filename:
            raise api_error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename must not contain path separators",
                code="invalid_upload_filename",
                category="validation",
            )
        if len(tags) > MAX_TAG_COUNT:
            raise api_error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tags must contain at most {MAX_TAG_COUNT} items",
                code="invalid_upload_tags",
                category="validation",
            )

        normalized_tags: list[str] = []
        for tag in tags:
            normalized_tag = tag.strip()
            if not normalized_tag:
                raise api_error(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tags must not be empty",
                    code="invalid_upload_tags",
                    category="validation",
                )
            if len(normalized_tag) > MAX_TAG_LENGTH:
                raise api_error(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tags must be at most {MAX_TAG_LENGTH} characters",
                    code="invalid_upload_tags",
                    category="validation",
                )
            if has_control_chars(normalized_tag):
                raise api_error(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tags must not contain control characters",
                    code="invalid_upload_tags",
                    category="validation",
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
                raise api_error(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Cannot upload file into trashed folder",
                    code="cannot_upload_into_trashed_folder",
                    category="validation",
                    context={"target_parent_id": parent_folder_id},
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
                        raise api_error(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="Uploaded file exceeds the maximum allowed size",
                            code="upload_size_exceeded",
                            category="validation",
                            context={"max_upload_bytes": self.max_upload_bytes},
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
                    raise api_error(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Uploaded file is empty",
                        code="upload_empty_file",
                        category="validation",
                    )

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
                try:
                    await run_in_threadpool(self.object_store.store, file_record, buffered_upload, total_size)
                except ObjectStoreUnavailableError as exc:
                    logger.error(
                        "file upload failed: object store unavailable",
                        event_name="file_upload_failed",
                        event_category="file",
                        owner_id=user.subject,
                        owner_username=user.username,
                        owner_email=user.email,
                        filename=file_record.filename,
                        mime_type=file_record.mime_type,
                        size=file_record.size,
                        tags_count=len(file_record.tags),
                        parent_folder_id=file_record.parent_folder_id,
                        status="failed",
                        error="File storage unavailable",
                    )
                    raise api_error(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="File storage unavailable",
                        code="storage_unavailable",
                        category="unavailable",
                        recoverable=False,
                    ) from exc
        finally:
            await upload.close()

        try:
            await self.downstream.publish_catalog(file_record, bearer_token=user.token or "")
        except ServiceClientError as exc:
            self._log_downstream_sync_failure(
                user=user,
                file_record=file_record,
                downstream_service="catalog-service",
                operation="publish_catalog",
                exc=exc,
            )
            raise api_error(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload stored, but downstream synchronization failed",
                code="downstream_sync_failed",
                category="unavailable",
                recoverable=False,
            ) from exc

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

        try:
            await self.downstream.publish_search(file_record, bearer_token=user.token or "")
        except ServiceClientError as exc:
            self._log_downstream_sync_failure(
                user=user,
                file_record=file_record,
                downstream_service="search-service",
                operation="publish_search",
                exc=exc,
            )
        else:
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

        try:
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(file_record, action="file_uploaded"),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            self._log_downstream_sync_failure(
                user=user,
                file_record=file_record,
                downstream_service="activity-service",
                operation="publish_activity",
                exc=exc,
            )
        else:
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
            file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        if file_record.trashed_at is not None:
            raise api_error(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot rename trashed file",
                code="cannot_rename_trashed_file",
                category="conflict",
                context={"file_id": file_id},
            )

        if request.name.casefold() == file_record.filename.casefold():
            return file_record

        updated_record = file_record.model_copy(
            update={
                "filename": request.name,
                "updated_at": utcnow(),
            }
        )

        try:
            old_name = file_record.filename
            updated_record = await self.downstream.update_catalog_file(
                updated_record,
                bearer_token=user.token or "",
            )
            await self.downstream.publish_search(updated_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(
                    updated_record,
                    action="item_renamed",
                    old_name=old_name,
                    new_name=updated_record.filename,
                ),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        return updated_record

    async def move_file(
        self,
        *,
        user: AuthenticatedUser,
        file_id: str,
        request: MoveItemRequest,
    ) -> FileRecord:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        if file_record.trashed_at is not None:
            raise api_error(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot move trashed file",
                code="cannot_move_trashed_file",
                category="conflict",
                context={"file_id": file_id},
            )

        target_folder: FolderRecord | None = None
        if request.parent_folder_id is not None:
            try:
                target_folder = await self.downstream.fetch_catalog_folder(
                    request.parent_folder_id,
                    bearer_token=user.token or "",
                )
            except ServiceClientError as exc:
                raise self._map_catalog_folder_lookup_error(exc) from exc
            if target_folder.trashed_at is not None:
                raise api_error(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Cannot move file into trashed folder",
                    code="cannot_move_into_trashed_folder",
                    category="validation",
                    context={"file_id": file_id, "target_parent_id": request.parent_folder_id},
                )

        if file_record.parent_folder_id == request.parent_folder_id:
            return file_record

        try:
            moved_record = await self.downstream.move_catalog_file(
                file_record,
                request,
                bearer_token=user.token or "",
            )
            await self.downstream.publish_search(moved_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(moved_record, action="item_moved"),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        return moved_record

    async def trash_file(
        self,
        *,
        user: AuthenticatedUser,
        file_id: str,
    ) -> None:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        if file_record.trashed_at is not None:
            return

        try:
            trashed_record = await self.downstream.trash_catalog_file(
                file_id,
                user.subject,
                bearer_token=user.token or "",
            )
            await self.downstream.publish_search(trashed_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(trashed_record, action="item_trashed"),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

    async def restore_file(
        self,
        *,
        user: AuthenticatedUser,
        file_id: str,
        request: RestoreItemRequest,
    ) -> FileRestoreResponse:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_error(exc) from exc

        if file_record.trashed_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File is not trashed")

        try:
            restore_result = await self.downstream.restore_catalog_file(
                file_id,
                user.subject,
                request,
                bearer_token=user.token or "",
            )
            restored_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
            await self.downstream.publish_search(restored_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(restored_record, action="item_restored"),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            raise self._map_catalog_file_restore_error(exc) from exc

        return restore_result

    async def hard_delete_user_file(self, *, user: AuthenticatedUser, file_id: str) -> None:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
        except ServiceClientError as exc:
            raise self._map_catalog_file_hard_delete_error(exc) from exc

        if file_record.trashed_at is None or file_record.purge_after is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File is not trashed")

        await self.hard_delete_file(owner_id=user.subject, file_id=file_id)

        try:
            await self.downstream.publish_activity(
                ItemActivityEvent.from_file(file_record, action="item_hard_deleted"),
                bearer_token=user.token or "",
            )
        except ServiceClientError:
            logger.error(
                "file hard delete activity publish failed after persistence",
                event_name="file_hard_delete_activity_publish_failed",
                event_category="file",
                file_id=file_record.file_id,
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                filename=file_record.filename,
                status="failed",
            )

    async def download_file(self, *, user: AuthenticatedUser, file_id: str) -> tuple[FileRecord, bytes]:
        file_record = await self.downstream.fetch_catalog_file(file_id, user.subject, bearer_token=user.token or "")
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

    async def hard_delete_file(self, *, owner_id: str, file_id: str) -> None:
        try:
            file_record = await self.downstream.fetch_catalog_file(file_id, owner_id, bearer_token="")
        except ServiceClientError as exc:
            raise self._map_catalog_file_hard_delete_error(exc) from exc

        if file_record.trashed_at is None or file_record.purge_after is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File is not trashed")

        try:
            await run_in_threadpool(self.object_store.delete, file_record.object_key)
        except ObjectStoreNotFoundError:
            pass
        except ObjectStoreUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="File storage unavailable",
            ) from exc

        try:
            await self.downstream.hard_delete_catalog_file(file_id, owner_id, bearer_token="")
        except ServiceClientError as exc:
            raise self._map_catalog_file_hard_delete_error(exc) from exc

        try:
            await self.downstream.delete_search_item(file_id, bearer_token="")
        except ServiceClientError as exc:
            if "status 404" in str(exc):
                return
            raise self._map_search_delete_error(exc) from exc
