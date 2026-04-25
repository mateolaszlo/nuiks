from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def _normalize_saved_object_title(title: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in title)
    parts = normalized.split()
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts)


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
        "keycloak-realm-render",
    ]:
        assert f"{service_name}:" in result.stdout
    assert "KC_DB: postgres" in result.stdout
    assert "KC_DB_URL_DATABASE: keycloak" in result.stdout
    assert "KC_DB_USERNAME: keycloak" in result.stdout
    assert "KC_DB_PASSWORD: keycloak" not in result.stdout
    assert "KEYCLOAK_DB_USER: keycloak" in result.stdout
    assert "KEYCLOAK_DB_PASSWORD: studyvault-keycloak-db-password-change-me" in result.stdout
    assert "/docker-entrypoint-initdb.d" in result.stdout
    assert "metricbeat.yml" in result.stdout
    assert "/usr/share/metricbeat/metricbeat.yml" in result.stdout
    assert "bootstrap_kibana.py" in result.stdout
    assert "/app/kibana" in result.stdout
    assert "render_studyvault_realm.sh" in result.stdout
    assert "studyvault-realm.template.json" in result.stdout
    assert "- /bin/sh" in result.stdout
    assert "start-dev" in result.stdout
    assert "keycloak-import-data" in result.stdout
    assert "CATALOG_INTERNAL_URL: http://catalog-service:8000" in result.stdout
    assert "SEARCH_INTERNAL_URL: http://search-service:8000" in result.stdout
    assert "ACTIVITY_INTERNAL_URL: http://activity-service:8000" in result.stdout
    assert "KEYCLOAK_ADMIN_USERNAME: admin" in result.stdout
    assert "KEYCLOAK_ADMIN_PASSWORD: admin" in result.stdout
    assert "internal-demo-token" not in result.stdout


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
    objects = [json.loads(line) for line in bundle.read_text().splitlines()]
    dashboard_objects = [obj for obj in objects if obj.get("type") == "dashboard"]
    dashboard_ids = {obj["id"] for obj in dashboard_objects}
    dashboard_titles = {
        _normalize_saved_object_title(obj["attributes"]["title"])
        for obj in dashboard_objects
        if obj.get("attributes", {}).get("title")
    }
    data_view_titles = {
        obj["attributes"]["title"]
        for obj in objects
        if obj.get("type") == "index-pattern" and obj.get("attributes", {}).get("title")
    }

    assert "studyvault-logs-*" in data_view_titles
    assert "metricbeat*" in data_view_titles
    assert len(dashboard_objects) == 6
    assert len(dashboard_ids) == len(dashboard_objects)
    assert "studyvault executive overview" in dashboard_titles
    assert "studyvault search analytics2" in dashboard_titles


def test_keycloak_realm_template_renders_public_base_url() -> None:
    project_root = Path(__file__).resolve().parents[2]
    render_script = project_root / "infra" / "scripts" / "render_studyvault_realm.sh"
    template = project_root / "infra" / "keycloak" / "studyvault-realm.template.json"

    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "studyvault-realm.json"
        result = subprocess.run(
            ["sh", str(render_script), str(template), str(output)],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "STUDYVAULT_PUBLIC_BASE_URL": "https://studyvault.example.com"},
        )

        assert result.returncode == 0, result.stderr
        contents = output.read_text()

    assert "https://studyvault.example.com/*" in contents
    assert '"webOrigins": [' in contents
    assert "__STUDYVAULT_" not in contents


def test_bootstrap_declares_float_metricbeat_docker_cpu_fields() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bootstrap_script = project_root / "infra" / "scripts" / "bootstrap_kibana.py"
    contents = bootstrap_script.read_text()

    for field_name in [
        '"usage": {"type": "float"}',
        '"pct": {"type": "float"}',
        "studyvault-metricbeat-overrides",
        "reset_metricbeat_data_streams",
    ]:
        assert field_name in contents


def test_frontend_keycloak_uses_same_origin_default() -> None:
    project_root = Path(__file__).resolve().parents[2]
    auth_source = (project_root / "apps" / "frontend" / "src" / "auth" / "keycloak.ts").read_text()
    compose_contents = (project_root / "infra" / "docker" / "compose" / "docker-compose.yml").read_text()

    assert 'window.location.origin' in auth_source
    assert "http://localhost:8080" not in auth_source
    assert "VITE_KEYCLOAK_URL" not in compose_contents


