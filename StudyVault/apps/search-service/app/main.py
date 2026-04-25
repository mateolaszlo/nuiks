from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging
from studyvault_backend_common.startup import retry_startup
from studyvault_backend_common.versioning import build_versioned_service_app, derive_public_origin_and_hosts

from app.api.routes import build_internal_router, build_public_router
from app.core.config import get_settings
from app.repositories.search import InMemorySearchRepository, MongoSearchRepository
from app.services.search import SearchService


def create_app(repository=None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    if repository is None:
        repository = MongoSearchRepository(settings.search_mongodb_url, settings.search_database_name)
    if hasattr(repository, "ping"):
        retry_startup(repository.ping)
    if hasattr(repository, "ensure_indexes"):
        retry_startup(repository.ensure_indexes)

    service = SearchService(repository)
    public_origin, allowed_hosts = derive_public_origin_and_hosts(settings.keycloak_issuer_url)
    app = build_versioned_service_app(
        title="StudyVault Search Service",
        service_name=settings.service_name,
        public_router=build_public_router(service),
        internal_router=build_internal_router(service),
        allowed_hosts=allowed_hosts,
        allowed_origins=[public_origin] if public_origin is not None else None,
        openapi_tags=[
            {
                "name": "Search",
                "description": "Gateway-facing metadata search endpoints for authenticated users.",
            }
        ],
    )
    app.state.repository = repository
    return app


app = FastAPI(title="StudyVault Search Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = ["app", "create_app", "InMemorySearchRepository"]
