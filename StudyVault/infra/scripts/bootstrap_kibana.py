from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


KIBANA_URL = "http://kibana:5601"
ELASTICSEARCH_URL = "http://elasticsearch:9200"
KIBANA_VERSION = "8.15.3"
MAX_SAVED_OBJECT_TYPE_MIGRATION_VERSION = "10.4.0"
DASHBOARD_EXPORT_DIR = Path("/app/kibana")
DATA_VIEWS = [
    {
        "id": "studyvault-logs",
        "title": "studyvault-logs-*",
        "time_field": "@timestamp",
    },
    {
        "id": "metricbeat",
        "title": "metricbeat*",
        "time_field": "@timestamp",
    },
    {
        "id": "studyvault-storage",
        "title": "studyvault-storage-*",
        "time_field": "@timestamp",
    },
]
ILM_POLICIES = {
    "studyvault-logs-policy": {
        "policy": {
            "phases": {
                "hot": {"actions": {}},
                "delete": {"min_age": "7d", "actions": {"delete": {}}},
            }
        }
    },
    "metricbeat-policy": {
        "policy": {
            "phases": {
                "hot": {"actions": {}},
                "delete": {"min_age": "3d", "actions": {"delete": {}}},
            }
        }
    },
}
STUDYVAULT_LOG_FIELD_MAPPINGS = {
    "event_timestamp": {"type": "date"},
    "client_geo": {
        "properties": {
            "geo": {
                "properties": {
                    "location": {"type": "geo_point"},
                }
            }
        }
    },
}
METRICBEAT_FLOAT_FIELDS = {
    "container": {
        "properties": {
            "cpu": {
                "properties": {
                    "usage": {"type": "float"},
                }
            },
            "memory": {
                "properties": {
                    "usage": {"type": "float"},
                }
            },
        }
    },
    "docker": {
        "properties": {
            "cpu": {
                "properties": {
                    "kernel": {
                        "properties": {
                            "pct": {"type": "float"},
                            "norm": {"properties": {"pct": {"type": "float"}}},
                        }
                    },
                    "system": {
                        "properties": {
                            "pct": {"type": "float"},
                            "norm": {"properties": {"pct": {"type": "float"}}},
                        }
                    },
                    "total": {
                        "properties": {
                            "pct": {"type": "float"},
                            "norm": {"properties": {"pct": {"type": "float"}}},
                        }
                    },
                    "user": {
                        "properties": {
                            "pct": {"type": "float"},
                            "norm": {"properties": {"pct": {"type": "float"}}},
                        }
                    },
                }
            }
        }
    },
}
SAVED_OBJECT_EXPORTS = [
    DASHBOARD_EXPORT_DIR / "studyvault-observability.ndjson",
]


def _parse_version_parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def validate_saved_object_compatibility(export_path: Path) -> None:
    incompatible_objects: list[tuple[str, str, str]] = []
    invalid_dashboards: list[str] = []
    invalid_searches: list[str] = []
    invalid_index_patterns: list[str] = []
    for line in export_path.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if "exportedCount" in payload and "missingReferences" in payload:
            continue
        object_type = payload.get("type")
        object_id = payload.get("id", "unknown-id")
        if object_type == "index-pattern":
            invalid_index_patterns.append(object_id)
            continue
        if object_type not in {"search", "dashboard"}:
            continue
        type_migration_version = payload.get("typeMigrationVersion")
        if not isinstance(type_migration_version, str):
            continue
        if _parse_version_parts(type_migration_version) > _parse_version_parts(
            MAX_SAVED_OBJECT_TYPE_MIGRATION_VERSION
        ):
            incompatible_objects.append((object_type, object_id, type_migration_version))
        if object_type == "dashboard":
            attributes = payload.get("attributes")
            if not isinstance(attributes, dict):
                invalid_dashboards.append(f"{object_id}:missing-attributes")
                continue
            if "timeRange" in attributes:
                invalid_dashboards.append(f"{object_id}:timeRange")
            if "timeFrom" not in attributes:
                invalid_dashboards.append(f"{object_id}:missing-timeFrom")
            if "timeTo" not in attributes:
                invalid_dashboards.append(f"{object_id}:missing-timeTo")
            if attributes.get("version") != 2:
                invalid_dashboards.append(f"{object_id}:version")
        if object_type == "search":
            attributes = payload.get("attributes")
            if not isinstance(attributes, dict):
                invalid_searches.append(f"{object_id}:missing-attributes")
                continue
            search_source = attributes.get("kibanaSavedObjectMeta", {}).get("searchSourceJSON")
            if not isinstance(search_source, str):
                invalid_searches.append(f"{object_id}:missing-searchSourceJSON")
                continue
            try:
                parsed_search_source = json.loads(search_source)
            except json.JSONDecodeError:
                invalid_searches.append(f"{object_id}:invalid-searchSourceJSON")
                continue
            if parsed_search_source.get("indexRefName") != "kibanaSavedObjectMeta.searchSourceJSON.index":
                invalid_searches.append(f"{object_id}:missing-indexRefName")

    if incompatible_objects:
        details = ", ".join(
            f"{object_type}:{object_id}@{version}"
            for object_type, object_id, version in incompatible_objects
        )
        raise RuntimeError(
            "Saved object bundle is incompatible with the pinned Kibana version "
            f"{KIBANA_VERSION}: found typeMigrationVersion newer than "
            f"{MAX_SAVED_OBJECT_TYPE_MIGRATION_VERSION} ({details})"
        )
    if invalid_index_patterns:
        details = ", ".join(invalid_index_patterns)
        raise RuntimeError(
            "Saved object bundle must not include index-pattern objects because data views "
            f"are provisioned separately by bootstrap ({details})"
        )
    if invalid_searches:
        details = ", ".join(invalid_searches)
        raise RuntimeError(
            "Saved object bundle contains search objects incompatible with the pinned "
            f"Kibana version {KIBANA_VERSION}: expected searchSourceJSON.indexRefName "
            f"to bind the runtime-created data view ({details})"
        )
    if invalid_dashboards:
        details = ", ".join(invalid_dashboards)
        raise RuntimeError(
            "Saved object bundle contains dashboard attributes incompatible with the "
            f"pinned Kibana version {KIBANA_VERSION}: expected timeFrom/timeTo and "
            f"version=2 with no timeRange ({details})"
        )


