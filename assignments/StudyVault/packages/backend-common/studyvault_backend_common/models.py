from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


STUDYVAULT_ADMIN_ROLE = "studyvault_admin"
MAX_FILENAME_LENGTH = 255
MAX_TAG_COUNT = 20
MAX_TAG_LENGTH = 64
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def has_control_chars(value: str) -> bool:
    return bool(_CONTROL_CHARS_RE.search(value))


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

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Filename must not be empty")
        if len(value) > MAX_FILENAME_LENGTH:
            raise ValueError(f"Filename must be at most {MAX_FILENAME_LENGTH} characters")
        if has_control_chars(value):
            raise ValueError("Filename must not contain control characters")
        if "/" in value or "\\" in value:
            raise ValueError("Filename must not contain path separators")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_TAG_COUNT:
            raise ValueError(f"Tags must contain at most {MAX_TAG_COUNT} items")

        normalized_tags: list[str] = []
        for tag in value:
            normalized_tag = tag.strip()
            if not normalized_tag:
                raise ValueError("Tags must not be empty")
            if len(normalized_tag) > MAX_TAG_LENGTH:
                raise ValueError(f"Tags must be at most {MAX_TAG_LENGTH} characters")
            if has_control_chars(normalized_tag):
                raise ValueError("Tags must not contain control characters")
            normalized_tags.append(normalized_tag)
        return normalized_tags

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
        object_key = f"{owner_id}/{file_id}"
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
    actor_email: str | None = None
    target_user_id: str | None = None
    target_username: str | None = None
    target_email: str | None = None
    owner_username: str | None = None
    owner_email: str | None = None
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
