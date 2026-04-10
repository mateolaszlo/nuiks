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
    STUDYVAULT_ADMIN_ROLE,
    UploadActivityEvent,
)
from .responses import build_attachment_content_disposition
from .startup import retry_startup

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
    "JsonServiceClient",
    "ServiceClientError",
    "STUDYVAULT_ADMIN_ROLE",
    "UploadActivityEvent",
    "build_auth_dependency",
    "build_attachment_content_disposition",
    "configure_logging",
    "get_logger",
    "install_request_logging",
    "retry_startup",
]
