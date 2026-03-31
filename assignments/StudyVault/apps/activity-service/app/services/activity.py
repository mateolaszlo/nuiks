from __future__ import annotations

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import ActivityRecord, AuthenticatedUser, UploadActivityEvent

from app.repositories.activity import ActivityRepository


logger = get_logger(__name__)


class ActivityService:
    def __init__(self, repository: ActivityRepository) -> None:
        self.repository = repository

    def record_upload(self, event: UploadActivityEvent) -> ActivityRecord:
        record = ActivityRecord(
            owner_id=event.file.owner_id,
            action=event.action,
            file_id=event.file.file_id,
            filename=event.file.filename,
            created_at=event.file.created_at,
        )
        created = self.repository.create_event(record)
        logger.info(
            "activity event recorded",
            event_name="activity_event_recorded",
            event_category="activity",
            activity_id=created.activity_id,
            owner_id=created.owner_id,
            file_id=created.file_id,
            filename=created.filename,
            action=created.action,
            status="succeeded",
        )
        return created

    def list_user_events(self, user: AuthenticatedUser) -> list[ActivityRecord]:
        records = self.repository.list_events(user.subject)
        logger.info(
            "activity list requested",
            event_name="activity_list_requested",
            event_category="activity",
            owner_id=user.subject,
            result_count=len(records),
            status="succeeded",
        )
        return records
