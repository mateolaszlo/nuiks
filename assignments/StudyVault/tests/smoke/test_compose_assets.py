from __future__ import annotations

import subprocess
from pathlib import Path


def test_docker_compose_config_contains_required_services() -> None:
    project_root = Path(__file__).resolve().parents[2]
    compose_file = project_root / "infra" / "docker" / "compose" / "docker-compose.yml"

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for service_name in [
        "frontend",
        "gateway",
        "keycloak",
        "file-service",
        "catalog-service",
        "search-service",
        "activity-service",
        "postgres",
        "mongodb",
        "minio",
        "elasticsearch",
        "logstash",
        "kibana",
        "metricbeat",
    ]:
        assert f"{service_name}:" in result.stdout
    assert "KC_DB: postgres" in result.stdout
    assert "KC_DB_URL_DATABASE: keycloak" in result.stdout
    assert "KC_DB_USERNAME: keycloak" in result.stdout
    assert "/docker-entrypoint-initdb.d" in result.stdout
    assert "metricbeat.yml" in result.stdout
    assert "/usr/share/metricbeat/metricbeat.yml" in result.stdout
