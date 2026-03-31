from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.base import BaseHTTPMiddleware


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def configure_logging(service_name: str) -> None:
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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


def install_request_logging(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
