from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pymongo import DESCENDING, MongoClient

from studyvault_backend_common.models import ActivityRecord


class ActivityRepository(Protocol):
    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord: ...

    def list_events(self, owner_id: str) -> list[ActivityRecord]: ...


class InMemoryActivityRepository:
    def __init__(self, seed: Iterable[ActivityRecord] | None = None) -> None:
        self._records = {record.activity_id: record for record in seed or []}

    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord:
        self._records[activity_record.activity_id] = activity_record
        return activity_record

    def list_events(self, owner_id: str) -> list[ActivityRecord]:
        records = [record for record in self._records.values() if record.owner_id == owner_id]
        return sorted(records, key=lambda item: item.created_at, reverse=True)


class MongoActivityRepository:
    def __init__(self, mongodb_url: str, database_name: str) -> None:
        self.client = MongoClient(mongodb_url)
        self.collection = self.client[database_name]["activity_events"]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("owner_id", DESCENDING), ("created_at", DESCENDING)])

    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord:
        self.collection.insert_one(activity_record.model_dump(mode="json"))
        return activity_record

    def list_events(self, owner_id: str) -> list[ActivityRecord]:
        cursor = self.collection.find({"owner_id": owner_id}).sort("created_at", DESCENDING)
        return [ActivityRecord(**document) for document in cursor]
