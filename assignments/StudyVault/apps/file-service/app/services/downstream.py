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
    def __init__(self, *, base_url: str, internal_token: str, client: JsonServiceClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.client = client or JsonServiceClient()

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.base_url}/internal/catalog/files",
            file_record.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.base_url}/internal/search/index",
            file_record.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def publish_activity(self, event: UploadActivityEvent, *, bearer_token: str) -> None:
        await self.client.post_json(
            f"{self.base_url}/internal/activity/events",
            event.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        payload = await self.client.get_json(
            f"{self.base_url}/internal/catalog/files/{file_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )
        return FileRecord(**payload)
