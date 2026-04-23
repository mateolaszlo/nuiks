from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi_versioning import version

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.errors import StudyVaultErrorResponse, StudyVaultHTTPException, build_error_response
from studyvault_backend_common.models import (
    ActivityRecord,
    AdminAuditEvent,
    AdminErrorRecord,
    AdminHealthSummary,
    AdminPasswordResetResult,
    AdminUserSummary,
    AuthenticatedUser,
    ItemActivityEvent,
)

from app.core.config import get_settings
from app.services.admin import ADMIN_QUERY_LIMIT_MAX, AdminService
from app.services.activity import ActivityService


PUBLIC_ACTIVITY_RESPONSES = {
    401: {
        "model": StudyVaultErrorResponse,
        "description": "Missing or invalid bearer token.",
    },
}

ADMIN_RESPONSES = {
    **PUBLIC_ACTIVITY_RESPONSES,
    403: {
        "model": StudyVaultErrorResponse,
        "description": "Authenticated user does not have the `studyvault_admin` role.",
    },
    404: {
        "model": StudyVaultErrorResponse,
        "description": "The requested admin target was not found.",
    },
    422: {
        "description": "Invalid query parameters.",
    },
}


def _studyvault_error_response(exc: StudyVaultHTTPException) -> JSONResponse:
    payload = build_error_response(exc)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


def build_public_router(service: ActivityService, admin_service: AdminService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()
    current_user_dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer=settings.keycloak_issuer_url,
            audience=None,
            jwks_url=settings.keycloak_jwks_url,
            auth_disabled=settings.auth_disabled,
        )
    )

    @router.get(
        "/activity/me",
        response_model=list[ActivityRecord],
        tags=["Activity"],
        summary="List my activity",
        description="Return recent activity events for the authenticated user.",
        responses=PUBLIC_ACTIVITY_RESPONSES,
    )
    @version(1)
    def list_my_activity(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[ActivityRecord]:
        return service.list_user_events(user)

    @router.get(
        "/admin/users",
        response_model=list[AdminUserSummary],
        tags=["Admin"],
        summary="List users",
        description="Return the current user list visible to StudyVault administrators.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def list_admin_users(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminUserSummary] | JSONResponse:
        try:
            return await admin_service.list_users(user)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/admin/users/{user_id}/disable",
        response_model=AdminUserSummary,
        tags=["Admin"],
        summary="Disable a user",
        description="Disable a StudyVault user account through the admin backend.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def disable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_user_enabled(user, user_id, False)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/admin/users/{user_id}/enable",
        response_model=AdminUserSummary,
        tags=["Admin"],
        summary="Enable a user",
        description="Re-enable a previously disabled StudyVault user account.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def enable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_user_enabled(user, user_id, True)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/admin/users/{user_id}/grant-admin",
        response_model=AdminUserSummary,
        tags=["Admin"],
        summary="Grant admin role",
        description="Grant the `studyvault_admin` role to a user.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def grant_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_admin_role(user, user_id, True)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/admin/users/{user_id}/revoke-admin",
        response_model=AdminUserSummary,
        tags=["Admin"],
        summary="Revoke admin role",
        description="Remove the `studyvault_admin` role from a user.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def revoke_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_admin_role(user, user_id, False)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/admin/users/{user_id}/reset-password",
        response_model=AdminPasswordResetResult,
        tags=["Admin"],
        summary="Reset a user password",
        description="Reset a user's password and return a temporary credential.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def reset_password(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminPasswordResetResult | JSONResponse:
        try:
            return await admin_service.reset_password(user, user_id)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get(
        "/admin/audit",
        response_model=list[AdminAuditEvent],
        tags=["Admin"],
        summary="List admin audit events",
        description="Return recent authentication and application audit events for administrators.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def list_audit(
        limit: int = Query(default=100, ge=1, le=ADMIN_QUERY_LIMIT_MAX),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminAuditEvent] | JSONResponse:
        try:
            return await admin_service.list_audit_events(user, limit=limit)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get(
        "/admin/health",
        response_model=AdminHealthSummary,
        tags=["Admin"],
        summary="Get admin health summary",
        description="Return service health and recent operational counters for administrators.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def admin_health(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminHealthSummary | JSONResponse:
        try:
            return await admin_service.health_summary(user)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get(
        "/admin/errors",
        response_model=list[AdminErrorRecord],
        tags=["Admin"],
        summary="List recent errors",
        description="Return recent operator-facing application errors for administrators.",
        responses=ADMIN_RESPONSES,
    )
    @version(1)
    async def admin_errors(
        limit: int = Query(default=50, ge=1, le=ADMIN_QUERY_LIMIT_MAX),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminErrorRecord] | JSONResponse:
        try:
            return await admin_service.recent_errors(user, limit=limit)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    return router


def build_internal_router(service: ActivityService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()

    async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if x_internal_token != settings.internal_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

    @router.post(
        "/internal/activity/events",
        response_model=ActivityRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def create_activity(event: ItemActivityEvent) -> ActivityRecord:
        return service.record_event(event)

    return router
