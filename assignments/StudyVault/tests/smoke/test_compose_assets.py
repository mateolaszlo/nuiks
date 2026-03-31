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
    ]:
        assert f"{service_name}:" in result.stdout
