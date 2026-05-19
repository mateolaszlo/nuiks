from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIST_ROOT = PROJECT_ROOT / "apps" / "frontend" / "dist"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

SECRET_ENV_KEYS = [
    "KEYCLOAK_DB_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "KC_BOOTSTRAP_ADMIN_PASSWORD",
    "STUDYVAULT_INTERNAL_TOKEN",
    "FILE_S3_SECRET_KEY",
    "CATALOG_DATABASE_URL",
    "SEARCH_MONGODB_URL",
    "ACTIVITY_MONGODB_URL",
]

FORBIDDEN_INTERNAL_HOSTS = [
    "catalog-service",
    "file-service",
    "search-service",
    "activity-service",
    "minio",
    "postgres",
    "mongodb",
]


def _read_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _forbidden_markers() -> list[str]:
    env_values = _read_env_values()
    markers = list(SECRET_ENV_KEYS)
    for key in SECRET_ENV_KEYS:
        value = env_values.get(key)
        if value and not value.startswith("${") and len(value) >= 8:
            markers.append(value)
    markers.extend(FORBIDDEN_INTERNAL_HOSTS)
    return markers


def main() -> int:
    if not DIST_ROOT.exists():
        print(f"dist directory not found: {DIST_ROOT}", file=sys.stderr)
        return 1

    bundle_paths = sorted([
        *DIST_ROOT.rglob("*.html"),
        *DIST_ROOT.rglob("*.js"),
    ])
    forbidden = _forbidden_markers()
    failures: list[str] = []

    for path in bundle_paths:
        contents = path.read_text()
        for marker in forbidden:
            if marker in contents:
                failures.append(f"{path.relative_to(PROJECT_ROOT)} contains forbidden marker: {marker}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print("frontend dist scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
