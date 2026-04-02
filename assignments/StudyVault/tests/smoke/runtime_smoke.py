from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "infra" / "docker" / "compose" / "docker-compose.yml"


def compose_command(*args: str) -> list[str]:
    base = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    probe = subprocess.run(base, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    if probe.returncode == 0:
        return base
    if "permission denied" in (probe.stderr or "").lower():
        return ["sudo", *base]
    return base


def wait_for_compose_health(timeout_seconds: int = 300) -> None:
    deadline = time.time() + timeout_seconds
    ps_command = compose_command("ps", "--format", "json")
    while time.time() < deadline:
        result = subprocess.run(
            ps_command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            time.sleep(2)
            continue

        payload = result.stdout.strip()
        if payload.startswith("["):
            services = json.loads(payload)
        else:
            services = [json.loads(line) for line in payload.splitlines() if line.strip()]
        required = {
            "frontend",
            "gateway",
            "keycloak",
            "catalog-service",
            "search-service",
            "activity-service",
            "file-service",
            "postgres",
            "mongodb",
            "minio",
            "elasticsearch",
            "logstash",
            "kibana",
            "metricbeat",
        }
        statuses = {service["Service"]: service.get("Health", "") for service in services}
        if required.issubset(statuses.keys()) and all(statuses[name] == "healthy" for name in required):
            return
        time.sleep(5)

    raise RuntimeError("Compose services did not become healthy within the timeout")


def assert_http_ok(url: str) -> None:
    with urllib.request.urlopen(url, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")


def assert_keycloak_database_exists() -> None:
    command = compose_command(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "studyvault",
        "-d",
        "studyvault",
        "-tAc",
        "SELECT 1 FROM pg_database WHERE datname = 'keycloak';",
    )
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "1":
        raise RuntimeError("Keycloak PostgreSQL database was not created")


def assert_kibana_data_view(title: str) -> None:
    url = (
        "http://127.0.0.1:5601/api/saved_objects/_find"
        f"?type=index-pattern&search_fields=title&search={quote(title, safe='*')}"
    )
    request = urllib.request.Request(url, headers={"kbn-xsrf": "true"})
    deadline = time.time() + 120
    while time.time() < deadline:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("saved_objects"):
            return
        time.sleep(3)
    raise RuntimeError(f"Kibana data view for {title} was not created")


def normalize_saved_object_title(title: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in title)
    parts = normalized.split()
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts)


def assert_kibana_dashboard(title: str) -> None:
    expected_title = normalize_saved_object_title(title)
    url = "http://127.0.0.1:5601/api/saved_objects/_find?type=dashboard&per_page=100"
    request = urllib.request.Request(url, headers={"kbn-xsrf": "true"})
    deadline = time.time() + 120
    while time.time() < deadline:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        saved_objects = payload.get("saved_objects", [])
        for saved_object in saved_objects:
            saved_object_title = saved_object.get("attributes", {}).get("title", "")
            if normalize_saved_object_title(saved_object_title) == expected_title:
                return
        time.sleep(3)
    raise RuntimeError(f"Kibana dashboard {title} was not created")


def assert_backend_logs_indexed() -> None:
    query = quote('service:(file-service OR catalog-service OR search-service OR activity-service)', safe="():*")
    url = f"http://127.0.0.1:9200/studyvault-logs-*/_search?q={query}&size=5&sort=@timestamp:desc"
    deadline = time.time() + 120
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hits = payload.get("hits", {}).get("hits", [])
        if hits:
            return
        time.sleep(3)
    raise RuntimeError("Backend service logs with structured fields were not indexed")


def assert_metricbeat_documents_indexed() -> None:
    url = "http://127.0.0.1:9200/metricbeat*/_search?size=5&sort=@timestamp:desc"
    deadline = time.time() + 360
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hits = payload.get("hits", {}).get("hits", [])
        if hits:
            return
        time.sleep(3)
    raise RuntimeError("Metricbeat documents were not indexed")


def assert_ilm_policy_exists(name: str) -> None:
    url = f"http://127.0.0.1:9200/_ilm/policy/{name}"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if name not in payload:
        raise RuntimeError(f"ILM policy {name} was not created")


def main() -> None:
    wait_for_compose_health()
    assert_http_ok("http://127.0.0.1:8080/")
    assert_http_ok("http://127.0.0.1:8080/realms/studyvault/.well-known/openid-configuration")
    assert_keycloak_database_exists()
    assert_http_ok("http://127.0.0.1:9200/_cluster/health")
    assert_http_ok("http://127.0.0.1:5601/api/status")
    assert_ilm_policy_exists("studyvault-logs-policy")
    assert_ilm_policy_exists("metricbeat-policy")
    assert_kibana_data_view("studyvault-logs-*")
    assert_kibana_data_view("metricbeat*")
    for title in [
        "StudyVault Executive Overview",
        "StudyVault Request Health",
        "StudyVault Upload Pipeline",
        "StudyVault Search Analytics",
        "StudyVault Errors and Failures",
        "StudyVault Infrastructure Metrics",
    ]:
        assert_kibana_dashboard(title)
    assert_backend_logs_indexed()
    assert_metricbeat_documents_indexed()


if __name__ == "__main__":
    main()
