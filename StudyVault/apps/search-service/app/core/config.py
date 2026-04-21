from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "search-service"
    auth_disabled: bool = False
    keycloak_issuer_url: str = "http://localhost:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    search_mongodb_url: str = "mongodb://mongodb:27017"
    search_database_name: str = "studyvault_search"
    catalog_internal_url: str = "http://catalog-service:8000"
    search_reindex_batch_size: int = 500
    internal_token: str = "studyvault-internal-token-change-me"

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=os.environ.get("STUDYVAULT_AUTH_DISABLED", "false").lower() == "true",
        catalog_internal_url=os.environ.get("CATALOG_INTERNAL_URL", "http://catalog-service:8000"),
        search_reindex_batch_size=int(os.environ.get("SEARCH_REINDEX_BATCH_SIZE", "500")),
        internal_token=os.environ.get(
            "STUDYVAULT_INTERNAL_TOKEN",
            "studyvault-internal-token-change-me",
        ),
    )
