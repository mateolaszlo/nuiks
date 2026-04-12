from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Protocol

from pymongo import DESCENDING, MongoClient

from studyvault_backend_common.models import FileRecord


class SearchRepository(Protocol):
    def index_file(self, file_record: FileRecord) -> FileRecord: ...

    def delete_item(self, item_id: str) -> None: ...

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[FileRecord]: ...

    def ping(self) -> None: ...


class InMemorySearchRepository:
    def __init__(self, seed: Iterable[FileRecord] | None = None) -> None:
        self._records = {record.file_id: record for record in seed or []}

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self._records[file_record.file_id] = file_record
        return file_record

    def delete_item(self, item_id: str) -> None:
        self._records.pop(item_id, None)

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[FileRecord]:
        lowered = query.lower()
        matches = [
            record
            for record in self._records.values()
            if record.owner_id == owner_id
            and (include_trashed or record.trashed_at is None)
            and (
                lowered in record.filename.lower()
                or lowered in record.mime_type.lower()
                or any(lowered in tag.lower() for tag in record.tags)
            )
        ]
        return sorted(matches, key=lambda item: item.created_at, reverse=True)

    def ping(self) -> None:
        return None


class MongoSearchRepository:
    def __init__(self, mongodb_url: str, database_name: str) -> None:
        self.client = MongoClient(mongodb_url)
        self.collection = self.client[database_name]["search_documents"]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("owner_id", DESCENDING), ("created_at", DESCENDING)])

    def ping(self) -> None:
        self.client.admin.command("ping")

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self.collection.replace_one(
            {"file_id": file_record.file_id},
            file_record.model_dump(mode="json"),
            upsert=True,
        )
        return file_record

    def delete_item(self, item_id: str) -> None:
        self.collection.delete_one({"file_id": item_id})

    def search(self, owner_id: str, query: str, *, include_trashed: bool = False) -> list[FileRecord]:
        regex = {"$regex": re.escape(query), "$options": "i"}
        query_filter = {
            "owner_id": owner_id,
            "$or": [
                {"filename": regex},
                {"mime_type": regex},
                {"tags": regex},
            ],
        }
        if not include_trashed:
            query_filter["trashed_at"] = None
        cursor = self.collection.find(query_filter).sort("created_at", DESCENDING)
        return [FileRecord(**document) for document in cursor]
