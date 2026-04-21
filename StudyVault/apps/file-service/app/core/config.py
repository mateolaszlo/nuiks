from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "file-service"
    auth_disabled: bool = False
    keycloak_issuer_url: str = "http://localhost:8080/realms/studyvault"
    keycloak_jwks_url: str = "http://keycloak:8080/realms/studyvault/protocol/openid-connect/certs"
    keycloak_client_id: str = "studyvault-frontend"
    catalog_internal_url: str = "http://catalog-service:8000"
    search_internal_url: str = "http://search-service:8000"
    activity_internal_url: str = "http://activity-service:8000"
    internal_token: str = "studyvault-internal-token-change-me"
    file_s3_endpoint: str = "http://minio:9000"
    file_s3_access_key: str = "minioadmin"
    file_s3_secret_key: str = "minioadmin"
    file_s3_bucket: str = "studyvault-files"
    file_s3_region: str = "us-east-1"
    file_max_upload_bytes: int = 104857600

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        auth_disabled=os.environ.get("STUDYVAULT_AUTH_DISABLED", "false").lower() == "true",
        catalog_internal_url=os.environ.get("CATALOG_INTERNAL_URL", "http://catalog-service:8000"),
        search_internal_url=os.environ.get("SEARCH_INTERNAL_URL", "http://search-service:8000"),
        activity_internal_url=os.environ.get("ACTIVITY_INTERNAL_URL", "http://activity-service:8000"),
        internal_token=os.environ.get("STUDYVAULT_INTERNAL_TOKEN", "studyvault-internal-token-change-me"),
        file_max_upload_bytes=int(os.environ.get("FILE_MAX_UPLOAD_BYTES", "104857600")),
    )
