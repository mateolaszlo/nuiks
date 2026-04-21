from __future__ import annotations

from typing import Protocol

from studyvault_backend_common.http import JsonServiceClient
from studyvault_backend_common.models import DriveItem


class SearchPublisher(Protocol):
    async def publish_search_item(self, item: DriveItem, *, bearer_token: str) -> None: ...

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None: ...


class HttpSearchPublisher:
    def __init__(
        self,
        *,
        search_url: str,
        internal_token: str,
        client: JsonServiceClient | None = None,
    ) -> None:
        self.search_url = search_url.rstrip("/")
        self.internal_token = internal_token
        self.client = client or JsonServiceClient()

    async def publish_search_item(self, item: DriveItem, *, bearer_token: str) -> None:
        await self.client.put_json(
            f"{self.search_url}/internal/search/items/{item.item_id}",
            item.model_dump(mode="json"),
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        await self.client.delete_json(
            f"{self.search_url}/internal/search/items/{item_id}",
            bearer_token=bearer_token,
            internal_token=self.internal_token,
        )


class NoopSearchPublisher:
    async def publish_search_item(self, item: DriveItem, *, bearer_token: str) -> None:
        return None

    async def delete_search_item(self, item_id: str, *, bearer_token: str) -> None:
        return None
