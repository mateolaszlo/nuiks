from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


ErrorCategory = Literal["conflict", "validation", "not_found", "auth", "permission", "unavailable", "internal"]
ErrorContextValue = str | int | bool | None


class StudyVaultFieldError(BaseModel):
    field: str
    message: str


class StudyVaultErrorResponse(BaseModel):
    detail: str
    code: str
    category: ErrorCategory
    recoverable: bool
    context: dict[str, ErrorContextValue] | None = None
    field_errors: list[StudyVaultFieldError] = Field(default_factory=list)


class StudyVaultHTTPException(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        code: str,
        category: ErrorCategory,
        recoverable: bool = True,
        context: dict[str, ErrorContextValue] | None = None,
        field_errors: list[StudyVaultFieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.category = category
        self.recoverable = recoverable
        self.context = context
        self.field_errors = list(field_errors or [])


def api_error(
    *,
    status_code: int,
    detail: str,
    code: str,
    category: ErrorCategory,
    recoverable: bool = True,
    context: dict[str, ErrorContextValue] | None = None,
    field_errors: list[StudyVaultFieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> StudyVaultHTTPException:
    return StudyVaultHTTPException(
        status_code=status_code,
        detail=detail,
        code=code,
        category=category,
        recoverable=recoverable,
        context=context,
        field_errors=field_errors,
        headers=headers,
    )


def build_error_response(exc: HTTPException) -> StudyVaultErrorResponse:
    if isinstance(exc, StudyVaultHTTPException):
        return StudyVaultErrorResponse(
            detail=str(exc.detail),
            code=exc.code,
            category=exc.category,
            recoverable=exc.recoverable,
            context=exc.context,
            field_errors=exc.field_errors,
        )

    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    category = _default_category(exc.status_code)
    return StudyVaultErrorResponse(
        detail=detail,
        code=_default_code(exc.status_code, category),
        category=category,
        recoverable=exc.status_code < status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def handle_studyvault_http_exception(
        request: Request,
        call_next,
    ) -> JSONResponse:
        try:
            return await call_next(request)
        except StudyVaultHTTPException as exc:
            payload = build_error_response(exc)
            return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


def _default_category(status_code: int) -> ErrorCategory:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        return "auth" if status_code == status.HTTP_401_UNAUTHORIZED else "permission"
    if status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_CONTENT}:
        return "validation"
    if status_code == status.HTTP_409_CONFLICT:
        return "conflict"
    if status_code in {status.HTTP_502_BAD_GATEWAY, status.HTTP_503_SERVICE_UNAVAILABLE, status.HTTP_504_GATEWAY_TIMEOUT}:
        return "unavailable"
    return "internal"


def _default_code(status_code: int, category: ErrorCategory) -> str:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "unauthorized"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "forbidden"
    if status_code == status.HTTP_409_CONFLICT:
        return "conflict"
    if status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_CONTENT}:
        return "invalid_request"
    if category == "unavailable":
        return "service_unavailable"
    return "internal_error"
