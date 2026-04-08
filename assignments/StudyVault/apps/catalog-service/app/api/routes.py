from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.core.config import get_settings
from app.schemas.catalog import CatalogBreadcrumbsResponse, CatalogItemsResponse, CatalogTrashResponse
from app.services.catalog import CatalogService


def build_router(service: CatalogService) -> APIRouter:
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

    @router.get("/api/catalog/files", response_model=list[FileRecord])
    def list_files(user: AuthenticatedUser = Depends(current_user_dependency)) -> list[FileRecord]:
        return service.list_user_files(user)

    @router.get("/api/catalog/items", response_model=CatalogItemsResponse)
    def list_items(
        parent_id: str | None = Query(default=None),
        include_trashed: bool = Query(default=False),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogItemsResponse:
        return service.list_items(
            user,
            parent_folder_id=parent_id,
            include_trashed=include_trashed,
        )

    @router.get("/api/catalog/breadcrumbs/{folder_id}", response_model=CatalogBreadcrumbsResponse)
    def get_breadcrumbs(
        folder_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogBreadcrumbsResponse:
        return service.get_breadcrumbs(user, folder_id)

    @router.get("/api/catalog/trash", response_model=CatalogTrashResponse)
    def list_trash(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogTrashResponse:
        return service.list_trash(user)

    @router.post(
        "/internal/catalog/files",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def create_file(file_record: FileRecord) -> FileRecord:
        return service.create_file(file_record)

    @router.get(
        "/internal/catalog/files/{file_id}",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def get_file(
        file_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRecord:
        return service.get_user_file(user, file_id)

    return router
