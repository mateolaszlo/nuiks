from __future__ import annotations

from fastapi import HTTPException, status

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import AuthenticatedUser, BreadcrumbEntry, FileRecord

from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import CatalogBreadcrumbsResponse, CatalogItemsResponse


logger = get_logger(__name__)


class CatalogService:
    ROOT_BREADCRUMB_NAME = "My Drive"

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
            owner_username=user.username,
            owner_email=user.email,
            result_count=len(records),
            status="succeeded",
        )
        return records

    def list_items(
        self,
        user: AuthenticatedUser,
        *,
        parent_folder_id: str | None,
        include_trashed: bool,
    ) -> CatalogItemsResponse:
        if include_trashed:
            items = self.repository.list_trashed_items(user.subject)
            response_parent_id = None
            event_name = "catalog_trash_list_requested"
        else:
            if parent_folder_id is not None:
                folder = self.repository.get_folder(user.subject, parent_folder_id)
                if folder is None:
                    logger.warning(
                        "catalog folder lookup failed",
                        event_name="catalog_folder_lookup_failed",
                        event_category="catalog",
                        owner_id=user.subject,
                        owner_username=user.username,
                        owner_email=user.email,
                        folder_id=parent_folder_id,
                        status="not_found",
                    )
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
            items = self.repository.list_items(user.subject, parent_folder_id)
            response_parent_id = parent_folder_id
            event_name = "catalog_items_list_requested"

        logger.info(
            "catalog items listed",
            event_name=event_name,
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            parent_folder_id=response_parent_id,
            include_trashed=include_trashed,
            result_count=len(items),
            status="succeeded",
        )
        return CatalogItemsResponse(parent_folder_id=response_parent_id, items=items)

    def get_breadcrumbs(self, user: AuthenticatedUser, folder_id: str) -> CatalogBreadcrumbsResponse:
        folder = self.repository.get_folder(user.subject, folder_id)
        if folder is None:
            logger.warning(
                "catalog folder lookup failed",
                event_name="catalog_folder_lookup_failed",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                status="not_found",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

        ancestors = self.repository.get_folder_ancestors(user.subject, folder_id)
        breadcrumbs = [BreadcrumbEntry(name=self.ROOT_BREADCRUMB_NAME)]
        breadcrumbs.extend(
            BreadcrumbEntry(folder_id=ancestor.folder_id, name=ancestor.name) for ancestor in ancestors
        )
        breadcrumbs.append(BreadcrumbEntry(folder_id=folder.folder_id, name=folder.name))

        logger.info(
            "catalog breadcrumbs fetched",
            event_name="catalog_breadcrumbs_fetched",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=folder_id,
            breadcrumb_count=len(breadcrumbs),
            status="succeeded",
        )
        return CatalogBreadcrumbsResponse(breadcrumbs=breadcrumbs)

    def get_user_file(self, user: AuthenticatedUser, file_id: str) -> FileRecord:
        record = self.repository.get_file(user.subject, file_id)
        if record is None:
            logger.warning(
                "catalog file lookup failed",
                event_name="catalog_file_lookup_failed",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                file_id=file_id,
                status="not_found",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        logger.info(
            "catalog file fetched",
            event_name="catalog_file_fetched",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            file_id=file_id,
            filename=record.filename,
            status="succeeded",
        )
        return record
