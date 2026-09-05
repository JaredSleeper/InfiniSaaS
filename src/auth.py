from __future__ import annotations

import time

import httpx
import jwt
from fastapi import Header, HTTPException

from src.config import settings

_jwks_cache: dict | None = None
_jwks_cached_at: float = 0.0
_JWKS_TTL = 3600


async def _fetch_jwks(force: bool = False) -> dict:
    global _jwks_cache, _jwks_cached_at
    if not force and _jwks_cache and time.monotonic() - _jwks_cached_at < _JWKS_TTL:
        return _jwks_cache
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(settings.clerk_jwks_url)
        r.raise_for_status()
        _jwks_cache = r.json()
        _jwks_cached_at = time.monotonic()
        return _jwks_cache


def _find_key(jwks: dict, kid: str | None) -> dict | None:
    return next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)


async def verify_token(token: str) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    jwk = _find_key(await _fetch_jwks(), kid)
    if jwk is None:
        jwk = _find_key(await _fetch_jwks(force=True), kid)
    if jwk is None:
        raise HTTPException(status_code=401, detail="Unknown signing key")
    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
    return jwt.decode(token, public_key, algorithms=["RS256"], options={"verify_aud": False})


async def current_user(authorization: str = Header(default="")) -> dict:
    """Dependency for dashboard API routes. No-op when Clerk isn't configured."""
    if not settings.auth_enabled:
        return {"user_id": "local", "email": ""}
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        payload = await verify_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
    email = (payload.get("email") or "").lower()
    user_id = payload.get("sub") or ""
    allowed = settings.allowed_email_set
    if allowed and email not in allowed and user_id.lower() not in allowed:
        raise HTTPException(status_code=403, detail="This account is not on the allowlist")
    return {"user_id": user_id, "email": email}
