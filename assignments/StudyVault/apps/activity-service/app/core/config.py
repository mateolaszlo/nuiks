from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "activity-service"
    auth_disabled: bool = False
    keycloak_base_url: str = "http://keycloak:8080"
    keycloak_realm: str = "studyvault"
    keycloak_issuer_url: str = "http://localhost:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    keycloak_admin_username: str = "admin"
    keycloak_admin_password: str = "admin"
    activity_mongodb_url: str = "mongodb://mongodb:27017"
    activity_database_name: str = "studyvault_activity"
    elasticsearch_url: str = "http://elasticsearch:9200"
    catalog_service_url: str = "http://catalog-service:8000/health"
    search_service_url: str = "http://search-service:8000/health"
    file_service_url: str = "http://file-service:8000/health"
    activity_service_url: str = "http://activity-service:8000/health"
    keycloak_health_url: str = "http://keycloak:8080/realms/studyvault/.well-known/openid-configuration"
    internal_token: str = "internal-demo-token"

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=os.environ.get("STUDYVAULT_AUTH_DISABLED", "false").lower() == "true",
        internal_token=os.environ.get("STUDYVAULT_INTERNAL_TOKEN", "internal-demo-token"),
    )
