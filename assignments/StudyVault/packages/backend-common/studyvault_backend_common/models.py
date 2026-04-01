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
