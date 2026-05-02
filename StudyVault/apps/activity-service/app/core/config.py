from __future__ import annotations

import os
from functools import lru_cache

from studyvault_backend_common.auth import DEFAULT_PUBLIC_TOKEN_AUDIENCE, resolve_public_token_audience
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "activity-service"
    auth_disabled: bool = False
    keycloak_base_url: str = "http://keycloak:8080"
    keycloak_realm: str = "studyvault"
    keycloak_issuer_url: str = "http://localhost:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    public_token_audience: str = DEFAULT_PUBLIC_TOKEN_AUDIENCE
    keycloak_admin_username: str = "admin"
    keycloak_admin_password: str = "admin"
    keycloak_auth_sync_enabled: bool = True
    keycloak_auth_sync_interval_seconds: float = 300.0
    keycloak_auth_sync_batch_size: int = 200
    activity_mongodb_url: str = "mongodb://mongodb:27017"
    activity_database_name: str = "studyvault_activity"
    elasticsearch_url: str = "http://elasticsearch:9200"
    catalog_service_url: str = "http://catalog-service:8000/health"
    search_service_url: str = "http://search-service:8000/health"
    file_service_url: str = "http://file-service:8000/health"
    activity_service_url: str = "http://activity-service:8000/health"
    keycloak_health_url: str = "http://keycloak:8080/realms/studyvault/.well-known/openid-configuration"
    internal_token: str = "studyvault-internal-token-change-me"

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")


def _resolve_keycloak_admin_username() -> str:
    return (
        os.environ.get("KEYCLOAK_ADMIN_USERNAME")
        or os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME")
        or "admin"
    )


def _resolve_keycloak_admin_password() -> str:
    return (
        os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
        or os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD")
        or "admin"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=os.environ.get("STUDYVAULT_AUTH_DISABLED", "false").lower() == "true",
        public_token_audience=resolve_public_token_audience(
            os.environ.get("STUDYVAULT_PUBLIC_TOKEN_AUDIENCE"),
            fallback_client_id=os.environ.get("KEYCLOAK_CLIENT_ID"),
        ),
        internal_token=os.environ.get(
            "STUDYVAULT_INTERNAL_TOKEN",
            "studyvault-internal-token-change-me",
        ),
        keycloak_admin_username=_resolve_keycloak_admin_username(),
        keycloak_admin_password=_resolve_keycloak_admin_password(),
    )
