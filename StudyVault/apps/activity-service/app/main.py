from __future__ import annotations

import os

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging
from studyvault_backend_common.startup import retry_startup
from studyvault_backend_common.versioning import build_versioned_service_app

from app.api.routes import build_internal_router, build_public_router
from app.core.config import get_settings
from app.repositories.activity import InMemoryActivityRepository, MongoActivityRepository
from app.services.admin import AdminService
from app.services.admin_integrations import (
    ElasticsearchAuditClient,
    HttpServiceHealthClient,
    InMemoryAuditLogGateway,
    InMemoryKeycloakAdminGateway,
    InMemoryServiceHealthGateway,
    KeycloakAdminClient,
)
from app.services.activity import ActivityService


def create_app(repository=None, keycloak_client=None, audit_client=None, health_client=None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    if repository is None:
        repository = MongoActivityRepository(settings.activity_mongodb_url, settings.activity_database_name)
    if hasattr(repository, "ping"):
        retry_startup(repository.ping)
    if hasattr(repository, "ensure_indexes"):
        retry_startup(repository.ensure_indexes)

    if keycloak_client is None:
        keycloak_client = KeycloakAdminClient(
            base_url=settings.keycloak_base_url,
            realm=settings.keycloak_realm,
            username=settings.keycloak_admin_username,
            password=settings.keycloak_admin_password,
        )
    if audit_client is None:
        audit_client = ElasticsearchAuditClient(elasticsearch_url=settings.elasticsearch_url)
    if health_client is None:
        health_client = HttpServiceHealthClient(
            {
                "keycloak": settings.keycloak_health_url,
                "catalog-service": settings.catalog_service_url,
                "search-service": settings.search_service_url,
                "file-service": settings.file_service_url,
                "activity-service": settings.activity_service_url,
            }
        )

    service = ActivityService(repository)
    admin_service = AdminService(
        keycloak=keycloak_client,
        audit_logs=audit_client,
        service_health=health_client,
    )
    app = build_versioned_service_app(
        title="StudyVault Activity Service",
        service_name=settings.service_name,
        public_router=build_public_router(service, admin_service),
        internal_router=build_internal_router(service),
        openapi_tags=[
            {
                "name": "Activity",
                "description": "Gateway-facing activity feed endpoints for authenticated users.",
            },
            {
                "name": "Admin",
                "description": "Gateway-facing administrative endpoints served by the activity service.",
            },
        ],
    )
    app.state.repository = repository
    app.state.keycloak_client = keycloak_client
    app.state.audit_client = audit_client
    app.state.health_client = health_client
    return app


app = FastAPI(title="StudyVault Activity Service placeholder")
if os.environ.get("STUDYVAULT_SKIP_APP_BOOTSTRAP", "false").lower() != "true":
    app = create_app()


__all__ = [
    "app",
    "create_app",
    "InMemoryActivityRepository",
    "InMemoryKeycloakAdminGateway",
    "InMemoryAuditLogGateway",
    "InMemoryServiceHealthGateway",
]
