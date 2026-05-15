from __future__ import annotations

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "storage-usage-worker"
    catalog_internal_url: str = "http://catalog-service:8000"
    elasticsearch_url: str = "http://elasticsearch:9200"
    internal_token: str = "studyvault-internal-token-change-me"
    storage_usage_index_prefix: str = "studyvault-storage"
    storage_usage_run_mode: str = "once"
    storage_usage_interval_seconds: int = 3600

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    @model_validator(mode="after")
    def validate_schedule(self) -> "Settings":
        if self.storage_usage_run_mode not in {"once", "loop"}:
            raise ValueError("STORAGE_USAGE_RUN_MODE must be either 'once' or 'loop'")
        if self.storage_usage_run_mode == "loop" and self.storage_usage_interval_seconds <= 0:
            raise ValueError("STORAGE_USAGE_INTERVAL_SECONDS must be a positive integer in loop mode")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        catalog_internal_url=os.environ.get("CATALOG_INTERNAL_URL", "http://catalog-service:8000"),
        elasticsearch_url=os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200"),
        internal_token=os.environ.get("STUDYVAULT_INTERNAL_TOKEN", "studyvault-internal-token-change-me"),
        storage_usage_index_prefix=os.environ.get("STORAGE_USAGE_INDEX_PREFIX", "studyvault-storage"),
        storage_usage_run_mode=os.environ.get("STORAGE_USAGE_RUN_MODE", "once"),
        storage_usage_interval_seconds=int(os.environ.get("STORAGE_USAGE_INTERVAL_SECONDS", "3600")),
    )
