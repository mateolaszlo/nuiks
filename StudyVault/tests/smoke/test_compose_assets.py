from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from studyvault_backend_common.versioning import derive_public_origin_and_hosts


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
        "purge-worker",
        "catalog-service",
        "search-service",
        "activity-service",
        "postgres",
        "mongodb",
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
    assert "FILE_INTERNAL_URL: http://file-service:8000" in result.stdout
    assert "PURGE_RUN_MODE: loop" in result.stdout
    assert "PURGE_INTERVAL_SECONDS: \"3600\"" in result.stdout
    assert "FILE_S3_ENDPOINT:" in result.stdout
    assert "FILE_S3_ACCESS_KEY:" in result.stdout
    assert "FILE_S3_SECRET_KEY:" in result.stdout
    assert "FILE_S3_BUCKET:" in result.stdout
    assert "FILE_S3_REGION: us-east-1" in result.stdout
    assert "KEYCLOAK_ADMIN_USERNAME: admin" in result.stdout
    assert "KEYCLOAK_ADMIN_PASSWORD: admin" in result.stdout
    assert "internal-demo-token" not in result.stdout


def test_docker_compose_local_minio_profile_exposes_optional_service() -> None:
    project_root = Path(__file__).resolve().parents[2]
    compose_file = project_root / "infra" / "docker" / "compose" / "docker-compose.yml"

    result = subprocess.run(
        ["docker", "compose", "--profile", "local-minio", "-f", str(compose_file), "config"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "minio:" in result.stdout
    assert "profiles:" in result.stdout
    assert "- local-minio" in result.stdout
    assert "FILE_S3_ENDPOINT:" in result.stdout


def test_internal_service_urls_match_trusted_host_allowlist() -> None:
    _, allowed_hosts = derive_public_origin_and_hosts("http://localhost:8080/realms/studyvault")

    assert "catalog-service:8000" in allowed_hosts
    assert "search-service:8000" in allowed_hosts
    assert "activity-service:8000" in allowed_hosts
    assert "file-service:8000" in allowed_hosts
    assert "keycloak:8080" in allowed_hosts


def test_metricbeat_config_uses_reduced_sampling_and_metricsets() -> None:
    project_root = Path(__file__).resolve().parents[2]
    metricbeat_config = project_root / "infra" / "observability" / "metricbeat.yml"
    contents = metricbeat_config.read_text()

    assert contents.count("period: 1m") == 2
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
    objects = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]
    dashboard_objects = [obj for obj in objects if obj.get("type") == "dashboard"]
    config_objects = [obj for obj in objects if obj.get("type") == "config"]
    dashboard_ids = {obj["id"] for obj in dashboard_objects}
    dashboard_titles = {
        _normalize_saved_object_title(obj["attributes"]["title"])
        for obj in dashboard_objects
        if obj.get("attributes", {}).get("title")
    }

    assert all(obj.get("type") != "index-pattern" for obj in objects)
    assert len(dashboard_objects) >= 6
    assert len(dashboard_ids) == len(dashboard_objects)
    assert len(config_objects) == 1
    assert config_objects[0].get("attributes", {}).get("theme:darkMode") == "enabled"
    assert "studyvault upload pipeline" in dashboard_titles
    assert "studyvault ops overview" in dashboard_titles
    assert "studyvault admin and auth" in dashboard_titles


def test_kibana_saved_objects_match_pinned_importer_version() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "infra" / "kibana" / "studyvault-observability.ndjson"
    objects = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]

    for obj in objects:
        if obj.get("type") not in {"search", "dashboard"}:
            continue
        assert obj.get("typeMigrationVersion") == "10.2.0"


def test_kibana_saved_searches_bind_runtime_data_views() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "infra" / "kibana" / "studyvault-observability.ndjson"
    objects = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]

    for obj in objects:
        if obj.get("type") != "search":
            continue
        search_source = json.loads(obj["attributes"]["kibanaSavedObjectMeta"]["searchSourceJSON"])
        assert search_source.get("indexRefName") == "kibanaSavedObjectMeta.searchSourceJSON.index"


