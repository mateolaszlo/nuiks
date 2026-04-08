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


__all__ = [
    "CatalogBreadcrumbsResponse",
    "CatalogExpiredTrashResponse",
    "CatalogItemsResponse",
    "CatalogTrashResponse",
]
