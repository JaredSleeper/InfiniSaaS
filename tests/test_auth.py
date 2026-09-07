from __future__ import annotations

import httpx
import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa

from src import auth
from src.config import settings
from src.main import app

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = {
    "keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1"}]
}


def _token(email: str, kid: str = "k1") -> str:
    return jwt.encode(
        {"sub": "user_1", "email": email}, KEY, algorithm="RS256", headers={"kid": kid}
    )


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example/.well-known/jwks.json")
    monkeypatch.setattr(settings, "allowed_emails", "jared@example.com")

    async def fake_jwks(force: bool = False) -> dict:
        return JWKS

    monkeypatch.setattr(auth, "_fetch_jwks", fake_jwks)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_requires_token(client):
    r = await client.get("/api/projects")
    assert r.status_code == 401
    assert (await client.get("/healthz")).status_code == 200


async def test_allowlisted_user_passes(client):
    r = await client.get(
        "/api/projects", headers={"Authorization": f"Bearer {_token('Jared@Example.com')}"}
    )
    assert r.status_code == 200


async def test_non_allowlisted_user_forbidden(client):
    r = await client.get(
        "/api/projects", headers={"Authorization": f"Bearer {_token('x@example.com')}"}
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "x@example.com is not on the allowlist"


async def test_missing_email_claim_names_user_id(client):
    tok = jwt.encode({"sub": "user_1"}, KEY, algorithm="RS256", headers={"kid": "k1"})
    r = await client.get("/api/projects", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "user_1" in r.json()["detail"]
    assert "no 'email' claim" in r.json()["detail"]


async def test_bad_signature_rejected(client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tok = jwt.encode(
        {"email": "jared@example.com"}, other, algorithm="RS256", headers={"kid": "k1"}
    )
    r = await client.get("/api/projects", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_ingest_stays_token_authed(client):
    r = await client.post("/api/v1/events", json={"events": [{"name": "visit"}]})
    assert r.status_code == 401


async def test_non_canonical_host_redirects_to_public_url(client, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://app.example.com")
    r = await client.get("/", headers={"host": "old.up.railway.app"})
    assert r.status_code == 308
    assert r.headers["location"] == "https://app.example.com/"
    # canonical host, health and API paths are untouched
    assert (await client.get("/", headers={"host": "app.example.com"})).status_code == 200
    assert (await client.get("/healthz", headers={"host": "old.up.railway.app"})).status_code == 200
    r = await client.get("/api/projects", headers={"host": "old.up.railway.app"})
    assert r.status_code == 401
