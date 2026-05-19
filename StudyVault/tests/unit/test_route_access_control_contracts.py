from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from tests.conftest import load_service_module


class FakeJwksCache:
    async def get(self, jwks_url: str) -> dict[str, Any]:
        return {"keys": [{"kid": "test-kid", "alg": "RS256", "kty": "RSA"}]}


def _get_route_dependency(service_name: str, path: str, method: str):
    module = load_service_module(service_name, module_name="app.api.routes")
    if service_name == "activity":
        router = module.build_public_router(object(), object())
    else:
        router = module.build_public_router(object())

    for route in router.routes:
        if getattr(route, "path", None) != path or method.upper() not in getattr(route, "methods", set()):
            continue
        for dependency in route.dependant.dependencies:
            if dependency.name == "user":
                return dependency.call
    raise AssertionError(f"missing auth dependency for {service_name} {method} {path}")


def _get_internal_token_dependency(service_name: str):
    module = load_service_module(service_name, module_name="app.api.routes")
    router = module.build_internal_router(object())
    for route in router.routes:
        if not str(getattr(route, "path", "")).startswith("/internal/"):
            continue
        if not route.dependant.dependencies:
            continue
        dependency = route.dependant.dependencies[0].call
        if dependency is not None:
            return dependency
    raise AssertionError(f"missing internal token dependency for {service_name}")


def _configure_wrong_audience_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "false")
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "iss": "http://keycloak.test/realms/studyvault",
            "aud": "account",
            "azp": "account-console",
            "email": "demo@example.com",
            "preferred_username": "demo",
            "realm_access": {"roles": ["user"]},
        },
    )


@pytest.mark.parametrize(
    ("service_name", "path", "method"),
    [
        ("catalog", "/catalog/files", "GET"),
        ("search", "/search", "GET"),
        ("activity", "/activity/me", "GET"),
        ("file", "/files", "POST"),
    ],
)
def test_public_service_routes_reject_missing_bearer_tokens(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    path: str,
    method: str,
) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "false")
    dependency = _get_route_dependency(service_name, path, method)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=None))

    assert exc.value.status_code == 401
    assert getattr(exc.value, "code", None) == "missing_bearer_token"


@pytest.mark.parametrize(
    ("service_name", "path", "method"),
    [
        ("catalog", "/catalog/files", "GET"),
        ("search", "/search", "GET"),
        ("activity", "/activity/me", "GET"),
        ("file", "/files", "POST"),
    ],
)
def test_public_service_routes_reject_wrong_audience_tokens(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    path: str,
    method: str,
) -> None:
    _configure_wrong_audience_claims(monkeypatch)
    dependency = _get_route_dependency(service_name, path, method)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "wrong-audience-token"})()))

    assert exc.value.status_code == 401
    assert getattr(exc.value, "code", None) == "invalid_token"


@pytest.mark.parametrize("service_name", ["catalog", "search", "activity", "file"])
def test_internal_route_dependencies_reject_browser_bearer_only_requests(
    service_name: str,
) -> None:
    dependency = _get_internal_token_dependency(service_name)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(x_internal_token=None))

    assert exc.value.status_code == 403


@pytest.mark.parametrize("service_name", ["catalog", "search", "activity", "file"])
def test_internal_route_dependencies_reject_wrong_internal_tokens(
    service_name: str,
) -> None:
    dependency = _get_internal_token_dependency(service_name)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(x_internal_token="wrong-token"))

    assert exc.value.status_code == 403


def test_admin_routes_require_bearer_token_before_role_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYVAULT_AUTH_DISABLED", "false")
    dependency = _get_route_dependency("activity", "/admin/users", "GET")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=None))

    assert exc.value.status_code == 401
    assert getattr(exc.value, "code", None) == "missing_bearer_token"
