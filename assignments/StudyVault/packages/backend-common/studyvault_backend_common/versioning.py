from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi_versioning import VersionedFastAPI

from .logging import install_request_logging


def build_versioned_service_app(
    *,
    title: str,
    service_name: str,
    public_router: APIRouter,
    internal_router: APIRouter | None = None,
) -> FastAPI:
    public_app = FastAPI(title=title)
    public_app.include_router(public_router)

    app = VersionedFastAPI(
        public_app,
        version_format="{major}",
        prefix_format="/api/v{major}",
        enable_latest=False,
    )
    install_request_logging(app)

    if internal_router is not None:
        app.include_router(internal_router)

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    return app
