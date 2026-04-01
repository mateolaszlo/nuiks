from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


STUDYVAULT_ADMIN_ROLE = "studyvault_admin"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthenticatedUser(BaseModel):
    subject: str
    email: str | None = None
    username: str | None = None
    roles: list[str] = Field(default_factory=list)
    token: str | None = None

    @property
    def is_admin(self) -> bool:
        return STUDYVAULT_ADMIN_ROLE in self.roles


class FileRecord(BaseModel):
    file_id: str
    owner_id: str
    filename: str
    mime_type: str
    size: int
    tags: list[str] = Field(default_factory=list)
    object_key: str
    created_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def create(
        cls,
        *,
        owner_id: str,
        filename: str,
        mime_type: str,
        size: int,
        tags: list[str] | None = None,
    ) -> "FileRecord":
        file_id = str(uuid4())
        object_key = f"{owner_id}/{file_id}/{filename}"
        return cls(
            file_id=file_id,
            owner_id=owner_id,
            filename=filename,
            mime_type=mime_type,
            size=size,
            tags=tags or [],
            object_key=object_key,
        )


class ActivityRecord(BaseModel):
    activity_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    action: str
    file_id: str
    filename: str
    created_at: datetime = Field(default_factory=utcnow)


class UploadActivityEvent(BaseModel):
    action: str = "file_uploaded"
    file: FileRecord


class ApiErrorResponse(BaseModel):
    detail: str
    extra: dict[str, Any] = Field(default_factory=dict)


class AdminUserSummary(BaseModel):
    user_id: str
    username: str
    email: str | None = None
    enabled: bool = True
    email_verified: bool = False
    roles: list[str] = Field(default_factory=list)
    created_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return STUDYVAULT_ADMIN_ROLE in self.roles


class AdminPasswordResetResult(BaseModel):
    user_id: str
    username: str
    temporary_password: str


class AdminAuditEvent(BaseModel):
    event_id: str
    event_type: str
    category: str
    actor_user_id: str | None = None
    actor_username: str | None = None
    target_user_id: str | None = None
    target_username: str | None = None
    file_id: str | None = None
    filename: str | None = None
    status: str | None = None
    service: str | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class AdminServiceHealth(BaseModel):
    service: str
    status: str
    detail: str | None = None


class AdminHealthSummary(BaseModel):
    total_users: int
    enabled_users: int
    admin_users: int
    recent_uploads: int
    recent_downloads: int
    recent_searches: int
    recent_errors: int
    services: list[AdminServiceHealth] = Field(default_factory=list)


class AdminErrorRecord(BaseModel):
    event_id: str
    service: str
    message: str
    request_id: str | None = None
    event_name: str | None = None
    status: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
