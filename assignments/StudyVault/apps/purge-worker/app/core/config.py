from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "purge-worker"
    catalog_internal_url: str = "http://catalog-service:8000"
    file_internal_url: str = "http://file-service:8000"
    search_internal_url: str = "http://search-service:8000"
    internal_token: str = "studyvault-internal-token-change-me"
    purge_batch_size: int = 100

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        catalog_internal_url=os.environ.get("CATALOG_INTERNAL_URL", "http://catalog-service:8000"),
        file_internal_url=os.environ.get("FILE_INTERNAL_URL", "http://file-service:8000"),
        search_internal_url=os.environ.get("SEARCH_INTERNAL_URL", "http://search-service:8000"),
        internal_token=os.environ.get("STUDYVAULT_INTERNAL_TOKEN", "studyvault-internal-token-change-me"),
        purge_batch_size=int(os.environ.get("PURGE_BATCH_SIZE", "100")),
    )
