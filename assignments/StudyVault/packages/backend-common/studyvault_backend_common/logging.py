from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.base import BaseHTTPMiddleware


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
service_name_ctx: ContextVar[str] = ContextVar("service_name", default="unknown-service")
configured_service_name = "unknown-service"


def configure_logging(service_name: str) -> None:
    global configured_service_name
    configured_service_name = service_name
    service_name_ctx.set(service_name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(service)s %(request_id)s"
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str):
    return structlog.get_logger(name)


def bind_authenticated_user(
    *,
    user_id: str,
    username: str | None = None,
    email: str | None = None,
) -> None:
    values = {"user_id": user_id}
    if username:
        values["username"] = username
    if email:
        values["email"] = email
    structlog.contextvars.bind_contextvars(**values)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        structlog.contextvars.clear_contextvars()
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(
            service=configured_service_name,
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        logger = get_logger(__name__)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request failed",
                event_name="request_failed",
                event_category="request",
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request completed",
            event_name="request_completed",
            event_category="request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["x-request-id"] = request_id
        return response


def install_request_logging(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
