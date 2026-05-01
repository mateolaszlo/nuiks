import io
import json
import logging
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import studyvault_backend_common.logging as logging_module
from studyvault_backend_common.logging import configure_logging, request_id_ctx, should_log_request


def test_configure_logging_injects_default_context_for_stdlib_logs() -> None:
    configure_logging("catalog-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream

    logging.getLogger("test.logger").info("plain stdlib log")

    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "plain stdlib log"
    assert payload["service"] == "catalog-service"
    assert payload["request_id"] == "-"


def test_configure_logging_injects_request_context_for_stdlib_logs() -> None:
    configure_logging("search-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream
    request_id_ctx.set("req-123")

    logging.getLogger("test.logger").warning("with request id")

    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "with request id"
    assert payload["service"] == "search-service"
    assert payload["request_id"] == "req-123"


def test_sanitize_request_id_preserves_valid_value() -> None:
    assert logging_module.sanitize_request_id("req-123.test_value") == "req-123.test_value"


def _find_request_completed_payload(stream: io.StringIO) -> dict[str, str]:
    payloads = []
    for line in stream.getvalue().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        message = payload.get("message")
        if isinstance(message, str) and message.startswith("{"):
            try:
                payload.update(json.loads(message))
            except json.JSONDecodeError:
                pass
        payloads.append(payload)
    return next(payload for payload in payloads if payload.get("event_name") == "request_completed")


def test_request_logging_replaces_invalid_request_id_in_logs_and_response(monkeypatch) -> None:
    configure_logging("gateway-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream
    monkeypatch.setattr(logging_module, "SLOW_REQUEST_THRESHOLD_MS", 0.0)

    app = FastAPI()
    logging_module.install_request_logging(app)

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get("/ok", headers={"x-request-id": "bad value"})

    payload = _find_request_completed_payload(stream)
    assert response.status_code == 200
    assert response.headers["x-request-id"] == payload["request_id"]
    UUID(response.headers["x-request-id"])


def test_request_logging_replaces_oversized_request_id(monkeypatch) -> None:
    configure_logging("gateway-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream
    monkeypatch.setattr(logging_module, "SLOW_REQUEST_THRESHOLD_MS", 0.0)

    app = FastAPI()
    logging_module.install_request_logging(app)

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get("/ok", headers={"x-request-id": "x" * 65})

    payload = _find_request_completed_payload(stream)
    assert response.status_code == 200
    assert response.headers["x-request-id"] == payload["request_id"]
    UUID(response.headers["x-request-id"])


def test_should_log_request_for_failures() -> None:
    assert should_log_request(path="/api/v1/catalog/files", status_code=500, duration_ms=12.0) is True


def test_should_not_log_fast_success_health_check() -> None:
    assert should_log_request(path="/health", status_code=200, duration_ms=3.0) is False


def test_should_not_log_fast_success_regular_request() -> None:
    assert should_log_request(path="/api/v1/catalog/files", status_code=200, duration_ms=24.0) is False


def test_should_log_slow_success_request() -> None:
    assert should_log_request(path="/api/v1/search", status_code=200, duration_ms=275.0) is True


def test_request_logging_emits_extended_request_context(monkeypatch) -> None:
    configure_logging("gateway-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream
    monkeypatch.setattr(logging_module, "SLOW_REQUEST_THRESHOLD_MS", 0.0)

    app = FastAPI()
    logging_module.install_request_logging(app)

    @app.post("/items/{item_id}")
    async def create_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    with TestClient(app) as client:
        response = client.post(
            "/items/123",
            headers={
                "x-forwarded-for": "198.51.100.10, 10.0.0.2",
                "user-agent": "pytest-agent/1.0",
                "content-type": "application/json",
                "host": "studyvault.local",
            },
            json={"name": "sample"},
        )

    payload = _find_request_completed_payload(stream)
    assert response.status_code == 200
    assert payload["route_template"] == "/items/{item_id}"
    assert payload["client_ip"] == "198.51.100.10"
    assert payload["client_ip_source"] == "x-forwarded-for"
    assert payload["forwarded_for"] == "198.51.100.10, 10.0.0.2"
    assert payload["user_agent"] == "pytest-agent/1.0"
    assert payload["host"] == "studyvault.local"
    assert payload["request_content_type"] == "application/json"
    assert payload["response_content_type"].startswith("application/json")
    assert payload["request_outcome"] == "success"
    assert payload["request_content_length"] > 0


def test_request_logging_marks_client_error_outcome(monkeypatch) -> None:
    configure_logging("gateway-service")
    root_logger = logging.getLogger()
    assert root_logger.handlers
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream
    monkeypatch.setattr(logging_module, "SLOW_REQUEST_THRESHOLD_MS", 0.0)

    app = FastAPI()
    logging_module.install_request_logging(app)

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="missing")

    with TestClient(app) as client:
        response = client.get("/missing")

    payload = _find_request_completed_payload(stream)
    assert response.status_code == 404
    assert payload["request_outcome"] == "client_error"
