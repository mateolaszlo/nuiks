from studyvault_backend_common.logging import should_log_request


def test_should_log_request_for_failures() -> None:
    assert should_log_request(path="/api/catalog/files", status_code=500, duration_ms=12.0) is True


def test_should_not_log_fast_success_health_check() -> None:
    assert should_log_request(path="/health", status_code=200, duration_ms=3.0) is False


def test_should_not_log_fast_success_regular_request() -> None:
    assert should_log_request(path="/api/catalog/files", status_code=200, duration_ms=24.0) is False


def test_should_log_slow_success_request() -> None:
    assert should_log_request(path="/api/search", status_code=200, duration_ms=275.0) is True