def request_json(
    base_url: str,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
        },
    )
    if base_url == KIBANA_URL:
        request.add_header("kbn-xsrf", "true")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body else {}
        return exc.code, payload


def wait_for_kibana(timeout_seconds: int = 300) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, payload = request_json(KIBANA_URL, "/api/status")
            if status == 200 and payload.get("status", {}).get("overall", {}).get("level") in {"available", "degraded"}:
                return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("Kibana did not become ready in time")


def wait_for_elasticsearch(timeout_seconds: int = 300) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, _ = request_json(ELASTICSEARCH_URL, "/_cluster/health")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("Elasticsearch did not become ready in time")


def ensure_ilm_policy(policy_name: str, payload: dict) -> None:
    status, _ = request_json(
        ELASTICSEARCH_URL,
        f"/_ilm/policy/{policy_name}",
        method="PUT",
        payload=payload,
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Failed to create ILM policy {policy_name}: HTTP {status}")


def ensure_log_index_template() -> None:
    status, _ = request_json(
        ELASTICSEARCH_URL,
        "/_index_template/studyvault-logs-retention",
        method="PUT",
        payload={
            "index_patterns": ["studyvault-logs-*"],
            "priority": 500,
            "template": {
                "settings": {
                    "index.lifecycle.name": "studyvault-logs-policy",
                },
                "mappings": {
                    "properties": STUDYVAULT_LOG_FIELD_MAPPINGS,
                },
            },
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Failed to create StudyVault log index template: HTTP {status}")


def ensure_metricbeat_index_template() -> None:
    status, _ = request_json(
        ELASTICSEARCH_URL,
        "/_index_template/studyvault-metricbeat-overrides",
        method="PUT",
        payload={
            "index_patterns": ["metricbeat*"],
            "priority": 1000,
            "data_stream": {},
            "template": {
                "settings": {
                    "index.lifecycle.name": "metricbeat-policy",
                },
                "mappings": {
                    "properties": METRICBEAT_FLOAT_FIELDS,
                },
            },
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Failed to create Metricbeat index template: HTTP {status}")


def reset_metricbeat_data_streams() -> None:
    status, payload = request_json(ELASTICSEARCH_URL, "/_data_stream/metricbeat*")
    if status == 404:
        return
    if status != 200:
        raise RuntimeError(f"Failed to inspect Metricbeat data streams: HTTP {status}")

    for data_stream in payload.get("data_streams", []):
        name = data_stream.get("name")
        if not name:
            continue
        delete_status, _ = request_json(
            ELASTICSEARCH_URL,
            f"/_data_stream/{name}",
            method="DELETE",
        )
        if delete_status not in {200, 204}:
            raise RuntimeError(f"Failed to reset Metricbeat data stream {name}: HTTP {delete_status}")


def ensure_data_view(view_id: str, title: str, time_field: str) -> None:
    status, payload = request_json(KIBANA_URL, f"/api/data_views/data_view/{view_id}")
    if status == 200:
        status, _ = request_json(
            KIBANA_URL,
            f"/api/data_views/data_view/{view_id}",
            method="DELETE",
        )
        if status not in {200, 204}:
            raise RuntimeError(f"Failed to replace Kibana data view for {title}: HTTP {status}")

    status, _ = request_json(
        KIBANA_URL,
        "/api/data_views/data_view",
        method="POST",
        payload={
            "data_view": {
                "id": view_id,
                "title": title,
                "timeFieldName": time_field,
                "name": title,
            },
            "override": True,
            "refresh_fields": True,
        },
    )
    if status not in {200, 201, 409}:
        raise RuntimeError(f"Failed to create Kibana data view for {title}: HTTP {status}")


def import_saved_objects(export_path: Path) -> None:
    if not export_path.exists():
        raise RuntimeError(f"Saved object export not found: {export_path}")
    validate_saved_object_compatibility(export_path)

    boundary = f"----studyvault-kibana-{uuid4().hex}"
    file_bytes = export_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{export_path.name}"\r\n'
                "Content-Type: application/x-ndjson\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        f"{KIBANA_URL}/api/saved_objects/_import?overwrite=true",
        data=body,
        method="POST",
        headers={
            "kbn-xsrf": "true",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"Failed to import Kibana saved objects from {export_path.name}: HTTP {exc.code} {body}") from exc

    if payload.get("success") is not True or payload.get("errors"):
        raise RuntimeError(f"Failed to import Kibana saved objects from {export_path.name}: {payload}")


def main() -> None:
    wait_for_elasticsearch()
    for policy_name, payload in ILM_POLICIES.items():
        ensure_ilm_policy(policy_name, payload)
    ensure_log_index_template()
    ensure_metricbeat_index_template()
    reset_metricbeat_data_streams()
    wait_for_kibana()
    for view in DATA_VIEWS:
        ensure_data_view(view["id"], view["title"], view["time_field"])
    for export_path in SAVED_OBJECT_EXPORTS:
        import_saved_objects(export_path)


if __name__ == "__main__":
    main()
