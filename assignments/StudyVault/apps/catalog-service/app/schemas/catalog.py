from __future__ import annotations

from pydantic import BaseModel

from studyvault_backend_common.models import DriveItem


class CatalogItemsResponse(BaseModel):
    parent_folder_id: str | None = None
    items: list[DriveItem]


__all__ = ["CatalogItemsResponse"]
