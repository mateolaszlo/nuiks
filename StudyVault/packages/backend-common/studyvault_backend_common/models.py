from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


STUDYVAULT_ADMIN_ROLE = "studyvault_admin"
MAX_ITEM_NAME_LENGTH = 255
MAX_FILENAME_LENGTH = MAX_ITEM_NAME_LENGTH
MAX_TAG_COUNT = 20
MAX_TAG_LENGTH = 64
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def has_control_chars(value: str) -> bool:
    return bool(_CONTROL_CHARS_RE.search(value))


def validate_item_name(value: str, *, field_name: str = "Name") -> str:
    cleaned_value = value.strip()
    if not cleaned_value:
        raise ValueError(f"{field_name} must not be empty")
    if len(cleaned_value) > MAX_ITEM_NAME_LENGTH:
        raise ValueError(f"{field_name} must be at most {MAX_ITEM_NAME_LENGTH} characters")
    if has_control_chars(cleaned_value):
        raise ValueError(f"{field_name} must not contain control characters")
    if "/" in cleaned_value or "\\" in cleaned_value:
        raise ValueError(f"{field_name} must not contain path separators")
    return cleaned_value


def normalize_item_name(value: str) -> str:
    return validate_item_name(value).casefold()


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
    updated_at: datetime = Field(default_factory=utcnow)
    parent_folder_id: str | None = None
    trashed_at: datetime | None = None
    purge_after: datetime | None = None
    original_parent_folder_id: str | None = None

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return validate_item_name(value, field_name="Filename")

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


class FolderRecord(BaseModel):
    folder_id: str
    owner_id: str
    name: str
    normalized_name: str | None = None
    parent_folder_id: str | None = None
    path_depth: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    trashed_at: datetime | None = None
    purge_after: datetime | None = None
    original_parent_folder_id: str | None = None
    deleted_by_cascade: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_item_name(value, field_name="Folder name")

    @field_validator("normalized_name")
    @classmethod
    def validate_normalized_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value:
            raise ValueError("Normalized folder name must not be empty")
        if has_control_chars(value):
            raise ValueError("Normalized folder name must not contain control characters")
        if "/" in value or "\\" in value:
            raise ValueError("Normalized folder name must not contain path separators")
        return value

    @model_validator(mode="after")
    def ensure_normalized_name(self) -> "FolderRecord":
        if self.normalized_name is None:
            self.normalized_name = normalize_item_name(self.name)
        return self

    @classmethod
    def create(
        cls,
        *,
        owner_id: str,
        name: str,
        parent_folder_id: str | None = None,
        path_depth: int = 0,
    ) -> "FolderRecord":
        return cls(
            folder_id=str(uuid4()),
            owner_id=owner_id,
            name=name,
            parent_folder_id=parent_folder_id,
            path_depth=path_depth,
        )


class CreateFolderRequest(BaseModel):
    name: str
    parent_folder_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_item_name(value, field_name="Folder name")


class RenameItemRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_item_name(value, field_name="Name")


class MoveItemRequest(BaseModel):
    parent_folder_id: str | None = None


class RestoreItemRequest(BaseModel):
    parent_folder_id: str | None = None


class FileRestoreResponse(BaseModel):
    file_id: str
    restored_to_parent_folder_id: str | None = None
    restored_to_root: bool
    message: str = ""


class BreadcrumbEntry(BaseModel):
    folder_id: str | None = None
    name: str


class DriveItem(BaseModel):
    item_id: str
    kind: Literal["file", "folder"]
    owner_id: str
    name: str
    parent_folder_id: str | None = None
    created_at: datetime
    updated_at: datetime
    trashed_at: datetime | None = None
    purge_after: datetime | None = None
    size: int | None = None
    mime_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    object_key: str | None = None
    path_depth: int | None = None
    deleted_by_cascade: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_item_name(value)

    @classmethod
    def from_file(cls, record: FileRecord) -> "DriveItem":
        return cls(
            item_id=record.file_id,
            kind="file",
            owner_id=record.owner_id,
            name=record.filename,
            parent_folder_id=record.parent_folder_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            trashed_at=record.trashed_at,
            purge_after=record.purge_after,
            size=record.size,
            mime_type=record.mime_type,
            tags=record.tags,
            object_key=record.object_key,
        )

    @classmethod
    def from_folder(cls, record: FolderRecord) -> "DriveItem":
        return cls(
            item_id=record.folder_id,
            kind="folder",
            owner_id=record.owner_id,
            name=record.name,
            parent_folder_id=record.parent_folder_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            trashed_at=record.trashed_at,
            purge_after=record.purge_after,
            path_depth=record.path_depth,
            deleted_by_cascade=record.deleted_by_cascade,
        )


class ActivityRecord(BaseModel):
    activity_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    action: str
    item_id: str | None = None
    item_kind: Literal["file", "folder"] | None = None
    item_name: str | None = None
    message: str = ""
    file_id: str | None = None
    filename: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class FileActivityEvent(BaseModel):
    action: str = "file_uploaded"
    file: FileRecord


class ItemActivityEvent(BaseModel):
    action: str
    item_id: str
    item_kind: Literal["file", "folder"]
    item_name: str
    owner_id: str
    created_at: datetime = Field(default_factory=utcnow)
    parent_folder_id: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    file_id: str | None = None
    filename: str | None = None

    @classmethod
    def from_file(
        cls,
        file_record: FileRecord,
        *,
        action: str,
        old_name: str | None = None,
        new_name: str | None = None,
    ) -> "ItemActivityEvent":
        return cls(
            action=action,
            item_id=file_record.file_id,
            item_kind="file",
            item_name=file_record.filename,
            owner_id=file_record.owner_id,
            created_at=file_record.updated_at,
            parent_folder_id=file_record.parent_folder_id,
            old_name=old_name,
            new_name=new_name,
            file_id=file_record.file_id,
            filename=file_record.filename,
        )


class UploadActivityEvent(FileActivityEvent):
    action: str = "file_uploaded"


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


class StorageUsageTotals(BaseModel):
    active_bytes: int = 0
    trashed_bytes: int = 0
    total_bytes: int = 0
    active_file_count: int = 0
    trashed_file_count: int = 0
    total_file_count: int = 0


class StorageUsageSummary(StorageUsageTotals):
    owner_id: str


class FolderStats(BaseModel):
    folder_id: str
    total_size_bytes: int = 0
    file_count: int = 0
    folder_count: int = 0
