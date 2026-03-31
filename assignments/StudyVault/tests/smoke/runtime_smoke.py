from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path


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


def main() -> None:
    wait_for_compose_health()
    assert_http_ok("http://127.0.0.1:8080/")
    assert_http_ok("http://127.0.0.1:8080/realms/studyvault/.well-known/openid-configuration")
    assert_http_ok("http://127.0.0.1:9200/_cluster/health")


if __name__ == "__main__":
    main()
