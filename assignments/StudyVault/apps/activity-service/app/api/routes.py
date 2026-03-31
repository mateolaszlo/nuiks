from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import ActivityRecord, AuthenticatedUser, UploadActivityEvent

from app.core.config import get_settings
from app.services.activity import ActivityService


def build_router(service: ActivityService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()
    current_user_dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer=settings.keycloak_issuer_url,
            audience=settings.keycloak_client_id,
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

    return router