def test_admin_auth_saved_searches_include_keycloak_auth_attempt_events() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "infra" / "kibana" / "studyvault-observability.ndjson"
    objects = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]

    admin_search = next(
        obj
        for obj in objects
        if obj.get("type") == "search" and obj.get("attributes", {}).get("title") == "StudyVault Admin"
    )
    auth_search = next(
        obj
        for obj in objects
        if obj.get("type") == "search" and obj.get("attributes", {}).get("title") == "StudyVault Auth"
    )
    admin_search_source = json.loads(admin_search["attributes"]["kibanaSavedObjectMeta"]["searchSourceJSON"])
    auth_attributes = auth_search["attributes"]
    auth_search_source = json.loads(auth_attributes["kibanaSavedObjectMeta"]["searchSourceJSON"])

    assert "admin_password_reset" in admin_search_source["query"]["query"]
    for event_name in ["auth_login", "auth_login_failed", "auth_register", "auth_register_failed"]:
        assert event_name in auth_search_source["query"]["query"]
    assert "username" in auth_attributes["columns"]
    assert "error" in auth_attributes["columns"]
    assert "client_ip" in auth_attributes["columns"]


def test_kibana_dashboard_objects_use_supported_time_fields() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bundle = project_root / "infra" / "kibana" / "studyvault-observability.ndjson"
    objects = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]

    for obj in objects:
        if obj.get("type") != "dashboard":
            continue
        attributes = obj.get("attributes", {})
        assert "timeRange" not in attributes
        assert attributes.get("timeFrom")
        assert attributes.get("timeTo")
        assert attributes.get("version") == 2


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
    assert '"protocolMapper": "oidc-audience-mapper"' in contents
    assert '"included.client.audience": "studyvault-frontend"' in contents
    assert "__STUDYVAULT_" not in contents


def test_keycloak_realm_enables_failed_auth_event_types() -> None:
    project_root = Path(__file__).resolve().parents[2]
    template = project_root / "infra" / "keycloak" / "studyvault-realm.template.json"
    contents = template.read_text()

    assert '"LOGIN"' in contents
    assert '"LOGIN_ERROR"' in contents
    assert '"REGISTER"' in contents
    assert '"REGISTER_ERROR"' in contents


def test_keycloak_seeded_users_keep_account_console_roles() -> None:
    project_root = Path(__file__).resolve().parents[2]
    template = project_root / "infra" / "keycloak" / "studyvault-realm.template.json"
    contents = template.read_text()

    assert '"clientRoles": {' in contents
    assert '"account": [' in contents
    assert '"manage-account"' in contents
    assert '"manage-account-links"' in contents
    assert '"view-profile"' in contents


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


def test_bootstrap_validates_saved_object_importer_compatibility() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bootstrap_script = project_root / "infra" / "scripts" / "bootstrap_kibana.py"
    contents = bootstrap_script.read_text()

    assert 'KIBANA_VERSION = "8.15.3"' in contents
    assert 'MAX_SAVED_OBJECT_TYPE_MIGRATION_VERSION = "10.2.0"' in contents
    assert "validate_saved_object_compatibility(export_path)" in contents
    assert "must not include index-pattern objects" in contents
    assert "missing-indexRefName" in contents
    assert "missing-timeFrom" in contents
    assert "missing-timeTo" in contents
    assert ":timeRange" in contents


def test_bootstrap_declares_runtime_data_views() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bootstrap_script = project_root / "infra" / "scripts" / "bootstrap_kibana.py"
    contents = bootstrap_script.read_text()

    assert '"id": "studyvault-logs"' in contents
    assert '"title": "studyvault-logs-*"' in contents
    assert '"id": "metricbeat"' in contents
    assert '"title": "metricbeat*"' in contents


def test_logstash_promotes_emitted_event_timestamp_to_index_timestamp() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contents = (project_root / "infra" / "observability" / "logstash.conf").read_text()

    assert 'match => ["event_timestamp", "ISO8601", "yyyy-MM-dd HH:mm:ss,SSS"]' in contents
    assert 'target => "@timestamp"' in contents
    assert 'replace => { "event_timestamp" => "%{@timestamp}" }' in contents


def test_bootstrap_declares_studyvault_log_field_mappings() -> None:
    project_root = Path(__file__).resolve().parents[2]
    bootstrap_script = project_root / "infra" / "scripts" / "bootstrap_kibana.py"
    contents = bootstrap_script.read_text()

    assert "STUDYVAULT_LOG_FIELD_MAPPINGS" in contents
    assert '"event_timestamp": {"type": "date"}' in contents
    assert '"location": {"type": "geo_point"}' in contents


def test_frontend_keycloak_uses_same_origin_default() -> None:
    project_root = Path(__file__).resolve().parents[2]
    auth_source = (project_root / "apps" / "frontend" / "src" / "auth" / "keycloak.ts").read_text()
    compose_contents = (project_root / "infra" / "docker" / "compose" / "docker-compose.yml").read_text()

    assert 'window.location.origin' in auth_source
    assert "http://localhost:8080" not in auth_source
    assert "VITE_KEYCLOAK_URL" not in compose_contents


