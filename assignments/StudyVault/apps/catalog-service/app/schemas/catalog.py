from __future__ import annotations

from pydantic import BaseModel

from studyvault_backend_common.models import BreadcrumbEntry, DriveItem, FileRecord, FolderRecord


class CatalogItemsResponse(BaseModel):
    parent_folder_id: str | None = None
    items: list[DriveItem]


class CatalogBreadcrumbsResponse(BaseModel):
    breadcrumbs: list[BreadcrumbEntry]


class CatalogTrashResponse(BaseModel):
    items: list[DriveItem]


class CatalogExpiredTrashResponse(BaseModel):
    files: list[FileRecord]
    folders: list[FolderRecord]


class CatalogRestoreResponse(BaseModel):
    folder_id: str
    restored_to_parent_folder_id: str | None = None
    restored_to_root: bool
    message: str = ""


__all__ = [
    "CatalogBreadcrumbsResponse",
    "CatalogExpiredTrashResponse",
    "CatalogItemsResponse",
    "CatalogRestoreResponse",
    "CatalogTrashResponse",
]
