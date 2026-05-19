from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = PROJECT_ROOT / "apps" / "frontend" / "src"

FORBIDDEN_BACKEND_ENV_NAMES = [
    "KEYCLOAK_DB_PASSWORD",
    "KC_BOOTSTRAP_ADMIN_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "STUDYVAULT_INTERNAL_TOKEN",
    "FILE_S3_SECRET_KEY",
    "CATALOG_DATABASE_URL",
    "SEARCH_MONGODB_URL",
    "ACTIVITY_MONGODB_URL",
]

FORBIDDEN_INTERNAL_HOSTNAMES = [
    "catalog-service",
    "file-service",
    "search-service",
    "activity-service",
    "minio",
    "postgres",
    "mongodb",
    "mongo",
]


def _frontend_source_files() -> list[Path]:
    return sorted([
        *FRONTEND_SRC.rglob("*.ts"),
        *FRONTEND_SRC.rglob("*.tsx"),
    ])


def test_frontend_import_meta_env_usage_is_limited_to_public_vite_keys() -> None:
    env_pattern = re.compile(r"import\.meta\.env\.([A-Z0-9_]+)")
    matches: list[str] = []

    for path in _frontend_source_files():
        matches.extend(env_pattern.findall(path.read_text()))

    assert matches
    assert all(name.startswith("VITE_") for name in matches)


def test_frontend_source_avoids_backend_secret_names_and_internal_hosts() -> None:
    for path in _frontend_source_files():
        contents = path.read_text()
        for name in FORBIDDEN_BACKEND_ENV_NAMES:
            assert name not in contents, f"{name} leaked into {path.relative_to(PROJECT_ROOT)}"
        for hostname in FORBIDDEN_INTERNAL_HOSTNAMES:
            assert hostname not in contents, f"{hostname} leaked into {path.relative_to(PROJECT_ROOT)}"


def test_frontend_source_keeps_auth_and_network_patterns_constrained() -> None:
    auth_source = (FRONTEND_SRC / "auth" / "keycloak.ts").read_text()
    api_source = (FRONTEND_SRC / "api" / "client.ts").read_text()
    all_source = "\n".join(path.read_text() for path in _frontend_source_files())

    assert "localStorage" not in all_source
    assert "sessionStorage" not in all_source
    assert "document.cookie" not in all_source
    assert "X-Internal-Token" not in all_source
    assert "console.log" not in all_source
    assert "console.error" not in all_source
    assert "apiKey" not in all_source
    assert "secret" not in all_source

    assert auth_source.count("import.meta.env.VITE_") == 3
    assert "window.location.origin" in auth_source
    assert 'new URL(`/realms/${keycloakRealm}/account/`, keycloakBaseUrl)' in auth_source
    assert "http://catalog-service" not in auth_source
    assert "http://file-service" not in auth_source

    assert 'headers.set("Authorization", `Bearer ${token}`);' in api_source
    assert 'xhr.setRequestHeader("Authorization", `Bearer ${token}`);' in api_source
    assert "http://" not in api_source
    assert "https://" not in api_source
    assert "fetch(input" in api_source
    assert 'xhr.open("POST", "/api/v1/files")' in api_source
    assert 'fetch(`/api/v1/files/${fileId}/download`' in api_source


def test_frontend_source_uses_only_gateway_and_keycloak_relative_paths() -> None:
    auth_source = (FRONTEND_SRC / "auth" / "keycloak.ts").read_text()
    api_source = (FRONTEND_SRC / "api" / "client.ts").read_text()

    api_paths = re.findall(r'"/api/v1/[^"]*"', api_source)

    assert api_paths
    assert all(path_literal.startswith('"/api/v1/') for path_literal in api_paths)
    assert '"/internal/' not in api_source
    assert '"/realms/' not in api_source
    assert '"/realms/' in auth_source or "`/realms/" in auth_source
