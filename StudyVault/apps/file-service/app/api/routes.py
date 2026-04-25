from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi_versioning import version

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.errors import StudyVaultErrorResponse, StudyVaultHTTPException, build_error_response
from studyvault_backend_common.models import (
    AuthenticatedUser,
    FileRecord,
    FileRestoreResponse,
    MoveItemRequest,
    RenameItemRequest,
    RestoreItemRequest,
)
from studyvault_backend_common.responses import build_attachment_content_disposition

from app.core.config import get_settings
from app.services.files import FileService


PUBLIC_FILE_RESPONSES = {
    401: {
        "model": StudyVaultErrorResponse,
        "description": "Missing or invalid bearer token.",
    },
}

FILE_MUTATION_RESPONSES = {
    **PUBLIC_FILE_RESPONSES,
    404: {
        "model": StudyVaultErrorResponse,
        "description": "The requested file was not found for the authenticated user.",
    },
    409: {
        "model": StudyVaultErrorResponse,
        "description": "The requested file action conflicts with current drive state.",
    },
    422: {
        "model": StudyVaultErrorResponse,
        "description": "The request payload is invalid or violates file constraints.",
    },
}

UPLOAD_RESPONSES = {
    **PUBLIC_FILE_RESPONSES,
    422: {
        "model": StudyVaultErrorResponse,
        "description": "The upload metadata or multipart payload is invalid.",
    },
    503: {
        "model": StudyVaultErrorResponse,
        "description": "Object storage or downstream metadata sync is unavailable.",
    },
}


def _studyvault_error_response(exc: StudyVaultHTTPException) -> JSONResponse:
    payload = build_error_response(exc)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


def build_public_router(service: FileService) -> APIRouter:
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

    @router.post(
        "/files",
        response_model=FileRecord,
        tags=["Files"],
        summary="Upload a file",
        description=(
            "Upload a new file into the authenticated user's drive. The request accepts multipart form "
            "data with the file bytes plus optional tags and an optional parent folder id."
        ),
        responses=UPLOAD_RESPONSES,
    )
    @version(1)
    async def upload_file(
        file: UploadFile = File(...),
        tags: list[str] | None = Form(default=None),
        parent_folder_id: str | None = Form(default=None),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRecord | JSONResponse:
        try:
            return await service.upload_file(
                user=user,
                upload=file,
                tags=tags or [],
                parent_folder_id=parent_folder_id,
            )
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.get(
        "/files/{file_id}/download",
        tags=["Files"],
        summary="Download a file",
        description="Download the stored file bytes for a file owned by the authenticated user.",
        responses={
            **PUBLIC_FILE_RESPONSES,
            404: {
                "model": StudyVaultErrorResponse,
                "description": "The requested file was not found for the authenticated user.",
            },
        },
    )
    @version(1)
    async def download_file(
        file_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> StreamingResponse:
        file_record, content = await service.download_file(user=user, file_id=file_id)
        return StreamingResponse(
            iter([content]),
            media_type="application/octet-stream",
            headers={
                "content-disposition": build_attachment_content_disposition(file_record.filename),
            },
        )

    @router.patch(
        "/files/{file_id}",
        response_model=FileRecord,
        tags=["Files"],
        summary="Rename a file",
        description="Rename a file owned by the authenticated user without changing its content.",
        responses=FILE_MUTATION_RESPONSES,
    )
    @version(1)
    async def rename_file(
        file_id: str,
        request: RenameItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRecord | JSONResponse:
        try:
            return await service.rename_file(user=user, file_id=file_id, request=request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.post(
        "/files/{file_id}/move",
        response_model=FileRecord,
        tags=["Files"],
        summary="Move a file",
        description="Move a file to another folder or back to the drive root.",
        responses=FILE_MUTATION_RESPONSES,
    )
    @version(1)
    async def move_file(
        file_id: str,
        request: MoveItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRecord | JSONResponse:
        try:
            return await service.move_file(user=user, file_id=file_id, request=request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    @router.delete(
        "/files/{file_id}",
        status_code=204,
        tags=["Files"],
        summary="Move a file to trash",
        description="Soft-delete a file by moving it to the authenticated user's trash.",
        responses={
            **PUBLIC_FILE_RESPONSES,
            404: {
                "model": StudyVaultErrorResponse,
                "description": "The requested file was not found for the authenticated user.",
            },
        },
    )
    @version(1)
    async def trash_file(
        file_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> None:
        await service.trash_file(user=user, file_id=file_id)

    @router.post(
        "/files/{file_id}/restore",
        response_model=FileRestoreResponse,
        tags=["Files"],
        summary="Restore a file",
        description=(
            "Restore a trashed file to its original parent folder when possible, or to a requested "
            "destination when provided."
        ),
        responses=FILE_MUTATION_RESPONSES,
    )
    @version(1)
    async def restore_file(
        file_id: str,
        request: RestoreItemRequest,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRestoreResponse | JSONResponse:
        try:
            return await service.restore_file(user=user, file_id=file_id, request=request)
        except StudyVaultHTTPException as exc:
            return _studyvault_error_response(exc)

    return router


def build_internal_router(service: FileService) -> APIRouter:
    router = APIRouter()
    settings = get_settings()

    async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if x_internal_token != settings.internal_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

    @router.delete(
        "/internal/files/{file_id}/hard-delete",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_internal_token)],
    )
    async def hard_delete_file(
        file_id: str,
        owner_id: str = Query(...),
    ) -> None:
        await service.hard_delete_file(owner_id=owner_id, file_id=file_id)

    return router
