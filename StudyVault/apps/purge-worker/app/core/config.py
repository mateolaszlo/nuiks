from __future__ import annotations

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "purge-worker"
    catalog_internal_url: str = "http://catalog-service:8000"
    file_internal_url: str = "http://file-service:8000"
    search_internal_url: str = "http://search-service:8000"
    internal_token: str = "studyvault-internal-token-change-me"
    purge_batch_size: int = 100
    purge_run_mode: str = "once"
    purge_interval_seconds: int = 86400

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    @model_validator(mode="after")
    def validate_schedule(self) -> "Settings":
        if self.purge_run_mode not in {"once", "loop"}:
            raise ValueError("PURGE_RUN_MODE must be either 'once' or 'loop'")
        if self.purge_run_mode == "loop" and self.purge_interval_seconds <= 0:
            raise ValueError("PURGE_INTERVAL_SECONDS must be a positive integer in loop mode")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        catalog_internal_url=os.environ.get("CATALOG_INTERNAL_URL", "http://catalog-service:8000"),
        file_internal_url=os.environ.get("FILE_INTERNAL_URL", "http://file-service:8000"),
        search_internal_url=os.environ.get("SEARCH_INTERNAL_URL", "http://search-service:8000"),
        internal_token=os.environ.get("STUDYVAULT_INTERNAL_TOKEN", "studyvault-internal-token-change-me"),
        purge_batch_size=int(os.environ.get("PURGE_BATCH_SIZE", "100")),
        purge_run_mode=os.environ.get("PURGE_RUN_MODE", "once"),
        purge_interval_seconds=int(os.environ.get("PURGE_INTERVAL_SECONDS", "86400")),
    )
