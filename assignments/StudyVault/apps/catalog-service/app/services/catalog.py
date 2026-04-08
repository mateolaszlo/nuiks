from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    AuthenticatedUser,
    BreadcrumbEntry,
    CreateFolderRequest,
    FileRecord,
    FolderRecord,
)

from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    CatalogBreadcrumbsResponse,
    CatalogExpiredTrashResponse,
    CatalogItemsResponse,
    CatalogTrashResponse,
)


logger = get_logger(__name__)


class CatalogService:
    ROOT_BREADCRUMB_NAME = "My Drive"

    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def create_folder(self, user: AuthenticatedUser, request: CreateFolderRequest) -> FolderRecord:
        parent: FolderRecord | None = None
        if request.parent_folder_id is not None:
            parent = self.repository.get_folder(user.subject, request.parent_folder_id)
            if parent is None:
                logger.warning(
                    "catalog parent folder lookup failed",
                    event_name="catalog_parent_folder_lookup_failed",
                    event_category="catalog",
                    owner_id=user.subject,
                    owner_username=user.username,
                    owner_email=user.email,
                    parent_folder_id=request.parent_folder_id,
                    status="not_found",
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
            if parent.trashed_at is not None:
                logger.warning(
                    "catalog parent folder invalid",
                    event_name="catalog_parent_folder_invalid",
                    event_category="catalog",
                    owner_id=user.subject,
                    owner_username=user.username,
                    owner_email=user.email,
                    parent_folder_id=request.parent_folder_id,
                    status="trashed",
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Cannot create folder inside trashed folder",
                )

        normalized_name = request.name.casefold()
        siblings = self.repository.list_child_folders(user.subject, request.parent_folder_id)
        if any((folder.normalized_name or folder.name.casefold()) == normalized_name for folder in siblings):
            logger.warning(
                "catalog folder create conflict",
                event_name="catalog_folder_create_conflict",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                parent_folder_id=request.parent_folder_id,
                folder_name=request.name,
                status="conflict",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            )

        folder_record = FolderRecord.create(
            owner_id=user.subject,
            name=request.name,
            parent_folder_id=request.parent_folder_id,
            path_depth=0 if parent is None else parent.path_depth + 1,
        )
        try:
            created = self.repository.create_folder(folder_record)
        except IntegrityError as exc:
            logger.warning(
                "catalog folder create conflict",
                event_name="catalog_folder_create_conflict",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                parent_folder_id=request.parent_folder_id,
                folder_name=request.name,
                status="conflict",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            ) from exc

        logger.info(
            "catalog folder created",
            event_name="catalog_folder_created",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=created.folder_id,
            parent_folder_id=created.parent_folder_id,
            folder_name=created.name,
            path_depth=created.path_depth,
            status="succeeded",
        )
        return created

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

    def list_trash(self, user: AuthenticatedUser) -> CatalogTrashResponse:
        items = self.repository.list_trashed_items(user.subject)
        logger.info(
            "catalog trash listed",
            event_name="catalog_trash_list_requested",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            result_count=len(items),
            status="succeeded",
        )
        return CatalogTrashResponse(items=items)

    def list_expired_trash(self, *, before: datetime, limit: int) -> CatalogExpiredTrashResponse:
        files = self.repository.list_expired_trashed_files(before)[:limit]
        folders = self.repository.list_expired_trashed_folders(before)[:limit]
        logger.info(
            "catalog expired trash listed",
            event_name="catalog_expired_trash_list_requested",
            event_category="catalog",
            before=before.isoformat(),
            limit=limit,
            expired_file_count=len(files),
            expired_folder_count=len(folders),
            status="succeeded",
        )
        return CatalogExpiredTrashResponse(files=files, folders=folders)

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
