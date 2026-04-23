from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi_versioning import VersionedFastAPI

from .errors import register_error_handlers
from .logging import install_request_logging


_DOCS_ROUTE_PATHS = {
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _remove_generated_docs_routes(app: FastAPI) -> None:
    version_prefixes = {
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v")
        and hasattr(getattr(route, "app", None), "routes")
    }

    blocked_parent_paths = set(_DOCS_ROUTE_PATHS)
    for prefix in version_prefixes:
        blocked_parent_paths.update({f"{prefix}{suffix}" for suffix in _DOCS_ROUTE_PATHS})

    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in blocked_parent_paths
    ]

    for route in app.router.routes:
        path = getattr(route, "path", "")
        mounted_app = getattr(route, "app", None)
        if path not in version_prefixes or not hasattr(mounted_app, "router"):
            continue
        mounted_app.docs_url = None
        mounted_app.redoc_url = None
        mounted_app.openapi_url = None
        mounted_app.router.routes = [
            child_route
            for child_route in mounted_app.router.routes
            if getattr(child_route, "path", None) not in _DOCS_ROUTE_PATHS
        ]


def build_versioned_service_app(
    *,
    title: str,
    service_name: str,
    public_router: APIRouter,
    internal_router: APIRouter | None = None,
    openapi_tags: list[dict[str, str]] | None = None,
) -> FastAPI:
    public_app = FastAPI(
        title=title,
        openapi_tags=openapi_tags,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    register_error_handlers(public_app)
    public_app.include_router(public_router)

    app = VersionedFastAPI(
        public_app,
        version_format="{major}",
        prefix_format="/api/v{major}",
        enable_latest=False,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    _remove_generated_docs_routes(app)
    register_error_handlers(app)
    install_request_logging(app)

    if internal_router is not None:
        app.include_router(internal_router)

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    return app
