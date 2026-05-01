from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from pymongo import DESCENDING, MongoClient

from studyvault_backend_common.models import ActivityRecord


class ActivityRepository(Protocol):
    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord: ...

    def list_events(self, owner_id: str) -> list[ActivityRecord]: ...

    def get_auth_event_sync_checkpoint(self) -> tuple[datetime, str] | None: ...

    def save_auth_event_sync_checkpoint(self, created_at: datetime, event_id: str) -> None: ...

    def ping(self) -> None: ...


class InMemoryActivityRepository:
    def __init__(self, seed: Iterable[ActivityRecord] | None = None) -> None:
        self._records = {record.activity_id: record for record in seed or []}
        self._auth_event_sync_checkpoint: tuple[datetime, str] | None = None

    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord:
        self._records[activity_record.activity_id] = activity_record
        return activity_record

    def list_events(self, owner_id: str) -> list[ActivityRecord]:
        records = [record for record in self._records.values() if record.owner_id == owner_id]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def get_auth_event_sync_checkpoint(self) -> tuple[datetime, str] | None:
        return self._auth_event_sync_checkpoint

    def save_auth_event_sync_checkpoint(self, created_at: datetime, event_id: str) -> None:
        self._auth_event_sync_checkpoint = (created_at, event_id)

    def ping(self) -> None:
        return None


class MongoActivityRepository:
    def __init__(self, mongodb_url: str, database_name: str) -> None:
        self.client = MongoClient(mongodb_url)
        self.collection = self.client[database_name]["activity_events"]
        self.state_collection = self.client[database_name]["service_state"]
        self._auth_event_sync_key = "keycloak_auth_event_sync"

    def ensure_indexes(self) -> None:
        self.collection.create_index([("owner_id", DESCENDING), ("created_at", DESCENDING)])
        self.state_collection.create_index("key", unique=True)

    def ping(self) -> None:
        self.client.admin.command("ping")

    def create_event(self, activity_record: ActivityRecord) -> ActivityRecord:
        self.collection.insert_one(activity_record.model_dump(mode="json"))
        return activity_record

    def list_events(self, owner_id: str) -> list[ActivityRecord]:
        cursor = self.collection.find({"owner_id": owner_id}).sort("created_at", DESCENDING)
        return [ActivityRecord(**document) for document in cursor]

    def get_auth_event_sync_checkpoint(self) -> tuple[datetime, str] | None:
        document = self.state_collection.find_one({"key": self._auth_event_sync_key})
        if document is None or not isinstance(document.get("created_at"), datetime):
            return None
        created_at = document["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return created_at, document.get("event_id", "")

    def save_auth_event_sync_checkpoint(self, created_at: datetime, event_id: str) -> None:
        self.state_collection.replace_one(
            {"key": self._auth_event_sync_key},
            {
                "key": self._auth_event_sync_key,
                "created_at": created_at,
                "event_id": event_id,
            },
            upsert=True,
        )
