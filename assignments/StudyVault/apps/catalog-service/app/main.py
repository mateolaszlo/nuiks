from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging, install_request_logging

from app.api.routes import build_router
from app.core.config import get_settings
from app.repositories.catalog import InMemoryCatalogRepository, SqlAlchemyCatalogRepository
from app.services.catalog import CatalogService


def create_app(repository=None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    if repository is None:
        repository = SqlAlchemyCatalogRepository(settings.catalog_database_url)
    if hasattr(repository, "create_tables"):
        repository.create_tables()

    service = CatalogService(repository)
    app = FastAPI(title="StudyVault Catalog Service")
    install_request_logging(app)
    app.include_router(build_router(service))
    app.state.repository = repository
    return app


app = FastAPI(title="StudyVault Catalog Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = ["app", "create_app", "InMemoryCatalogRepository"]
