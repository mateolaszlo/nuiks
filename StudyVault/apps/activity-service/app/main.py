from __future__ import annotations

import asyncio
import os
from contextlib import suppress

from fastapi import FastAPI

from studyvault_backend_common.logging import configure_logging
from studyvault_backend_common.startup import retry_startup
from studyvault_backend_common.versioning import build_versioned_service_app, derive_public_origin_and_hosts

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
    KeycloakAuthEventSync,
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
    public_origin, allowed_hosts = derive_public_origin_and_hosts(settings.keycloak_issuer_url)
    app = build_versioned_service_app(
        title="StudyVault Activity Service",
        service_name=settings.service_name,
        public_router=build_public_router(service, admin_service),
        internal_router=build_internal_router(service),
        allowed_hosts=allowed_hosts,
        allowed_origins=[public_origin] if public_origin is not None else None,
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
    app.state.auth_sync_stop_event = None
    app.state.auth_sync_task = None

    @app.on_event("startup")
    async def start_keycloak_auth_sync() -> None:
        if not settings.keycloak_auth_sync_enabled:
            return
        stop_event = asyncio.Event()
        app.state.auth_sync_stop_event = stop_event
        auth_sync = KeycloakAuthEventSync(
            keycloak=keycloak_client,
            checkpoint_store=repository,
            batch_size=settings.keycloak_auth_sync_batch_size,
            interval_seconds=settings.keycloak_auth_sync_interval_seconds,
        )
        app.state.auth_sync_task = asyncio.create_task(auth_sync.run_forever(stop_event))

    @app.on_event("shutdown")
    async def stop_keycloak_auth_sync() -> None:
        stop_event = getattr(app.state, "auth_sync_stop_event", None)
        task = getattr(app.state, "auth_sync_task", None)
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
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