def test_internal_fanout_is_not_exposed_through_gateway() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf.template").read_text()
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
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf.template").read_text()

    assert "map $http_cf_visitor $studyvault_cloudflare_proto" in nginx_contents
    assert '~*"https" https;' in nginx_contents
    assert 'map $http_x_forwarded_proto $studyvault_proxy_proto' in nginx_contents
    assert 'map "$studyvault_cloudflare_proto:$studyvault_proxy_proto" $studyvault_forwarded_proto' in nginx_contents
    assert "~^https: https;" in nginx_contents
    assert "~^:https$ https;" in nginx_contents
    assert "map $studyvault_forwarded_proto $studyvault_forwarded_port" in nginx_contents
    assert "https 443;" in nginx_contents
    assert "proxy_set_header X-Forwarded-Host $host;" in nginx_contents
    assert "proxy_set_header X-Forwarded-Port $studyvault_forwarded_port;" in nginx_contents


def test_logstash_preserves_request_observability_fields() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contents = (project_root / "infra" / "observability" / "logstash.conf").read_text()

    for field_name in [
        "route_template",
        "client_ip",
        "client_ip_source",
        "forwarded_for",
        "user_agent",
        "request_outcome",
        "request_content_length",
        "response_content_length",
        'target => "client_geo"',
    ]:
        assert field_name in contents


def test_logstash_drops_local_gateway_probe_noise() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contents = (project_root / "infra" / "observability" / "logstash.conf").read_text()

    assert '[service] == "gateway"' in contents
    assert '127\\.0\\.0\\.1' in contents
    assert '"Wget' in contents
    assert "drop {}" in contents


def test_gateway_cloudflare_real_ip_restore_is_configured() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf.template").read_text()
    realip_contents = (project_root / "infra" / "nginx" / "cloudflare-realip.conf").read_text()
    compose_contents = (project_root / "infra" / "docker" / "compose" / "docker-compose.yml").read_text()

    assert "include /etc/nginx/cloudflare-realip.conf;" in nginx_contents
    assert "real_ip_header CF-Connecting-IP;" in nginx_contents
    assert "real_ip_recursive on;" in nginx_contents
    assert "set_real_ip_from 127.0.0.1;" in realip_contents
    assert "set_real_ip_from ::1;" in realip_contents
    assert "set_real_ip_from 173.245.48.0/20;" in realip_contents
    assert "set_real_ip_from 103.21.244.0/22;" in realip_contents
    assert "set_real_ip_from 2400:cb00::/32;" in realip_contents
    assert "set_real_ip_from 2a06:98c0::/29;" in realip_contents
    assert "/etc/nginx/cloudflare-realip.conf:ro" in compose_contents


def test_gateway_browser_security_headers_are_configured() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf.template").read_text()
    silent_sso_html = (project_root / "apps" / "frontend" / "public" / "silent-check-sso.html").read_text()
    silent_sso_script = (project_root / "apps" / "frontend" / "public" / "silent-check-sso.js").read_text()

    assert "map $request_uri $studyvault_csp_header {" in nginx_contents
    assert """default "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'self'; frame-src 'self'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'";""" in nginx_contents
    assert """~^/(realms|resources|js)/ "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'self'; frame-src 'self'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'";""" in nginx_contents
    assert "add_header Content-Security-Policy $studyvault_csp_header always;" in nginx_contents
    assert "base-uri 'self';" in nginx_contents
    assert "object-src 'none';" in nginx_contents
    assert "form-action 'self';" in nginx_contents
    assert "frame-ancestors 'self';" in nginx_contents
    assert "frame-src 'self';" in nginx_contents
    assert "img-src 'self' data:;" in nginx_contents
    assert "font-src 'self' data:;" in nginx_contents
    assert "connect-src 'self';" in nginx_contents
    assert "script-src 'self';" in nginx_contents
    assert "style-src 'self' 'unsafe-inline'" in nginx_contents
    assert "script-src 'self' 'unsafe-inline';" in nginx_contents
    assert "style-src 'self' 'unsafe-inline'" in nginx_contents
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx_contents
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in nginx_contents
    assert 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;' in nginx_contents
    assert 'add_header Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=(), usb=()" always;' in nginx_contents
    assert "map $studyvault_forwarded_proto $studyvault_hsts_header" in nginx_contents
    assert 'https "max-age=31536000; includeSubDomains";' in nginx_contents
    assert "add_header Strict-Transport-Security $studyvault_hsts_header always;" in nginx_contents
    assert '<script src="/silent-check-sso.js"></script>' in silent_sso_html
    assert "parent.postMessage(location.href, location.origin);" in silent_sso_script
    assert "parent.postMessage(location.href, location.origin);" not in silent_sso_html


