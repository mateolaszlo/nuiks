from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging
from studyvault_backend_common.startup import retry_startup
from studyvault_backend_common.versioning import build_versioned_service_app, derive_public_origin_and_hosts

from app.api.routes import build_internal_router, build_public_router
from app.core.config import get_settings
from app.repositories.object_store import (
    InMemoryObjectStoreRepository,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStoreRepository,
)
from app.services.downstream import HttpDownstreamPublisher
from app.services.files import FileService


def create_app(object_store=None, downstream=None, max_upload_bytes: int | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    if object_store is None:
        object_store = S3ObjectStoreRepository(
            endpoint_url=settings.file_s3_endpoint,
            access_key=settings.file_s3_access_key,
            secret_key=settings.file_s3_secret_key,
            bucket_name=settings.file_s3_bucket,
            region_name=settings.file_s3_region,
        )
    if hasattr(object_store, "ping"):
        retry_startup(object_store.ping)
    if hasattr(object_store, "ensure_bucket"):
        retry_startup(object_store.ensure_bucket)

    if downstream is None:
        downstream = HttpDownstreamPublisher(
            catalog_url=settings.catalog_internal_url,
            search_url=settings.search_internal_url,
            activity_url=settings.activity_internal_url,
            internal_token=settings.internal_token,
        )

    service = FileService(
        object_store=object_store,
        downstream=downstream,
        max_upload_bytes=max_upload_bytes or settings.file_max_upload_bytes,
    )
    public_origin, allowed_hosts = derive_public_origin_and_hosts(settings.keycloak_issuer_url)
    app = build_versioned_service_app(
        title="StudyVault File Service",
        service_name=settings.service_name,
        public_router=build_public_router(service),
        internal_router=build_internal_router(service),
        allowed_hosts=allowed_hosts,
        allowed_origins=[public_origin] if public_origin is not None else None,
        openapi_tags=[
            {
                "name": "Files",
                "description": "Gateway-facing file upload, download, and lifecycle endpoints.",
            }
        ],
    )
    app.state.object_store = object_store
    app.state.downstream = downstream
    return app


app = FastAPI(title="StudyVault File Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = [
    "app",
    "create_app",
    "InMemoryObjectStoreRepository",
    "ObjectStoreNotFoundError",
    "ObjectStoreUnavailableError",
]
