from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi_versioning import version

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.errors import StudyVaultHTTPException, build_error_response
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

    @router.get("/activity/me", response_model=list[ActivityRecord])
    @version(1)
    def list_my_activity(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[ActivityRecord]:
        return service.list_user_events(user)

    @router.get("/admin/users", response_model=list[AdminUserSummary])
    @version(1)
    async def list_admin_users(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminUserSummary] | JSONResponse:
        try:
            return await admin_service.list_users(user)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post("/admin/users/{user_id}/disable", response_model=AdminUserSummary)
    @version(1)
    async def disable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_user_enabled(user, user_id, False)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post("/admin/users/{user_id}/enable", response_model=AdminUserSummary)
    @version(1)
    async def enable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_user_enabled(user, user_id, True)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post("/admin/users/{user_id}/grant-admin", response_model=AdminUserSummary)
    @version(1)
    async def grant_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_admin_role(user, user_id, True)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post("/admin/users/{user_id}/revoke-admin", response_model=AdminUserSummary)
    @version(1)
    async def revoke_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary | JSONResponse:
        try:
            return await admin_service.set_admin_role(user, user_id, False)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post("/admin/users/{user_id}/reset-password", response_model=AdminPasswordResetResult)
    @version(1)
    async def reset_password(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminPasswordResetResult | JSONResponse:
        try:
            return await admin_service.reset_password(user, user_id)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get("/admin/audit", response_model=list[AdminAuditEvent])
    @version(1)
    async def list_audit(
        limit: int = Query(default=100, ge=1, le=ADMIN_QUERY_LIMIT_MAX),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminAuditEvent] | JSONResponse:
        try:
            return await admin_service.list_audit_events(user, limit=limit)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get("/admin/health", response_model=AdminHealthSummary)
    @version(1)
    async def admin_health(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminHealthSummary | JSONResponse:
        try:
            return await admin_service.health_summary(user)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get("/admin/errors", response_model=list[AdminErrorRecord])
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
