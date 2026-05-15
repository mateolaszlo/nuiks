from __future__ import annotations

import os
from functools import lru_cache

from studyvault_backend_common.auth import DEFAULT_PUBLIC_TOKEN_AUDIENCE, resolve_public_token_audience
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "catalog-service"
    auth_disabled: bool = False
    keycloak_issuer_url: str = "http://localhost:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    public_token_audience: str = DEFAULT_PUBLIC_TOKEN_AUDIENCE
    catalog_database_url: str = "postgresql+psycopg://studyvault:studyvault@postgres:5432/studyvault"
    search_service_url: str = "http://search-service:8000"
    file_service_url: str = "http://file-service:8000"
    activity_service_url: str = "http://activity-service:8000"
    internal_token: str = "studyvault-internal-token-change-me"

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=False
        if str(os.getenv("STUDYVAULT_AUTH_DISABLED", "false")).lower() != "true"
        else True,
        public_token_audience=resolve_public_token_audience(
            os.environ.get("STUDYVAULT_PUBLIC_TOKEN_AUDIENCE"),
            fallback_client_id=os.environ.get("KEYCLOAK_CLIENT_ID"),
        ),
        search_service_url=os.getenv("SEARCH_SERVICE_URL", "http://search-service:8000"),
        file_service_url=os.getenv("FILE_SERVICE_URL", "http://file-service:8000"),
        activity_service_url=os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8000"),
        internal_token=os.getenv(
            "STUDYVAULT_INTERNAL_TOKEN",
            "studyvault-internal-token-change-me",
        ),
    )
