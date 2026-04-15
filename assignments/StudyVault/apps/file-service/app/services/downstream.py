from __future__ import annotations

from typing import Protocol

from studyvault_backend_common.http import JsonServiceClient
from studyvault_backend_common.models import (
    FileRecord,
    FileRestoreResponse,
    FolderRecord,
    ItemActivityEvent,
    MoveItemRequest,
    RestoreItemRequest,
)


class DownstreamPublisher(Protocol):
    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None: ...

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None: ...

    async def publish_activity(self, event: ItemActivityEvent, *, bearer_token: str) -> None: ...

    async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord: ...

    async def fetch_catalog_folder(self, folder_id: str, *, bearer_token: str) -> FolderRecord: ...

    async def update_catalog_file(self, file_record: FileRecord, *, bearer_token: str) -> FileRecord: ...

    async def move_catalog_file(
        self,
        file_record: FileRecord,
        request: MoveItemRequest,
        *,
        bearer_token: str,
    ) -> FileRecord: ...

    async def trash_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord: ...

    async def restore_catalog_file(
        self,
        file_id: str,
        owner_id: str,
        request: RestoreItemRequest,
        *,
        bearer_token: str,
    ) -> FileRestoreResponse: ...

    async def hard_delete_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> None: ...

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None: ...


class HttpDownstreamPublisher:
    def __init__(
        self,
        *,
        catalog_url: str,
        search_url: str,
        activity_url: str,
        internal_token: str,
        client: JsonServiceClient | None = None,
    ) -> None:
        self.catalog_url = catalog_url.rstrip("/")
        self.search_url = search_url.rstrip("/")
        self.activity_url = activity_url.rstrip("/")
        self.internal_token = internal_token
        self.client = client or JsonServiceClient()

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.catalog_url}/internal/catalog/files",
            file_record.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.search_url}/internal/search/index",
            file_record.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def publish_activity(self, event: ItemActivityEvent, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.activity_url}/internal/activity/events",
            event.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def fetch_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord:
        payload = await self.client.get_json(
            f"{self.catalog_url}/internal/catalog/files/{file_id}?owner_id={owner_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRecord(**payload)

    async def fetch_catalog_folder(self, folder_id: str, *, bearer_token: str) -> FolderRecord:
        payload = await self.client.get_json(
            f"{self.catalog_url}/api/catalog/folders/{folder_id}",
            bearer_token=bearer_token,
        )
        return FolderRecord(**payload)

    async def update_catalog_file(self, file_record: FileRecord, *, bearer_token: str) -> FileRecord:
        payload = await self.client.patch_json(
            f"{self.catalog_url}/internal/catalog/files/{file_record.file_id}",
            file_record.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRecord(**payload)

    async def move_catalog_file(
        self,
        file_record: FileRecord,
        request: MoveItemRequest,
        *,
        bearer_token: str,
    ) -> FileRecord:
        payload = await self.client.post_json(
            f"{self.catalog_url}/internal/catalog/files/{file_record.file_id}/move?owner_id={file_record.owner_id}",
            {
                "parent_folder_id": request.parent_folder_id,
            },
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRecord(**payload)

    async def trash_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> FileRecord:
        payload = await self.client.delete_json(
            f"{self.catalog_url}/internal/catalog/files/{file_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
            query_params={"owner_id": owner_id},
        )
        return FileRecord(**payload)

    async def restore_catalog_file(
        self,
        file_id: str,
        owner_id: str,
        request: RestoreItemRequest,
        *,
        bearer_token: str,
    ) -> FileRestoreResponse:
        payload = await self.client.post_json(
            f"{self.catalog_url}/internal/catalog/files/{file_id}/restore?owner_id={owner_id}",
            request.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRestoreResponse(**payload)

    async def hard_delete_catalog_file(self, file_id: str, owner_id: str, *, bearer_token: str) -> None:
        await self.client.delete_json(
            f"{self.catalog_url}/internal/catalog/files/{file_id}/hard-delete",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
            query_params={"owner_id": owner_id},
        )

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        await self.client.delete_json(
            f"{self.search_url}/internal/search/items/{item_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
