from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi_versioning import version

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.errors import StudyVaultErrorResponse, StudyVaultHTTPException, build_error_response
from studyvault_backend_common.models import (
    AuthenticatedUser,
    CreateFolderRequest,
    FileRecord,
    FolderRecord,
    MoveItemRequest,
    RenameItemRequest,
    RestoreItemRequest,
)

from app.core.config import get_settings
from app.schemas.catalog import (
    CatalogBreadcrumbsResponse,
    CatalogExpiredTrashResponse,
    CatalogItemExportResponse,
    CatalogItemsResponse,
    CatalogRestoreResponse,
    CatalogTrashResponse,
    FileRestoreResponse,
)
from app.services.catalog import CatalogService


PUBLIC_CATALOG_RESPONSES = {
    401: {
        "model": StudyVaultErrorResponse,
        "description": "Missing or invalid bearer token.",
    },
}

CATALOG_MUTATION_RESPONSES = {
    **PUBLIC_CATALOG_RESPONSES,
    404: {
        "model": StudyVaultErrorResponse,
        "description": "The requested file or folder was not found for the authenticated user.",
    },
    409: {
        "model": StudyVaultErrorResponse,
        "description": "The requested catalog change conflicts with existing drive state.",
    },
    422: {
        "model": StudyVaultErrorResponse,
        "description": "The request payload is invalid or violates folder constraints.",
    },
}


def _studyvault_error_response(exc: StudyVaultHTTPException) -> JSONResponse:
    payload = build_error_response(exc)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