def test_gateway_rate_limiting_is_configured_for_abuse_prone_routes() -> None:
    project_root = Path(__file__).resolve().parents[2]
    nginx_contents = (project_root / "infra" / "nginx" / "nginx.conf.template").read_text()
    render_script = (project_root / "infra" / "nginx" / "render-nginx.sh").read_text()
    compose_contents = (project_root / "infra" / "docker" / "compose" / "docker-compose.yml").read_text()
    env_example = (project_root / ".env.example").read_text()

    assert "limit_req_zone $binary_remote_addr zone=studyvault_auth_rate:10m rate=${STUDYVAULT_AUTH_RATE};" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_auth_nav_rate:10m rate=${STUDYVAULT_AUTH_NAV_RATE};" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_upload_rate:10m rate=${STUDYVAULT_UPLOAD_RATE};" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_search_rate:10m rate=${STUDYVAULT_SEARCH_RATE};" in nginx_contents
    assert "limit_req_zone $binary_remote_addr zone=studyvault_admin_rate:10m rate=${STUDYVAULT_ADMIN_RATE};" in nginx_contents
    assert "limit_req_status 429;" in nginx_contents
    assert "location = /realms/studyvault/protocol/openid-connect/auth {" in nginx_contents
    assert "limit_req zone=studyvault_auth_nav_rate burst=${STUDYVAULT_AUTH_NAV_BURST} nodelay;" in nginx_contents
    assert "location = /realms/studyvault/protocol/openid-connect/token {" in nginx_contents
    assert "location ^~ /realms/studyvault/login-actions/ {" in nginx_contents
    assert "location ^~ /realms/studyvault/account/ {" in nginx_contents
    assert "location /realms/ {" in nginx_contents
    assert "location = /favicon.ico {" in nginx_contents
    assert "envsubst '${STUDYVAULT_AUTH_RATE} ${STUDYVAULT_AUTH_NAV_RATE} ${STUDYVAULT_UPLOAD_RATE} ${STUDYVAULT_SEARCH_RATE} ${STUDYVAULT_ADMIN_RATE}" in render_script
    assert "location /api/v1/files {" in nginx_contents
    assert "limit_req zone=studyvault_upload_rate burst=${STUDYVAULT_UPLOAD_BURST} nodelay;" in nginx_contents
    assert "location /api/v1/search {" in nginx_contents
    assert "limit_req zone=studyvault_search_rate burst=${STUDYVAULT_SEARCH_BURST} nodelay;" in nginx_contents
    assert "location ^~ /api/v1/admin/ {" in nginx_contents
    assert "limit_req zone=studyvault_admin_rate burst=${STUDYVAULT_ADMIN_BURST} nodelay;" in nginx_contents
    assert "command: [\"/bin/sh\", \"/app/render-nginx.sh\"]" in compose_contents
    assert "STUDYVAULT_ADMIN_RATE: ${STUDYVAULT_ADMIN_RATE:-120r/m}" in compose_contents
    assert "STUDYVAULT_ADMIN_BURST: ${STUDYVAULT_ADMIN_BURST:-30}" in compose_contents
    assert "STUDYVAULT_AUTH_RATE=360r/m" in env_example
    assert "STUDYVAULT_AUTH_BURST=90" in env_example
    assert "STUDYVAULT_AUTH_NAV_RATE=480r/m" in env_example
    assert "STUDYVAULT_AUTH_NAV_BURST=180" in env_example
    assert "STUDYVAULT_UPLOAD_RATE=50r/m" in env_example
    assert "STUDYVAULT_UPLOAD_BURST=50" in env_example
    assert "STUDYVAULT_SEARCH_RATE=80r/m" in env_example
    assert "STUDYVAULT_SEARCH_BURST=50" in env_example
    assert "STUDYVAULT_ADMIN_RATE=150r/m" in env_example
    assert "STUDYVAULT_ADMIN_BURST=50" in env_example


def test_postgres_initdb_uses_env_driven_keycloak_db_credentials() -> None:
    project_root = Path(__file__).resolve().parents[2]
    init_script = project_root / "infra" / "postgres" / "initdb" / "01-create-keycloak-db.sh"
    contents = init_script.read_text()

    assert "KEYCLOAK_DB_USER" in contents
    assert "KEYCLOAK_DB_PASSWORD" in contents
    assert "PASSWORD 'keycloak'" not in contents
