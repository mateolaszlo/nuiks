from __future__ import annotations

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import ActivityRecord, AuthenticatedUser, ItemActivityEvent

from app.repositories.activity import ActivityRepository


logger = get_logger(__name__)


class ActivityService:
    def __init__(self, repository: ActivityRepository) -> None:
        self.repository = repository

    def record_event(self, event: ItemActivityEvent) -> ActivityRecord:
        record = ActivityRecord(
            owner_id=event.owner_id,
            action=event.action,
            item_id=event.item_id,
            item_kind=event.item_kind,
            item_name=event.item_name,
            message=self._message_for(event),
            file_id=event.file_id,
            filename=event.filename,
            created_at=event.created_at,
        )
        created = self.repository.create_event(record)
        logger.info(
            "activity event recorded",
            event_name="activity_event_recorded",
            event_category="activity",
            activity_id=created.activity_id,
            owner_id=created.owner_id,
            item_id=created.item_id,
            item_kind=created.item_kind,
            item_name=created.item_name,
            file_id=created.file_id,
            filename=created.filename,
            action=created.action,
            status="succeeded",
        )
        return created

    @staticmethod
    def _message_for(event: ItemActivityEvent) -> str:
        if event.action == "file_uploaded":
            return f"Uploaded {event.item_name}"
        if event.action == "folder_created":
            return f"Created folder {event.item_name}"
        if event.action == "item_renamed":
            old_name = event.old_name or event.item_name
            new_name = event.new_name or event.item_name
            return f"Renamed {old_name} to {new_name}"
        if event.action == "item_moved":
            return f"Moved {event.item_name}"
        if event.action == "item_trashed":
            return f"Moved {event.item_name} to trash"
        if event.action == "item_restored":
            return f"Restored {event.item_name}"
        if event.action == "item_hard_deleted":
            return f"Permanently deleted {event.item_name}"
        return event.action.replace("_", " ").capitalize()

    def list_user_events(self, user: AuthenticatedUser) -> list[ActivityRecord]:
        records = self.repository.list_events(user.subject)
        logger.info(
            "activity list requested",
            event_name="activity_list_requested",
            event_category="activity",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            result_count=len(records),
            status="succeeded",
        )
        return records
