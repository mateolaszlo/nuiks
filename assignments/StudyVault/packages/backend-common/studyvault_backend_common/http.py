from __future__ import annotations

from typing import Any
import json

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


class ServiceClientError(RuntimeError):
    """Raised when a downstream StudyVault service call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        code: str | None = None,
        category: str | None = None,
        recoverable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.category = category
        self.recoverable = recoverable
        self.context = context or {}


class JsonServiceClient:
    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    @staticmethod
    def _build_service_error(method: str, url: str, response: httpx.Response) -> ServiceClientError:
        detail = response.text.strip()
        message = f"{method} {url} failed with status {response.status_code}"
        code = None
        category = None
        recoverable = None
        context: dict[str, Any] | None = None
        parsed_detail: str | None = None
        if detail:
            try:
                payload = json.loads(detail)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                payload_detail = payload.get("detail")
                if isinstance(payload_detail, str):
                    parsed_detail = payload_detail
                payload_code = payload.get("code")
                if isinstance(payload_code, str):
                    code = payload_code
                payload_category = payload.get("category")
                if isinstance(payload_category, str):
                    category = payload_category
                payload_recoverable = payload.get("recoverable")
                if isinstance(payload_recoverable, bool):
                    recoverable = payload_recoverable
                payload_context = payload.get("context")
                if isinstance(payload_context, dict):
                    context = payload_context
        if parsed_detail:
            detail = parsed_detail
        if detail:
            message = f"{message} {detail}"
        return ServiceClientError(
            message,
            status_code=response.status_code,
            detail=detail or None,
            code=code,
            category=category,
            recoverable=recoverable,
            context=context,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.25),
        retry=retry_if_exception_type((httpx.HTTPError, ServiceClientError)),
        reraise=True,
    )
    async def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        if internal_token:
            headers["x-internal-token"] = internal_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.is_error:
                raise self._build_service_error("POST", url, response)
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.25),
        retry=retry_if_exception_type((httpx.HTTPError, ServiceClientError)),
        reraise=True,
    )
    async def get_json(
        self,
        url: str,
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        if internal_token:
            headers["x-internal-token"] = internal_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=headers)
            if response.is_error:
                raise self._build_service_error("GET", url, response)
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.25),
        retry=retry_if_exception_type((httpx.HTTPError, ServiceClientError)),
        reraise=True,
    )
    async def patch_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        if internal_token:
            headers["x-internal-token"] = internal_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(url, json=payload, headers=headers)
            if response.is_error:
                raise self._build_service_error("PATCH", url, response)
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.25),
        retry=retry_if_exception_type((httpx.HTTPError, ServiceClientError)),
        reraise=True,
    )
    async def put_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        if internal_token:
            headers["x-internal-token"] = internal_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(url, json=payload, headers=headers)
            if response.is_error:
                raise self._build_service_error("PUT", url, response)
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.25),
        retry=retry_if_exception_type((httpx.HTTPError, ServiceClientError)),
        reraise=True,
    )
    async def delete_json(
        self,
        url: str,
        *,
        bearer_token: str | None = None,
        internal_token: str | None = None,
        query_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        if internal_token:
            headers["x-internal-token"] = internal_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(url, headers=headers, params=query_params)
            if response.is_error:
                raise self._build_service_error("DELETE", url, response)
            if not response.content:
                return {}
            return response.json()
