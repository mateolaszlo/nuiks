from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pymongo import DESCENDING, MongoClient

from studyvault_backend_common.models import FileRecord


class SearchRepository(Protocol):
    def index_file(self, file_record: FileRecord) -> FileRecord: ...

    def search(self, owner_id: str, query: str) -> list[FileRecord]: ...


class InMemorySearchRepository:
    def __init__(self, seed: Iterable[FileRecord] | None = None) -> None:
        self._records = {record.file_id: record for record in seed or []}

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self._records[file_record.file_id] = file_record
        return file_record

    def search(self, owner_id: str, query: str) -> list[FileRecord]:
        lowered = query.lower()
        matches = [
            record
            for record in self._records.values()
            if record.owner_id == owner_id
            and (
                lowered in record.filename.lower()
                or lowered in record.mime_type.lower()
                or any(lowered in tag.lower() for tag in record.tags)
            )
        ]
        return sorted(matches, key=lambda item: item.created_at, reverse=True)


class MongoSearchRepository:
    def __init__(self, mongodb_url: str, database_name: str) -> None:
        self.client = MongoClient(mongodb_url)
        self.collection = self.client[database_name]["search_documents"]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("owner_id", DESCENDING), ("created_at", DESCENDING)])

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self.collection.replace_one(
            {"file_id": file_record.file_id},
            file_record.model_dump(mode="json"),
            upsert=True,
        )
        return file_record

    def search(self, owner_id: str, query: str) -> list[FileRecord]:
        regex = {"$regex": query, "$options": "i"}
        cursor = self.collection.find(
            {
                "owner_id": owner_id,
                "$or": [
                    {"filename": regex},
                    {"mime_type": regex},
                    {"tags": regex},
                ],
            }
        ).sort("created_at", DESCENDING)
        return [FileRecord(**document) for document in cursor]
