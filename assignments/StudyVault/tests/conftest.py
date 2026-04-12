from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "packages" / "backend-common"
SERVICE_ROOTS = {
    "catalog": ROOT / "apps" / "catalog-service",
    "search": ROOT / "apps" / "search-service",
    "activity": ROOT / "apps" / "activity-service",
    "file": ROOT / "apps" / "file-service",
    "purge": ROOT / "apps" / "purge-worker",
}


def _purge_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name)


def load_service_module(service_name: str, module_name: str = "app.main"):
    _purge_app_modules()
    common = str(COMMON_PATH)
    service_root = str(SERVICE_ROOTS[service_name])
    if common not in sys.path:
        sys.path.insert(0, common)
    if service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


@pytest.fixture(autouse=True)
def test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    env_values = {
        "KEYCLOAK_REALM": "studyvault",
        "KEYCLOAK_ISSUER_URL": "http://keycloak.test/realms/studyvault",
        "KEYCLOAK_JWKS_URL": "http://keycloak.test/realms/studyvault/protocol/openid-connect/certs",
        "KEYCLOAK_CLIENT_ID": "studyvault-frontend",
        "STUDYVAULT_AUTH_DISABLED": "true",
        "CATALOG_INTERNAL_URL": "http://catalog.test",
        "SEARCH_INTERNAL_URL": "http://search.test",
        "ACTIVITY_INTERNAL_URL": "http://activity.test",
        "FILE_INTERNAL_URL": "http://file.test",
        "STUDYVAULT_INTERNAL_TOKEN": "internal-test-token",
        "CATALOG_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SEARCH_MONGODB_URL": "mongodb://mongodb.test:27017",
        "ACTIVITY_MONGODB_URL": "mongodb://mongodb.test:27017",
        "FILE_S3_ENDPOINT": "http://minio.test:9000",
        "FILE_S3_ACCESS_KEY": "minioadmin",
        "FILE_S3_SECRET_KEY": "minioadmin",
        "FILE_S3_BUCKET": "studyvault-files-test",
        "STUDYVAULT_SKIP_APP_BOOTSTRAP": "true",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    yield

    _purge_app_modules()


if str(COMMON_PATH) not in sys.path:
    sys.path.insert(0, str(COMMON_PATH))
