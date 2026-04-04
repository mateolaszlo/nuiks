from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from studyvault_backend_common.auth import AuthSettings, build_auth_dependency
from studyvault_backend_common.models import STUDYVAULT_ADMIN_ROLE


class FakeJwksCache:
    async def get(self, jwks_url: str) -> dict[str, Any]:
        return {"keys": [{"kid": "test-kid", "alg": "RS256", "kty": "RSA"}]}


def test_auth_dependency_builds_user_from_valid_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    decode_calls: dict[str, Any] = {}
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    
    def fake_decode(*args, **kwargs):
        decode_calls["kwargs"] = kwargs
        return {
            "sub": "user-1",
            "email": "demo@example.com",
            "preferred_username": "demo",
            "realm_access": {"roles": ["user"]},
        }

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.decode", fake_decode)

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    app = FastAPI()

    @app.get("/me")
    async def me(user=Depends(dependency)):
        return user.model_dump()

    with TestClient(app) as client:
        response = client.get("/me", headers={"authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert response.json()["subject"] == "user-1"
    assert response.json()["roles"] == ["user"]
    assert decode_calls["kwargs"]["algorithms"] == ["RS256"]


def test_auth_dependency_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )

    def raise_decode(*args, **kwargs):
        raise ValueError("bad token")

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.decode", raise_decode)

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "bad-token"})()))

    assert exc.value.status_code == 401


def test_auth_dependency_rejects_malformed_token_header(monkeypatch: pytest.MonkeyPatch) -> None:
    jwks_called = False
    decode_called = False

    class TrackingJwksCache:
        async def get(self, jwks_url: str) -> dict[str, Any]:
            nonlocal jwks_called
            jwks_called = True
            return {"keys": []}

    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: TrackingJwksCache())

    def raise_bad_header(token: str) -> dict[str, Any]:
        raise ValueError("bad header")

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.get_unverified_header", raise_bad_header)

    def fake_decode(*args, **kwargs):
        nonlocal decode_called
        decode_called = True
        return {}

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.decode", fake_decode)

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "bad-token"})()))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"
    assert jwks_called is False
    assert decode_called is False


def test_auth_dependency_rejects_token_missing_subject_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.decode",
        lambda *args, **kwargs: {
            "email": "demo@example.com",
            "preferred_username": "demo",
            "realm_access": {"roles": ["user"]},
        },
    )

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "missing-sub-token"})()))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"


def test_auth_dependency_rejects_unexpected_header_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "HS256"},
    )

    decode_called = False

    def fake_decode(*args, **kwargs):
        nonlocal decode_called
        decode_called = True
        return {}

    monkeypatch.setattr("studyvault_backend_common.auth.jwt.decode", fake_decode)

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "bad-alg-token"})()))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"
    assert decode_called is False


def test_auth_dependency_preserves_admin_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.decode",
        lambda *args, **kwargs: {
            "sub": "admin-1",
            "email": "admin@example.com",
            "preferred_username": "admin",
            "realm_access": {"roles": ["user", STUDYVAULT_ADMIN_ROLE]},
        },
    )

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    user = asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "admin-token"})()))

    assert user.roles == ["user", STUDYVAULT_ADMIN_ROLE]
    assert user.is_admin is True


def test_auth_dependency_binds_identity_context(monkeypatch: pytest.MonkeyPatch) -> None:
    bound_values: dict[str, str | None] = {}
    monkeypatch.setattr("studyvault_backend_common.auth.get_jwks_cache", lambda: FakeJwksCache())
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.get_unverified_header",
        lambda token: {"kid": "test-kid", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.bind_authenticated_user",
        lambda **kwargs: bound_values.update(kwargs),
    )
    monkeypatch.setattr(
        "studyvault_backend_common.auth.jwt.decode",
        lambda *args, **kwargs: {
            "sub": "user-42",
            "email": "demo@example.com",
            "preferred_username": "demo",
            "realm_access": {"roles": ["user"]},
        },
    )

    dependency = build_auth_dependency(
        lambda: AuthSettings(
            issuer="http://issuer.test/realms/studyvault",
            jwks_url="http://issuer.test/certs",
            audience=None,
            auth_disabled=False,
        )
    )

    asyncio.run(dependency(credentials=type("Creds", (), {"credentials": "demo-token"})()))

    assert bound_values["user_id"] == "user-42"
    assert bound_values["username"] == "demo"
    assert bound_values["email"] == "demo@example.com"
