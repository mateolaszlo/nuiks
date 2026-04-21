from studyvault_backend_common.startup import retry_startup


def test_retry_startup_retries_until_success() -> None:
    attempts = {"count": 0}

    def flaky_operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("not ready")
        return "ok"

    assert retry_startup(flaky_operation, attempts=4, wait_seconds=0) == "ok"
    assert attempts["count"] == 3
