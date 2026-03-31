from __future__ import annotations

from fastapi import HTTPException, status

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.repositories.catalog import CatalogRepository


logger = get_logger(__name__)


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def create_file(self, file_record: FileRecord) -> FileRecord:
        created = self.repository.create_file(file_record)
        logger.info(
            "catalog file created",
            event_name="catalog_file_created",
            event_category="catalog",
            file_id=file_record.file_id,
            owner_id=file_record.owner_id,
            filename=file_record.filename,
            mime_type=file_record.mime_type,
            size=file_record.size,
            tags_count=len(file_record.tags),
            status="succeeded",
        )
        return created

    def list_user_files(self, user: AuthenticatedUser) -> list[FileRecord]:
        records = self.repository.list_files(user.subject)
        logger.info(
            "catalog list requested",
            event_name="catalog_list_requested",
            event_category="catalog",
            owner_id=user.subject,
            result_count=len(records),
            status="succeeded",
        )
        return records

    def get_user_file(self, user: AuthenticatedUser, file_id: str) -> FileRecord:
        record = self.repository.get_file(user.subject, file_id)
        if record is None:
            logger.warning(
                "catalog file lookup failed",
                event_name="catalog_file_lookup_failed",
                event_category="catalog",
                owner_id=user.subject,
                file_id=file_id,
                status="not_found",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        logger.info(
            "catalog file fetched",
            event_name="catalog_file_fetched",
            event_category="catalog",
            owner_id=user.subject,
            file_id=file_id,
            filename=record.filename,
            status="succeeded",
        )
        return record
