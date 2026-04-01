"""Shared backend helpers for StudyVault services."""

from .auth import AuthSettings, AuthenticatedUserDependency, build_auth_dependency
from .http import JsonServiceClient, ServiceClientError
from .logging import configure_logging, get_logger, install_request_logging
from .models import ActivityRecord, AuthenticatedUser, FileRecord, STUDYVAULT_ADMIN_ROLE, UploadActivityEvent
from .startup import retry_startup

__all__ = [
    "ActivityRecord",
    "AuthenticatedUser",
    "AuthenticatedUserDependency",
    "AuthSettings",
    "FileRecord",
    "JsonServiceClient",
    "ServiceClientError",
    "STUDYVAULT_ADMIN_ROLE",
    "UploadActivityEvent",
    "build_auth_dependency",
    "configure_logging",
    "get_logger",
    "install_request_logging",
    "retry_startup",
]
