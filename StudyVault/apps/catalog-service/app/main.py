from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging
from studyvault_backend_common.startup import retry_startup
from studyvault_backend_common.versioning import build_versioned_service_app

from app.api.routes import build_internal_router, build_public_router
from app.core.config import get_settings
from app.repositories.catalog import InMemoryCatalogRepository, SqlAlchemyCatalogRepository
from app.services.catalog import CatalogService
from app.services.downstream import HttpSearchPublisher, NoopSearchPublisher


def create_app(repository=None, downstream=None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    repository_provided = repository is not None
    if repository is None:
        repository = SqlAlchemyCatalogRepository(settings.catalog_database_url)
    if hasattr(repository, "ping"):
        retry_startup(repository.ping)
    if hasattr(repository, "create_tables"):
        retry_startup(repository.create_tables)
    if downstream is None and repository_provided:
        downstream = NoopSearchPublisher()
    if downstream is None:
        downstream = HttpSearchPublisher(
            search_url=settings.search_service_url,
            internal_token=settings.internal_token,
        )

    service = CatalogService(repository, downstream=downstream)
    app = build_versioned_service_app(
        title="StudyVault Catalog Service",
        service_name=settings.service_name,
        public_router=build_public_router(service),
        internal_router=build_internal_router(service),
        openapi_tags=[
            {
                "name": "Catalog",
                "description": "Gateway-facing drive metadata, folders, breadcrumbs, and trash endpoints.",
            }
        ],
    )
    app.state.repository = repository
    app.state.downstream = downstream
    return app


app = FastAPI(title="StudyVault Catalog Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = ["app", "create_app", "InMemoryCatalogRepository"]
