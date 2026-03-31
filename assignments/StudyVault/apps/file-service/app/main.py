from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging, install_request_logging

from app.api.routes import build_router
from app.core.config import get_settings
from app.repositories.object_store import InMemoryObjectStoreRepository, S3ObjectStoreRepository
from app.services.downstream import HttpDownstreamPublisher
from app.services.files import FileService


def create_app(object_store=None, downstream=None) -> FastAPI:
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
    if hasattr(object_store, "ensure_bucket"):
        object_store.ensure_bucket()

    if downstream is None:
        downstream = HttpDownstreamPublisher(
            base_url=settings.internal_base_url,
            internal_token=settings.internal_token,
        )

    service = FileService(object_store=object_store, downstream=downstream)
    app = FastAPI(title="StudyVault File Service")
    install_request_logging(app)
    app.include_router(build_router(service))
    app.state.object_store = object_store
    app.state.downstream = downstream
    return app


app = FastAPI(title="StudyVault File Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = ["app", "create_app", "InMemoryObjectStoreRepository"]
