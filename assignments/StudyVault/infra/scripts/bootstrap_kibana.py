from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


KIBANA_URL = "http://kibana:5601"
DATA_VIEWS = [
    {
        "id": "studyvault-logs",
        "title": "studyvault-logs-*",
        "time_field": "@timestamp",
    },
    {
        "id": "metricbeat",
        "title": "metricbeat-*",
        "time_field": "@timestamp",
    },
]


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{KIBANA_URL}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "kbn-xsrf": "true",
        },
    )
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
            status, payload = request_json("/api/status")
            if status == 200 and payload.get("status", {}).get("overall", {}).get("level") in {"available", "degraded"}:
                return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("Kibana did not become ready in time")


def ensure_data_view(view_id: str, title: str, time_field: str) -> None:
    params = urllib.parse.urlencode(
        {
            "type": "index-pattern",
            "search_fields": "title",
            "search": title,
        }
    )
    status, payload = request_json(f"/api/saved_objects/_find?{params}")
    if status == 200:
        for saved_object in payload.get("saved_objects", []):
            if saved_object.get("attributes", {}).get("title") == title:
                return

    status, _ = request_json(
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
    wait_for_kibana()
    for view in DATA_VIEWS:
        ensure_data_view(view["id"], view["title"], view["time_field"])


if __name__ == "__main__":
    main()
