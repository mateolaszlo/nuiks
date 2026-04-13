from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Protocol

from pymongo import DESCENDING, MongoClient

from studyvault_backend_common.models import DriveItem, FileRecord


class SearchRepository(Protocol):
    def index_item(self, item: DriveItem) -> DriveItem: ...

    def index_file(self, file_record: FileRecord) -> FileRecord: ...

    def delete_item(self, item_id: str) -> None: ...

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[DriveItem]: ...

    def ping(self) -> None: ...


class InMemorySearchRepository:
    def __init__(self, seed: Iterable[FileRecord | DriveItem] | None = None) -> None:
        self._records = {}
        for record in seed or []:
            item = self._to_drive_item(record)
            self._records[item.item_id] = item

    def index_item(self, item: DriveItem) -> DriveItem:
        self._records[item.item_id] = item
        return item

    def index_file(self, file_record: FileRecord) -> FileRecord:
        item = self.index_item(DriveItem.from_file(file_record))
        return file_record

    def delete_item(self, item_id: str) -> None:
        self._records.pop(item_id, None)

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[DriveItem]:
        lowered = query.lower()
        matches = [
            item
            for item in self._records.values()
            if item.owner_id == owner_id
            and (include_trashed or item.trashed_at is None)
            and (
                lowered in item.name.lower()
                or lowered in (item.mime_type or "").lower()
                or any(lowered in tag.lower() for tag in item.tags)
            )
        ]
        return sorted(matches, key=lambda item: item.created_at, reverse=True)

    def ping(self) -> None:
        return None

    @staticmethod
    def _to_drive_item(record: FileRecord | DriveItem) -> DriveItem:
        if isinstance(record, DriveItem):
            return record
        return DriveItem.from_file(record)


class MongoSearchRepository:
    def __init__(self, mongodb_url: str, database_name: str) -> None:
        self.client = MongoClient(mongodb_url)
        self.collection = self.client[database_name]["search_documents"]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("owner_id", DESCENDING), ("created_at", DESCENDING)])

    def ping(self) -> None:
        self.client.admin.command("ping")

    def index_item(self, item: DriveItem) -> DriveItem:
        self.collection.replace_one(
            {"item_id": item.item_id},
            item.model_dump(mode="json"),
            upsert=True,
        )
        return item

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self.index_item(DriveItem.from_file(file_record))
        return file_record

    def delete_item(self, item_id: str) -> None:
        self.collection.delete_one({"item_id": item_id})

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[DriveItem]:
        regex = {"$regex": re.escape(query), "$options": "i"}
        query_filter = {
            "owner_id": owner_id,
            "$or": [
                {"name": regex},
                {"mime_type": regex},
                {"tags": regex},
            ],
        }
        if not include_trashed:
            query_filter["trashed_at"] = None
        cursor = self.collection.find(query_filter).sort("created_at", DESCENDING)
        return [DriveItem(**document) for document in cursor]
