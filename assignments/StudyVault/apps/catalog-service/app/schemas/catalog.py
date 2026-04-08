from __future__ import annotations

from pydantic import BaseModel

from studyvault_backend_common.models import BreadcrumbEntry, DriveItem


class CatalogItemsResponse(BaseModel):
    parent_folder_id: str | None = None
    items: list[DriveItem]


class CatalogBreadcrumbsResponse(BaseModel):
    breadcrumbs: list[BreadcrumbEntry]


class CatalogTrashResponse(BaseModel):
    items: list[DriveItem]


__all__ = ["CatalogBreadcrumbsResponse", "CatalogItemsResponse", "CatalogTrashResponse"]
