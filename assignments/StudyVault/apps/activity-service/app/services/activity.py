from __future__ import annotations

from studyvault_backend_common.models import ActivityRecord, AuthenticatedUser, UploadActivityEvent

from app.repositories.activity import ActivityRepository


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
        return self.repository.create_event(record)

    def list_user_events(self, user: AuthenticatedUser) -> list[ActivityRecord]:
        return self.repository.list_events(user.subject)
