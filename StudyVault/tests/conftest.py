from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "packages" / "backend-common"
TEST_ENV_FILE = ROOT / ".env.test"
SERVICE_ROOTS = {
    "catalog": ROOT / "apps" / "catalog-service",
    "search": ROOT / "apps" / "search-service",
    "activity": ROOT / "apps" / "activity-service",
    "file": ROOT / "apps" / "file-service",
    "purge": ROOT / "apps" / "purge-worker",
    "storage_usage": ROOT / "apps" / "storage-usage-worker",
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


def load_test_env_values() -> dict[str, str]:
    env_values: dict[str, str] = {}
    for raw_line in TEST_ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if not key or not _:
            raise ValueError(f"Invalid env assignment in {TEST_ENV_FILE}: {raw_line!r}")
        env_values[key] = value
    env_values["STUDYVAULT_SKIP_APP_BOOTSTRAP"] = "true"
    return env_values


@pytest.fixture(autouse=True)
def test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in load_test_env_values().items():
        monkeypatch.setenv(key, value)

    yield

    _purge_app_modules()


if str(COMMON_PATH) not in sys.path:
    sys.path.insert(0, str(COMMON_PATH))


@pytest.fixture(autouse=True)
def version_public_testclient_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    original_request = TestClient.request

    def request_with_api_version_prefix(self, method, url, *args, **kwargs):
        headers = kwargs.get("headers")
        skip_rewrite = False
        if isinstance(headers, dict) and headers.get("x-test-raw-path") == "true":
            headers = dict(headers)
            headers.pop("x-test-raw-path", None)
            kwargs["headers"] = headers
            skip_rewrite = True

        if (
            not skip_rewrite
            and isinstance(url, str)
            and url.startswith("/api/")
            and not url.startswith("/api/v1/")
        ):
            url = url.replace("/api/", "/api/v1/", 1)

        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_api_version_prefix)
