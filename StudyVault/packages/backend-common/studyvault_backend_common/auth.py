from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from pydantic import BaseModel

from .errors import api_error
from .logging import bind_authenticated_user, get_logger
from .models import AuthenticatedUser


security = HTTPBearer(auto_error=False)
ALLOWED_JWT_ALGORITHMS = ("RS256",)
DEFAULT_PUBLIC_TOKEN_AUDIENCE = "studyvault-frontend"
logger = get_logger(__name__)


class AuthSettings(BaseModel):
    issuer: str
    audience: str | None = None
    client_id: str | None = None
    jwks_url: str
    auth_disabled: bool = False


def resolve_public_token_audience(
    configured_audience: str | None,
    *,
    fallback_client_id: str | None = None,
) -> str:
    return configured_audience or fallback_client_id or DEFAULT_PUBLIC_TOKEN_AUDIENCE


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
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise api_error(
            status_code=401,
            detail="Invalid token",
            code="invalid_token",
            category="auth",
        )
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return AuthenticatedUser(
        subject=subject,
        email=claims.get("email"),
        username=claims.get("preferred_username"),
        roles=roles,
        token=token,
    )


def _normalize_audience_values(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, (list, tuple)):
        return [candidate for candidate in value if isinstance(candidate, str) and candidate]
    return []


def _log_public_token_rejection(
    *,
    reason: str,
    issuer: str | None,
    audience: Any,
    authorized_party: Any,
    token_kid: Any,
) -> None:
    logger.warning(
        "public token rejected",
        event_name="public_token_rejected",
        event_category="auth",
        reason=reason,
        issuer=issuer,
        audience=audience,
        authorized_party=authorized_party,
        token_kid=token_kid,
        status="rejected",
    )


def build_auth_dependency(settings_provider: Callable[[], AuthSettings]) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> AuthenticatedUser:
        settings = settings_provider()
        if settings.auth_disabled:
            user = AuthenticatedUser(
                subject="test-user",
                email="test@example.com",
                username="test-user",
                roles=["user"],
                token="disabled-auth-token",
            )
            bind_authenticated_user(user_id=user.subject, username=user.username, email=user.email)
            return user

        if not settings.audience:
            raise RuntimeError("JWT audience must be configured when auth is enabled")

        if credentials is None:
            raise api_error(
                status_code=401,
                detail="Missing bearer token",
                code="missing_bearer_token",
                category="auth",
            )

        token = credentials.credentials
        unverified_header: dict[str, Any] | None = None
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:  # pragma: no cover - exact library exception is not important
            _log_public_token_rejection(
                reason="malformed_header",
                issuer=None,
                audience=None,
                authorized_party=None,
                token_kid=None,
            )
            raise api_error(
                status_code=401,
                detail="Invalid token",
                code="invalid_token",
                category="auth",
            ) from exc
        if unverified_header.get("alg") not in ALLOWED_JWT_ALGORITHMS:
            _log_public_token_rejection(
                reason="invalid_algorithm",
                issuer=None,
                audience=None,
                authorized_party=None,
                token_kid=unverified_header.get("kid"),
            )
            raise api_error(
                status_code=401,
                detail="Invalid token",
                code="invalid_token",
                category="auth",
            )

        jwks = await get_jwks_cache().get(settings.jwks_url)
        keys = jwks.get("keys", [])
        key = next((candidate for candidate in keys if candidate.get("kid") == unverified_header.get("kid")), None)
        if key is None:
            _log_public_token_rejection(
                reason="unknown_signing_key",
                issuer=None,
                audience=None,
                authorized_party=None,
                token_kid=unverified_header.get("kid"),
            )
            raise api_error(
                status_code=401,
                detail="Unknown signing key",
                code="unknown_signing_key",
                category="auth",
            )

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_JWT_ALGORITHMS),
                options={"verify_aud": False, "verify_iss": False},
            )
        except Exception as exc:  # pragma: no cover - exact library exception is not important
            _log_public_token_rejection(
                reason="decode_failed",
                issuer=None,
                audience=None,
                authorized_party=None,
                token_kid=unverified_header.get("kid"),
            )
            raise api_error(
                status_code=401,
                detail="Invalid token",
                code="invalid_token",
                category="auth",
            ) from exc

        claims_issuer = claims.get("iss")
        if claims_issuer != settings.issuer:
            _log_public_token_rejection(
                reason="issuer_mismatch",
                issuer=claims_issuer if isinstance(claims_issuer, str) else None,
                audience=claims.get("aud"),
                authorized_party=claims.get("azp"),
                token_kid=unverified_header.get("kid"),
            )
            raise api_error(
                status_code=401,
                detail="Invalid token",
                code="invalid_token",
                category="auth",
            )

        accepted_audiences = {settings.audience}
        if settings.client_id:
            accepted_audiences.add(settings.client_id)
        token_audiences = set(_normalize_audience_values(claims.get("aud")))
        authorized_party = claims.get("azp")
        if not (
            token_audiences.intersection(accepted_audiences)
            or (isinstance(authorized_party, str) and authorized_party in accepted_audiences)
        ):
            _log_public_token_rejection(
                reason="audience_mismatch",
                issuer=claims_issuer,
                audience=claims.get("aud"),
                authorized_party=authorized_party,
                token_kid=unverified_header.get("kid"),
            )
            raise api_error(
                status_code=401,
                detail="Invalid token",
                code="invalid_token",
                category="auth",
            )

        user = _build_user(claims, token)
        bind_authenticated_user(user_id=user.subject, username=user.username, email=user.email)
        return user

    return dependency


AuthenticatedUserDependency = Annotated[AuthenticatedUser, Depends]
