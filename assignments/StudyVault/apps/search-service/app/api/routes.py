from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.core.config import get_settings
from app.services.search import SearchService


def build_router(service: SearchService) -> APIRouter:
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

    @router.get("/api/search", response_model=list[FileRecord])
    async def search_files(
        q: str = Query(default=""),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[FileRecord]:
        return service.search(user, q)

    @router.post(
        "/internal/search/index",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    async def index_file(file_record: FileRecord) -> FileRecord:
        return service.index_file(file_record)

    return router
