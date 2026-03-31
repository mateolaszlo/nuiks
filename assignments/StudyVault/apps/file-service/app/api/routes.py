from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.core.config import get_settings
from app.services.files import FileService


def build_router(service: FileService) -> APIRouter:
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

    @router.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @router.post("/api/files", response_model=FileRecord)
    async def upload_file(
        file: UploadFile = File(...),
        tags: list[str] | None = Form(default=None),
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> FileRecord:
        return await service.upload_file(user=user, upload=file, tags=tags or [])

    @router.get("/api/files/{file_id}/download")
    async def download_file(
        file_id: str,
        user: AuthenticatedUser = Depends(current_user_dependency),
    ) -> StreamingResponse:
        file_record, content = await service.download_file(user=user, file_id=file_id)
        return StreamingResponse(
            iter([content]),
            media_type=file_record.mime_type,
            headers={
                "content-disposition": f'attachment; filename="{file_record.filename}"',
            },
        )

    return router
