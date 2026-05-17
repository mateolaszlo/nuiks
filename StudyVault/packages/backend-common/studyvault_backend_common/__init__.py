"""Shared backend helpers for StudyVault services."""

from .auth import AuthSettings, AuthenticatedUserDependency, build_auth_dependency
from .http import JsonServiceClient, ServiceClientError
from .logging import configure_logging, get_logger, install_request_logging
from .models import (
    ActivityRecord,
    AdminAuditEvent,
    AdminErrorRecord,
    AdminHealthSummary,
    AdminPasswordResetResult,
    AdminServiceHealth,
    AdminUserSummary,
    AuthenticatedUser,
    FileActivityEvent,
    FileRecord,
    FileRestoreResponse,
    FolderStats,
    ItemActivityEvent,
    STUDYVAULT_ADMIN_ROLE,
    UserStorageUsage,
    UploadActivityEvent,
)
from .responses import build_attachment_content_disposition
from .startup import retry_startup
from .versioning import build_versioned_service_app

__all__ = [
    "ActivityRecord",
    "AdminAuditEvent",
    "AdminErrorRecord",
    "AdminHealthSummary",
    "AdminPasswordResetResult",
    "AdminServiceHealth",
    "AdminUserSummary",
    "AuthenticatedUser",
    "AuthenticatedUserDependency",
    "AuthSettings",
    "FileActivityEvent",
    "FileRecord",
    "FileRestoreResponse",
    "FolderStats",
    "ItemActivityEvent",
    "JsonServiceClient",
    "ServiceClientError",
    "STUDYVAULT_ADMIN_ROLE",
    "UserStorageUsage",
    "UploadActivityEvent",
    "build_auth_dependency",
    "build_attachment_content_disposition",
    "build_versioned_service_app",
    "configure_logging",
    "get_logger",
    "install_request_logging",
    "retry_startup",
]
