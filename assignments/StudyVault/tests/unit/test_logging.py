import io
import json
import logging

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


def test_should_log_request_for_failures() -> None:
    assert should_log_request(path="/api/catalog/files", status_code=500, duration_ms=12.0) is True


def test_should_not_log_fast_success_health_check() -> None:
    assert should_log_request(path="/health", status_code=200, duration_ms=3.0) is False


def test_should_not_log_fast_success_regular_request() -> None:
    assert should_log_request(path="/api/catalog/files", status_code=200, duration_ms=24.0) is False


def test_should_log_slow_success_request() -> None:
    assert should_log_request(path="/api/search", status_code=200, duration_ms=275.0) is True