def build_public_router(service: CatalogService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()
    current_user_dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer=settings.keycloak_issuer_url,
            audience=settings.public_token_audience,
            jwks_url=settings.keycloak_jwks_url,
            auth_disabled=settings.auth_disabled,
        )
    )

    @router.get(
        "/catalog/files",
        response_model=list[FileRecord],
        tags=["Catalog"],
        summary="List user files",
        description="Return all file records owned by the authenticated user.",
        responses=PUBLIC_CATALOG_RESPONSES,
    )
    @version(1)
    def list_files(user: AuthenticatedUser = Depends(current_user_dependency)) -> list[FileRecord]:
        return service.list_user_files(user)

    @router.get(
        "/catalog/items",
        response_model=CatalogItemsResponse,
        tags=["Catalog"],
        summary="List drive items",
        description=(
            "List files and folders for a specific parent folder or the drive root. Trashed items are "
            "excluded unless `include_trashed` is set."
        ),
        responses=PUBLIC_CATALOG_RESPONSES,
    )
    @version(1)
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

    @router.get(
        "/catalog/breadcrumbs/{folder_id}",
        response_model=CatalogBreadcrumbsResponse,
        tags=["Catalog"],
        summary="Get folder breadcrumbs",
        description="Return the breadcrumb trail from drive root to the requested folder.",
        responses={
            **PUBLIC_CATALOG_RESPONSES,
            404: {
                "model": StudyVaultErrorResponse,
                "description": "The requested folder was not found for the authenticated user.",
            },
        },
    )
    @version(1)
    def get_breadcrumbs(
        folder_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogBreadcrumbsResponse:
        return service.get_breadcrumbs(user, folder_id)

    @router.get(
        "/catalog/trash",
        response_model=CatalogTrashResponse,
        tags=["Catalog"],
        summary="List trash contents",
        description="Return trashed files and folders for the authenticated user.",
        responses=PUBLIC_CATALOG_RESPONSES,
    )
    @version(1)
    def list_trash(
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogTrashResponse:
        return service.list_trash(user)

    @router.get(
        "/catalog/folders/{folder_id}",
        response_model=FolderRecord,
        tags=["Catalog"],
        summary="Get folder details",
        description="Return metadata for a folder owned by the authenticated user.",
        responses={
            **PUBLIC_CATALOG_RESPONSES,
            404: {
                "model": StudyVaultErrorResponse,
                "description": "The requested folder was not found for the authenticated user.",
            },
        },
    )
    @version(1)
    def get_folder(
        folder_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FolderRecord:
        return service.get_user_folder(user, folder_id)

    @router.post(
        "/catalog/folders",
        response_model=FolderRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["Catalog"],
        summary="Create a folder",
        description="Create a new folder at drive root or inside an existing parent folder.",
        responses=CATALOG_MUTATION_RESPONSES,
    )
    @version(1)
    def create_folder(
        request: CreateFolderRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FolderRecord | JSONResponse:
        try:
            return service.create_folder(user, request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.patch(
        "/catalog/folders/{folder_id}",
        response_model=FolderRecord,
        tags=["Catalog"],
        summary="Rename a folder",
        description="Rename an existing folder owned by the authenticated user.",
        responses=CATALOG_MUTATION_RESPONSES,
    )
    @version(1)
    def rename_folder(
        folder_id: str,
        request: RenameItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FolderRecord | JSONResponse:
        try:
            return service.rename_folder(user, folder_id, request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.delete(
        "/catalog/folders/{folder_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Catalog"],
        summary="Move a folder to trash",
        description="Soft-delete a folder and any descendants by moving them to trash.",
        responses={
            **PUBLIC_CATALOG_RESPONSES,
            404: {
                "model": StudyVaultErrorResponse,
                "description": "The requested folder was not found for the authenticated user.",
            },
        },
    )
    @version(1)
    def trash_folder(
        folder_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> None:
        service.trash_folder(user, folder_id)

    @router.post(
        "/catalog/folders/{folder_id}/move",
        response_model=FolderRecord,
        tags=["Catalog"],
        summary="Move a folder",
        description="Move a folder to a different parent folder or back to drive root.",
        responses=CATALOG_MUTATION_RESPONSES,
    )
    @version(1)
    def move_folder(
        folder_id: str,
        request: MoveItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FolderRecord | JSONResponse:
        try:
            return service.move_folder(user, folder_id, request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/catalog/folders/{folder_id}/restore",
        response_model=CatalogRestoreResponse,
        tags=["Catalog"],
        summary="Restore a folder",
        description=(
            "Restore a trashed folder to its original parent folder when possible, or to a requested "
            "destination when provided."
        ),
        responses=CATALOG_MUTATION_RESPONSES,
    )
    @version(1)
    def restore_folder(
        folder_id: str,
        request: RestoreItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> CatalogRestoreResponse | JSONResponse:
        try:
            return service.restore_folder(user, folder_id, request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    return router


def build_internal_router(service: CatalogService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()

    async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if x_internal_token != settings.internal_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

    @router.get(
        "/internal/catalog/trash/expired",
        response_model=CatalogExpiredTrashResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def list_expired_trash(
        before: datetime = Query(...),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> CatalogExpiredTrashResponse:
        return service.list_expired_trash(before=before, limit=limit)

    @router.get(
        "/internal/catalog/items/export",
        response_model=CatalogItemExportResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def export_items(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        include_trashed: bool = Query(default=True),
    ) -> CatalogItemExportResponse:
        return service.export_items(
            offset=offset,
            limit=limit,
            include_trashed=include_trashed,
        )

    @router.post(
        "/internal/catalog/files",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def create_file(file_record: FileRecord) -> FileRecord:
        return service.create_file(file_record)

    @router.patch(
        "/internal/catalog/files/{file_id}",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def update_file(
        file_id: str,
        file_record: FileRecord,
    ) -> FileRecord | JSONResponse:
        if file_id != file_record.file_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File id mismatch")
        try:
            return service.update_file(file_record)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/internal/catalog/files/{file_id}/move",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def move_file(
        file_id: str,
        request: MoveItemRequest,
        owner_id: str = Query(...),
    ) -> FileRecord | JSONResponse:
        try:
            return service.move_file(owner_id=owner_id, file_id=file_id, request=request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.delete(
        "/internal/catalog/files/{file_id}",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def trash_file(
        file_id: str,
        owner_id: str = Query(...),
    ) -> FileRecord:
        return service.trash_file(owner_id=owner_id, file_id=file_id)

    @router.post(
        "/internal/catalog/files/{file_id}/restore",
        response_model=FileRestoreResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def restore_file(
        file_id: str,
        request: RestoreItemRequest,
        owner_id: str = Query(...),
    ) -> FileRestoreResponse | JSONResponse:
        try:
            return service.restore_file(owner_id=owner_id, file_id=file_id, request=request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.delete(
        "/internal/catalog/files/{file_id}/hard-delete",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_internal_token)],
    )
    def hard_delete_file(
        file_id: str,
        owner_id: str = Query(...),
    ) -> None:
        service.hard_delete_file(owner_id=owner_id, file_id=file_id)

    @router.delete(
        "/internal/catalog/folders/{folder_id}/hard-delete",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_internal_token)],
    )
    def hard_delete_folder(
        folder_id: str,
        owner_id: str = Query(...),
    ) -> None:
        service.hard_delete_folder(owner_id=owner_id, folder_id=folder_id)

    @router.get(
        "/internal/catalog/files/{file_id}",
        response_model=FileRecord,
        dependencies=[Depends(require_internal_token)],
    )
    def get_file(
        file_id: str,
        owner_id: str = Query(...),
    ) -> FileRecord:
        return service.get_file_for_owner(owner_id=owner_id, file_id=file_id)

    return router
