"""Shared backend helpers for StudyVault services."""

from .auth import AuthSettings, AuthenticatedUserDependency, build_auth_dependency
from .http import JsonServiceClient, ServiceClientError
from .logging import configure_logging, get_logger, install_request_logging
from .models import ActivityRecord, AuthenticatedUser, FileRecord, UploadActivityEvent

__all__ = [
    "ActivityRecord",
    "AuthenticatedUser",
    "AuthenticatedUserDependency",
    "AuthSettings",
    "FileRecord",
    "JsonServiceClient",
    "ServiceClientError",
    "UploadActivityEvent",
    "build_auth_dependency",
    "configure_logging",
    "get_logger",
    "install_request_logging",
]
