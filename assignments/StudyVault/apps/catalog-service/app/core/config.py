from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "catalog-service"
    auth_disabled: bool = False
    keycloak_issuer_url: str = "http://keycloak:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    catalog_database_url: str = "postgresql+psycopg://studyvault:studyvault@postgres:5432/studyvault"
    internal_token: str = "internal-demo-token"

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=False
        if str(__import__("os").environ.get("STUDYVAULT_AUTH_DISABLED", "false")).lower() != "true"
        else True,
        internal_token=__import__("os").environ.get("STUDYVAULT_INTERNAL_TOKEN", "internal-demo-token"),
    )
