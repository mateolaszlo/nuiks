from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


T = TypeVar("T")


def retry_startup(operation: Callable[[], T], *, attempts: int = 20, wait_seconds: float = 1.0) -> T:
    @retry(
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(wait_seconds),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _runner() -> T:
        return operation()

    return _runner()
