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
    assert "bootstrap_kibana.py" in result.stdout
    assert "/app/kibana" in result.stdout


def test_metricbeat_config_uses_reduced_sampling_and_metricsets() -> None:
    project_root = Path(__file__).resolve().parents[2]
    metricbeat_config = project_root / "infra" / "observability" / "metricbeat.yml"
    contents = metricbeat_config.read_text()

    assert "period: 5m" in contents
    assert "- process" not in contents
    assert "- process_summary" not in contents
    assert "- network" not in contents
    assert "- load" not in contents
    assert "- diskio" not in contents
    assert "- info" not in contents


def test_kibana_saved_object_bundle_exists() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "infra" / "kibana" / "studyvault-observability.ndjson"

    assert bundle.exists()
    assert "StudyVault Executive Overview" in bundle.read_text()
