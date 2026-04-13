from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import AuthenticatedUser, DriveItem, FileRecord

from app.core.config import get_settings
from app.services.search import MAX_SEARCH_QUERY_LENGTH, SearchService


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
    def search_files(
        q: str = Query(default="", max_length=MAX_SEARCH_QUERY_LENGTH),
        include_trashed: bool = Query(default=False),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[FileRecord]:
        return service.search(user, q, include_trashed=include_trashed)

    @router.post(
        "/internal/search/index",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def index_file(file_record: FileRecord) -> FileRecord:
        return service.index_file(file_record)

    @router.put(
        "/internal/search/items/{item_id}",
        response_model=DriveItem,
        dependencies=[Depends(require_internal_token)],
    )
    def index_item(item_id: str, item: DriveItem) -> DriveItem:
        if item_id != item.item_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item id mismatch")
        return service.index_item(item)

    @router.delete(
        "/internal/search/items/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_internal_token)],
    )
    def delete_item(item_id: str) -> None:
        service.delete_item(item_id)

    return router
