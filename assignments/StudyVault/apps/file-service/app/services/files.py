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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

        file_record = FileRecord.create(
            owner_id=user.subject,
            filename=upload.filename or "unnamed-file",
            mime_type=upload.content_type or "application/octet-stream",
            size=len(content),
            tags=tags,
        )
        self.object_store.store(file_record, content)

        try:
            await self.downstream.publish_catalog(file_record, bearer_token=user.token or "")
            await self.downstream.publish_search(file_record, bearer_token=user.token or "")
            await self.downstream.publish_activity(
                UploadActivityEvent(file=file_record),
                bearer_token=user.token or "",
            )
        except ServiceClientError as exc:
            logger.error("downstream_sync_failed", file_id=file_record.file_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload stored, but downstream synchronization failed",
            ) from exc

        return file_record

    async def download_file(self, *, user: AuthenticatedUser, file_id: str) -> tuple[FileRecord, bytes]:
        file_record = await self.downstream.fetch_catalog_file(file_id, bearer_token=user.token or "")
        if file_record.owner_id != user.subject:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File owner mismatch")
        content = self.object_store.get(file_record.object_key)
        return file_record, content