def test_internal_fanout_is_not_exposed_through_gateway() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf").read_text()
    downstream_contents = (project_root / "apps" / "file-service" / "app" / "services" / "downstream.py").read_text()
    config_contents = (project_root / "apps" / "file-service" / "app" / "core" / "config.py").read_text()

    assert "location /internal/catalog/" not in nginx_contents
    assert "location /internal/search/" not in nginx_contents
    assert "location /internal/activity/" not in nginx_contents
    assert "base_url" not in downstream_contents
    assert "catalog_url" in downstream_contents
    assert "search_url" in downstream_contents
    assert "activity_url" in downstream_contents
    assert "STUDYVAULT_INTERNAL_BASE_URL" not in config_contents
    assert "CATALOG_INTERNAL_URL" in config_contents or "catalog_internal_url" in config_contents


def test_gateway_cloudflare_proxy_handling_preserves_https_scheme() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf").read_text()

    assert "map $http_cf_visitor $studyvault_cloudflare_proto" in nginx_contents
    assert '~*"https" https;' in nginx_contents
    assert 'map $http_x_forwarded_proto $studyvault_proxy_proto' in nginx_contents
    assert 'map "$studyvault_cloudflare_proto:$studyvault_proxy_proto" $studyvault_forwarded_proto' in nginx_contents
    assert "~^https: https;" in nginx_contents
    assert "~^:https$ https;" in nginx_contents
    assert "map $studyvault_forwarded_proto $studyvault_forwarded_port" in nginx_contents
    assert "https 443;" in nginx_contents
    assert "proxy_set_header X-Forwarded-Port $studyvault_forwarded_port;" in nginx_contents


def test_gateway_browser_security_headers_are_configured() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf").read_text()

    assert 'add_header Content-Security-Policy "default-src \'self\';' in nginx_contents
    assert "base-uri 'self';" in nginx_contents
    assert "object-src 'none';" in nginx_contents
    assert "form-action 'self';" in nginx_contents
    assert "frame-ancestors 'self';" in nginx_contents
    assert "frame-src 'self';" in nginx_contents
    assert "img-src 'self' data:;" in nginx_contents
    assert "font-src 'self' data:;" in nginx_contents
    assert "connect-src 'self';" in nginx_contents
    assert "script-src 'self' 'unsafe-inline';" in nginx_contents
    assert "style-src 'self' 'unsafe-inline'" in nginx_contents
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx_contents
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in nginx_contents
    assert 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;' in nginx_contents
    assert 'add_header Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=(), usb=()" always;' in nginx_contents
    assert "map $studyvault_forwarded_proto $studyvault_hsts_header" in nginx_contents
    assert 'https "max-age=31536000; includeSubDomains";' in nginx_contents
    assert "add_header Strict-Transport-Security $studyvault_hsts_header always;" in nginx_contents


def test_gateway_rate_limiting_is_configured_for_abuse_prone_routes() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf").read_text()

    assert "limit_req_zone $binary_remote_addr zone=studyvault_auth_rate:10m rate=30r/m;" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_upload_rate:10m rate=10r/m;" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_search_rate:10m rate=60r/m;" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_admin_rate:10m rate=20r/m;" in nginx_contents
    assert "limit_req_status 429;" in nginx_contents
    assert "location /realms/ {" in nginx_contents
    assert "limit_req zone=studyvault_auth_rate burst=10 nodelay;" in nginx_contents
    assert "location /api/v1/files {" in nginx_contents
    assert "limit_req zone=studyvault_upload_rate burst=5 nodelay;" in nginx_contents
    assert "location /api/v1/search {" in nginx_contents
    assert "limit_req zone=studyvault_search_rate burst=20 nodelay;" in nginx_contents
    assert "location ^~ /api/v1/admin/ {" in nginx_contents
    assert "limit_req zone=studyvault_admin_rate burst=10 nodelay;" in nginx_contents


def test_postgres_initdb_uses_env_driven_keycloak_db_credentials() -> None:
    project_root = Path(__file__).resolve().parents[2]
    init_script = project_root / "infra" / "postgres" / "initdb" / "01-create-keycloak-db.sh"
    contents = init_script.read_text()

    assert "KEYCLOAK_DB_USER" in contents
    assert "KEYCLOAK_DB_PASSWORD" in contents
    assert "PASSWORD 'keycloak'" not in contents
