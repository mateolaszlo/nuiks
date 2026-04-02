from __future__ import annotations

from typing import Protocol

from studyvault_backend_common.http import JsonServiceClient
from studyvault_backend_common.models import FileRecord, UploadActivityEvent


class DownstreamPublisher(Protocol):
    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None: ...

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None: ...

    async def publish_activity(self, event: UploadActivityEvent, *, bearer_token: str) -> None: ...

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord: ...


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

    async def publish_activity(self, event: UploadActivityEvent, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.activity_url}/internal/activity/events",
            event.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        payload = await self.client.get_json(
            f"{self.catalog_url}/internal/catalog/files/{file_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRecord(**payload)
