from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import (
    AuthenticatedUser,
    BreadcrumbEntry,
    CreateFolderRequest,
    FileRecord,
    FolderRecord,
    MoveItemRequest,
    RenameItemRequest,
    RestoreItemRequest,
    utcnow,
)

from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    CatalogBreadcrumbsResponse,
    CatalogExpiredTrashResponse,
    CatalogItemsResponse,
    CatalogRestoreResponse,
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

    def rename_folder(self, user: AuthenticatedUser, folder_id: str, request: RenameItemRequest) -> FolderRecord:
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
        if folder.trashed_at is not None:
            logger.warning(
                "catalog folder rename rejected",
                event_name="catalog_folder_rename_rejected",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                status="trashed",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot rename trashed folder",
            )

        normalized_name = request.name.casefold()
        current_normalized_name = folder.normalized_name or folder.name.casefold()
        if normalized_name == current_normalized_name:
            logger.info(
                "catalog folder rename skipped",
                event_name="catalog_folder_rename_skipped",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                folder_name=folder.name,
                status="unchanged",
            )
            return folder

        siblings = self.repository.list_child_folders(user.subject, folder.parent_folder_id)
        if any(
            sibling.folder_id != folder_id
            and (sibling.normalized_name or sibling.name.casefold()) == normalized_name
            for sibling in siblings
        ):
            logger.warning(
                "catalog folder rename conflict",
                event_name="catalog_folder_rename_conflict",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                parent_folder_id=folder.parent_folder_id,
                folder_name=request.name,
                status="conflict",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            )

        renamed_folder = folder.model_copy(
            update={
                "name": request.name,
                "normalized_name": normalized_name,
                "updated_at": utcnow(),
            }
        )
        try:
            updated = self.repository.rename_folder(renamed_folder)
        except IntegrityError as exc:
            logger.warning(
                "catalog folder rename conflict",
                event_name="catalog_folder_rename_conflict",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                parent_folder_id=folder.parent_folder_id,
                folder_name=request.name,
                status="conflict",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            ) from exc

        logger.info(
            "catalog folder renamed",
            event_name="catalog_folder_renamed",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=updated.folder_id,
            parent_folder_id=updated.parent_folder_id,
            folder_name=updated.name,
            status="succeeded",
        )
        return updated

    def trash_folder(self, user: AuthenticatedUser, folder_id: str) -> None:
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
        if folder.trashed_at is not None:
            logger.info(
                "catalog folder trash skipped",
                event_name="catalog_folder_trash_skipped",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                status="already_trashed",
            )
            return

        trashed_at = utcnow()
        purge_after = trashed_at + timedelta(days=30)
        updated_at = trashed_at

        folder_updates: list[FolderRecord] = []
        file_updates: list[FileRecord] = []
        queue = [folder]

        while queue:
            current = queue.pop(0)
            is_root = current.folder_id == folder.folder_id
            folder_updates.append(
                current.model_copy(
                    update={
                        "updated_at": updated_at,
                        "trashed_at": trashed_at,
                        "purge_after": purge_after,
                        "original_parent_folder_id": (
                            current.original_parent_folder_id or current.parent_folder_id
                        ),
                        "deleted_by_cascade": False if is_root else True,
                    }
                )
            )

            child_folders = self.repository.list_child_folders(user.subject, current.folder_id)
            queue.extend(child_folders)
            for child_file in self.repository.list_child_files(user.subject, current.folder_id):
                file_updates.append(
                    child_file.model_copy(
                        update={
                            "updated_at": updated_at,
                            "trashed_at": trashed_at,
                            "purge_after": purge_after,
                            "original_parent_folder_id": (
                                child_file.original_parent_folder_id or child_file.parent_folder_id
                            ),
                        }
                    )
                )

        for updated_folder in folder_updates:
            self.repository.update_folder(updated_folder)
        for updated_file in file_updates:
            self.repository.update_file(updated_file)

        logger.info(
            "catalog folder trashed",
            event_name="catalog_folder_trashed",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=folder_id,
            trashed_folder_count=len(folder_updates),
            trashed_file_count=len(file_updates),
            status="succeeded",
        )

    def move_folder(self, user: AuthenticatedUser, folder_id: str, request: MoveItemRequest) -> FolderRecord:
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
        if folder.trashed_at is not None:
            logger.warning(
                "catalog folder move rejected",
                event_name="catalog_folder_move_rejected",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                status="trashed",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot move trashed folder",
            )

        target_parent: FolderRecord | None = None
        if request.parent_folder_id is not None:
            if request.parent_folder_id == folder_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot move folder into itself or its descendant",
                )
            target_parent = self.repository.get_folder(user.subject, request.parent_folder_id)
            if target_parent is None:
                logger.warning(
                    "catalog move target lookup failed",
                    event_name="catalog_move_target_lookup_failed",
                    event_category="catalog",
                    owner_id=user.subject,
                    owner_username=user.username,
                    owner_email=user.email,
                    folder_id=folder_id,
                    target_parent_folder_id=request.parent_folder_id,
                    status="not_found",
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
            if target_parent.trashed_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Cannot move folder into trashed folder",
                )
            target_ancestors = self.repository.get_folder_ancestors(user.subject, target_parent.folder_id)
            if any(ancestor.folder_id == folder_id for ancestor in target_ancestors):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot move folder into itself or its descendant",
                )

        if folder.parent_folder_id == request.parent_folder_id:
            logger.info(
                "catalog folder move skipped",
                event_name="catalog_folder_move_skipped",
                event_category="catalog",
                owner_id=user.subject,
                owner_username=user.username,
                owner_email=user.email,
                folder_id=folder_id,
                parent_folder_id=folder.parent_folder_id,
                status="unchanged",
            )
            return folder

        siblings = self.repository.list_child_folders(user.subject, request.parent_folder_id)
        if any(
            sibling.folder_id != folder_id
            and (sibling.normalized_name or sibling.name.casefold())
            == (folder.normalized_name or folder.name.casefold())
            for sibling in siblings
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            )

        updated_at = utcnow()
        target_depth = 0 if target_parent is None else target_parent.path_depth + 1
        depth_delta = target_depth - folder.path_depth

        moved_root = folder.model_copy(
            update={
                "parent_folder_id": request.parent_folder_id,
                "path_depth": target_depth,
                "updated_at": updated_at,
            }
        )
        self.repository.update_folder(moved_root)

        queue = self.repository.list_child_folders(user.subject, folder.folder_id)
        while queue:
            current = queue.pop(0)
            updated_child = current.model_copy(
                update={
                    "path_depth": current.path_depth + depth_delta,
                    "updated_at": updated_at,
                }
            )
            self.repository.update_folder(updated_child)
            queue.extend(self.repository.list_child_folders(user.subject, current.folder_id))

        logger.info(
            "catalog folder moved",
            event_name="catalog_folder_moved",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=folder_id,
            parent_folder_id=request.parent_folder_id,
            path_depth=target_depth,
            status="succeeded",
        )
        return self.repository.get_folder(user.subject, folder_id) or moved_root

    def restore_folder(
        self,
        user: AuthenticatedUser,
        folder_id: str,
        request: RestoreItemRequest,
    ) -> CatalogRestoreResponse:
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
        if folder.trashed_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder is not trashed")

        all_folders = self.repository.list_folders(user.subject)
        folders_by_parent: dict[str | None, list[FolderRecord]] = {}
        folders_by_id = {item.folder_id: item for item in all_folders}
        for item in all_folders:
            folders_by_parent.setdefault(item.parent_folder_id, []).append(item)

        subtree_ids = {folder_id}
        queue = [folder_id]
        subtree_folders: list[FolderRecord] = []
        while queue:
            current_id = queue.pop(0)
            for child in folders_by_parent.get(current_id, []):
                subtree_ids.add(child.folder_id)
                subtree_folders.append(child)
                queue.append(child.folder_id)

        explicit_target_parent: FolderRecord | None = None
        if request.parent_folder_id is not None:
            if request.parent_folder_id in subtree_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot restore folder into itself or its descendant",
                )
            explicit_target_parent = self.repository.get_folder(user.subject, request.parent_folder_id)
            if explicit_target_parent is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
            if explicit_target_parent.trashed_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot restore folder into trashed folder",
                )

        fallback_to_root = False
        target_parent = explicit_target_parent
        if request.parent_folder_id is None and folder.original_parent_folder_id is not None:
            original_parent = folders_by_id.get(folder.original_parent_folder_id)
            if original_parent is not None and original_parent.trashed_at is None and original_parent.folder_id not in subtree_ids:
                target_parent = original_parent
            else:
                fallback_to_root = True
        elif request.parent_folder_id is None and folder.original_parent_folder_id is None:
            fallback_to_root = folder.parent_folder_id is not None

        target_parent_id = None if target_parent is None else target_parent.folder_id
        root_normalized_name = folder.normalized_name or folder.name.casefold()
        siblings = self.repository.list_child_folders(user.subject, target_parent_id)
        if any(
            sibling.folder_id != folder_id
            and (sibling.normalized_name or sibling.name.casefold()) == root_normalized_name
            for sibling in siblings
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with that name already exists in this location",
            )

        updated_at = utcnow()
        root_depth = 0 if target_parent is None else target_parent.path_depth + 1
        depth_delta = root_depth - folder.path_depth

        restored_root = folder.model_copy(
            update={
                "parent_folder_id": target_parent_id,
                "path_depth": root_depth,
                "updated_at": updated_at,
                "trashed_at": None,
                "purge_after": None,
                "original_parent_folder_id": None,
                "deleted_by_cascade": False,
            }
        )
        self.repository.update_folder(restored_root)

        for child in subtree_folders:
            restored_child = child.model_copy(
                update={
                    "path_depth": child.path_depth + depth_delta,
                    "updated_at": updated_at,
                    "trashed_at": None,
                    "purge_after": None,
                    "original_parent_folder_id": None,
                    "deleted_by_cascade": False,
                }
            )
            self.repository.update_folder(restored_child)

        file_queue = [folder_id, *[child.folder_id for child in subtree_folders]]
        for current_id in file_queue:
            for child_file in self.repository.list_child_files(user.subject, current_id):
                restored_file = child_file.model_copy(
                    update={
                        "updated_at": updated_at,
                        "trashed_at": None,
                        "purge_after": None,
                        "original_parent_folder_id": None,
                    }
                )
                self.repository.update_file(restored_file)

        message = (
            "Original parent was unavailable, item restored to root"
            if fallback_to_root and target_parent is None
            else ""
        )
        logger.info(
            "catalog folder restored",
            event_name="catalog_folder_restored",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=folder_id,
            restored_to_parent_folder_id=target_parent_id,
            restored_to_root=target_parent is None,
            status="succeeded",
        )
        return CatalogRestoreResponse(
            folder_id=folder_id,
            restored_to_parent_folder_id=target_parent_id,
            restored_to_root=target_parent is None,
            message=message,
        )

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

    def update_file(self, file_record: FileRecord) -> FileRecord:
        existing = self.repository.get_file(file_record.owner_id, file_record.file_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        if existing.trashed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot rename trashed file")

        siblings = self.repository.list_child_files(file_record.owner_id, existing.parent_folder_id)
        normalized_name = file_record.filename.casefold()
        if any(
            sibling.file_id != file_record.file_id
            and sibling.trashed_at is None
            and sibling.filename.casefold() == normalized_name
            for sibling in siblings
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file with that name already exists in this location",
            )

        updated = existing.model_copy(
            update={
                "filename": file_record.filename,
                "updated_at": file_record.updated_at,
            }
        )
        updated = self.repository.update_file(updated)
        logger.info(
            "catalog file updated",
            event_name="catalog_file_updated",
            event_category="catalog",
            file_id=updated.file_id,
            owner_id=updated.owner_id,
            filename=updated.filename,
            status="succeeded",
        )
        return updated

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

    def get_user_folder(self, user: AuthenticatedUser, folder_id: str) -> FolderRecord:
        record = self.repository.get_folder(user.subject, folder_id)
        if record is None:
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
        logger.info(
            "catalog folder fetched",
            event_name="catalog_folder_fetched",
            event_category="catalog",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            folder_id=folder_id,
            folder_name=record.name,
            status="succeeded",
        )
        return record
