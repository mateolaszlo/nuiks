from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import (
    ActivityRecord,
    AdminAuditEvent,
    AdminErrorRecord,
    AdminHealthSummary,
    AdminPasswordResetResult,
    AdminUserSummary,
    AuthenticatedUser,
    UploadActivityEvent,
)

from app.core.config import get_settings
from app.services.admin import ADMIN_QUERY_LIMIT_MAX, AdminService
from app.services.activity import ActivityService


def build_router(service: ActivityService, admin_service: AdminService) -> APIRouter:
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

    async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if x_internal_token != settings.internal_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

    @router.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @router.get("/api/activity/me", response_model=list[ActivityRecord])
    async def list_my_activity(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[ActivityRecord]:
        return service.list_user_events(user)

    @router.post(
        "/internal/activity/events",
        response_model=ActivityRecord,
        dependencies=[Depends(require_internal_token)],
    )
    async def create_activity(event: UploadActivityEvent) -> ActivityRecord:
        return service.record_upload(event)

    @router.get("/api/admin/users", response_model=list[AdminUserSummary])
    async def list_admin_users(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminUserSummary]:
        return await admin_service.list_users(user)

    @router.post("/api/admin/users/{user_id}/disable", response_model=AdminUserSummary)
    async def disable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary:
        return await admin_service.set_user_enabled(user, user_id, False)

    @router.post("/api/admin/users/{user_id}/enable", response_model=AdminUserSummary)
    async def enable_user(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary:
        return await admin_service.set_user_enabled(user, user_id, True)

    @router.post("/api/admin/users/{user_id}/grant-admin", response_model=AdminUserSummary)
    async def grant_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary:
        return await admin_service.set_admin_role(user, user_id, True)

    @router.post("/api/admin/users/{user_id}/revoke-admin", response_model=AdminUserSummary)
    async def revoke_admin(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminUserSummary:
        return await admin_service.set_admin_role(user, user_id, False)

    @router.post("/api/admin/users/{user_id}/reset-password", response_model=AdminPasswordResetResult)
    async def reset_password(
        user_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminPasswordResetResult:
        return await admin_service.reset_password(user, user_id)

    @router.get("/api/admin/audit", response_model=list[AdminAuditEvent])
    async def list_audit(
        limit: int = Query(default=100, ge=1, le=ADMIN_QUERY_LIMIT_MAX),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminAuditEvent]:
        return await admin_service.list_audit_events(user, limit=limit)

    @router.get("/api/admin/health", response_model=AdminHealthSummary)
    async def admin_health(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> AdminHealthSummary:
        return await admin_service.health_summary(user)

    @router.get("/api/admin/errors", response_model=list[AdminErrorRecord])
    async def admin_errors(
        limit: int = Query(default=50, ge=1, le=ADMIN_QUERY_LIMIT_MAX),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[AdminErrorRecord]:
        return await admin_service.recent_errors(user, limit=limit)

    return router
