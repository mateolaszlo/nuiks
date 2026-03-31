from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from pydantic import BaseModel

from .models import AuthenticatedUser


security = HTTPBearer(auto_error=False)


class AuthSettings(BaseModel):
    issuer: str
    audience: str
    jwks_url: str
    auth_disabled: bool = False


class JwksCache:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    async def get(self, jwks_url: str) -> dict[str, Any]:
        if jwks_url in self._cache:
            return self._cache[jwks_url]
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            payload = response.json()
            self._cache[jwks_url] = payload
            return payload


@lru_cache(maxsize=1)
def get_jwks_cache() -> JwksCache:
    return JwksCache()


def _build_user(claims: dict[str, Any], token: str | None = None) -> AuthenticatedUser:
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return AuthenticatedUser(
        subject=claims["sub"],
        email=claims.get("email"),
        username=claims.get("preferred_username"),
        roles=roles,
        token=token,
    )


def build_auth_dependency(settings_provider: Callable[[], AuthSettings]) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> AuthenticatedUser:
        settings = settings_provider()
        if settings.auth_disabled:
            return AuthenticatedUser(
                subject="test-user",
                email="test@example.com",
                username="test-user",
                roles=["user"],
                token="disabled-auth-token",
            )

        if credentials is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

        token = credentials.credentials
        unverified_header = jwt.get_unverified_header(token)
        jwks = await get_jwks_cache().get(settings.jwks_url)
        keys = jwks.get("keys", [])
        key = next((candidate for candidate in keys if candidate.get("kid") == unverified_header.get("kid")), None)
        if key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown signing key")

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[unverified_header.get("alg", "RS256")],
                audience=settings.audience,
                issuer=settings.issuer,
            )
        except Exception as exc:  # pragma: no cover - exact library exception is not important
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

        return _build_user(claims, token)

    return dependency


AuthenticatedUserDependency = Annotated[AuthenticatedUser, Depends]
