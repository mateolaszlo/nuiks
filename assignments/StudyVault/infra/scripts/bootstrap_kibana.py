from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


KIBANA_URL = "http://kibana:5601"
ELASTICSEARCH_URL = "http://elasticsearch:9200"
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
                }
            },
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Failed to create StudyVault log index template: HTTP {status}")


def ensure_metricbeat_index_template() -> None:
    status, _ = request_json(
        ELASTICSEARCH_URL,
        "/_index_template/metricbeat-retention",
        method="PUT",
        payload={
            "index_patterns": ["metricbeat*"],
            "priority": 500,
            "data_stream": {},
            "template": {
                "settings": {
                    "index.lifecycle.name": "metricbeat-policy",
                }
            },
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Failed to create Metricbeat index template: HTTP {status}")


def ensure_data_view(view_id: str, title: str, time_field: str) -> None:
    status, payload = request_json(KIBANA_URL, f"/api/saved_objects/index-pattern/{view_id}")
    if status == 200:
        attributes = payload.get("attributes", {})
        if attributes.get("title") == title and attributes.get("timeFieldName") == time_field:
            return
        status, _ = request_json(
            KIBANA_URL,
            f"/api/saved_objects/index-pattern/{view_id}",
            method="PUT",
            payload={
                "attributes": {
                    "title": title,
                    "timeFieldName": time_field,
                }
            },
        )
        if status not in {200, 201}:
            raise RuntimeError(f"Failed to update Kibana data view for {title}: HTTP {status}")
        return

    params = urllib.parse.urlencode(
        {
            "type": "index-pattern",
            "search_fields": "title",
            "search": title,
        }
    )
    status, payload = request_json(KIBANA_URL, f"/api/saved_objects/_find?{params}")
    if status == 200:
        for saved_object in payload.get("saved_objects", []):
            if saved_object.get("attributes", {}).get("title") == title:
                return

    status, _ = request_json(
        KIBANA_URL,
        f"/api/saved_objects/index-pattern/{view_id}",
        method="POST",
        payload={
            "attributes": {
                "title": title,
                "timeFieldName": time_field,
            }
        },
    )
    if status not in {200, 201, 409}:
        raise RuntimeError(f"Failed to create Kibana data view for {title}: HTTP {status}")


def main() -> None:
    wait_for_elasticsearch()
    for policy_name, payload in ILM_POLICIES.items():
        ensure_ilm_policy(policy_name, payload)
    ensure_log_index_template()
    ensure_metricbeat_index_template()
    wait_for_kibana()
    for view in DATA_VIEWS:
        ensure_data_view(view["id"], view["title"], view["time_field"])


if __name__ == "__main__":
    main()
