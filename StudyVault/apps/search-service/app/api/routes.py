from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi_versioning import version

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.errors import StudyVaultErrorResponse, api_error
from studyvault_backend_common.models import AuthenticatedUser, DriveItem, FileRecord

from app.core.config import get_settings
from app.services.search import MAX_SEARCH_QUERY_LENGTH, SearchService


PUBLIC_SEARCH_RESPONSES = {
    401: {
        "model": StudyVaultErrorResponse,
        "description": "Missing or invalid bearer token.",
    },
    422: {
        "description": "Invalid query parameters or search query too long.",
    },
}


def build_public_router(service: SearchService) -> APIRouter:
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

    @router.get(
        "/search",
        response_model=list[DriveItem],
        tags=["Search"],
        summary="Search drive items",
        description=(
            "Search the authenticated user's files and folders by filename, MIME type, and tags. "
            "Results can be filtered by item kind, folder, and trash state."
        ),
        responses=PUBLIC_SEARCH_RESPONSES,
    )
    @version(1)
    def search_files(
        q: str = Query(default=""),
        include_trashed: bool = Query(default=False),
        kind: Literal["file", "folder", "all"] = Query(default="all"),
        parent_id: str | None = Query(default=None),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> list[DriveItem]:
        if len(q) > MAX_SEARCH_QUERY_LENGTH:
            raise api_error(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Search query must be at most {MAX_SEARCH_QUERY_LENGTH} characters",
                code="search_query_too_long",
                category="validation",
                context={"max_query_length": MAX_SEARCH_QUERY_LENGTH},
            )
        return service.search(
            user,
            q,
            include_trashed=include_trashed,
            kind=kind,
            parent_id=parent_id,
        )

    return router


def build_internal_router(service: SearchService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()

    async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if x_internal_token != settings.internal_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

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
