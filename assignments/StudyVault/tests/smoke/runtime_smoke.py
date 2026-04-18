from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "infra" / "docker" / "compose" / "docker-compose.yml"
KIBANA_BUNDLE = PROJECT_ROOT / "infra" / "kibana" / "studyvault-observability.ndjson"


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


def load_saved_object_bundle() -> list[dict]:
    return [json.loads(line) for line in KIBANA_BUNDLE.read_text().splitlines() if line.strip()]


def expected_dashboard_objects() -> list[dict]:
    return [obj for obj in load_saved_object_bundle() if obj.get("type") == "dashboard"]


def assert_kibana_data_view(view_id: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:5601/api/data_views/data_view/{view_id}",
        headers={"kbn-xsrf": "true"},
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("data_view", {}).get("id") == view_id:
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError(f"Kibana data view {view_id} was not created")


def assert_kibana_saved_object_exists(saved_object_type: str, saved_object_id: str, title: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:5601/api/saved_objects/{saved_object_type}/{saved_object_id}",
        headers={"kbn-xsrf": "true"},
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("id") == saved_object_id and payload.get("type") == saved_object_type:
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError(f"Kibana {saved_object_type} {title} ({saved_object_id}) was not created")


def trigger_backend_requests() -> None:
    urls = [
        "http://127.0.0.1:8080/api/v1/catalog/files",
        "http://127.0.0.1:8080/api/v1/search?q=smoke",
        "http://127.0.0.1:8080/api/v1/activity/me",
        "http://127.0.0.1:8080/api/v1/files/smoke/download",
    ]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=20):
                pass
        except urllib.error.HTTPError:
            # Auth errors are expected here and still produce structured request logs.
            pass


def assert_backend_logs_indexed() -> None:
    pending_services = {
        "file-service",
        "catalog-service",
        "search-service",
        "activity-service",
    }
    deadline = time.time() + 180
    while time.time() < deadline:
        resolved = set()
        for service in pending_services:
            query = quote(f"service:{service}", safe="():*")
            url = f"http://127.0.0.1:9200/studyvault-logs-*/_search?q={query}&size=1&sort=@timestamp:desc"
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            hits = payload.get("hits", {}).get("hits", [])
            if hits:
                resolved.add(service)
        pending_services -= resolved
        if not pending_services:
            return
        time.sleep(3)
    raise RuntimeError(
        "Backend service logs with structured fields were not indexed for: "
        + ", ".join(sorted(pending_services))
    )


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


def assert_metricbeat_field_is_float(field_path: str) -> None:
    url = "http://127.0.0.1:9200/metricbeat*/_mapping"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    for mapping in payload.values():
        properties = mapping.get("mappings", {}).get("properties", {})
        current = properties
        for part in field_path.split("."):
            current = current.get(part, {}).get("properties") if isinstance(current, dict) and part in current and "properties" in current.get(part, {}) else current.get(part)
            if current is None:
                break
        if isinstance(current, dict) and current.get("type") == "float":
            return

    raise RuntimeError(f"Metricbeat field {field_path} is not mapped as float")


def main() -> None:
    wait_for_compose_health()
    assert_http_ok("http://127.0.0.1:8080/")
    assert_http_ok("http://127.0.0.1:8080/realms/studyvault/.well-known/openid-configuration")
    assert_keycloak_database_exists()
    assert_http_ok("http://127.0.0.1:9200/_cluster/health")
    assert_http_ok("http://127.0.0.1:5601/api/status")
    assert_ilm_policy_exists("studyvault-logs-policy")
    assert_ilm_policy_exists("metricbeat-policy")
    assert_metricbeat_field_is_float("container.cpu.usage")
    assert_metricbeat_field_is_float("docker.cpu.total.norm.pct")
    assert_kibana_data_view("studyvault-logs")
    assert_kibana_data_view("metricbeat")
    for dashboard in expected_dashboard_objects():
        assert_kibana_saved_object_exists(
            "dashboard",
            dashboard["id"],
            dashboard.get("attributes", {}).get("title", dashboard["id"]),
        )
    trigger_backend_requests()
    assert_backend_logs_indexed()
    assert_metricbeat_documents_indexed()


if __name__ == "__main__":
    main()
