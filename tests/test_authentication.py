"""Tests for JWT authentication, expiration, rotation, and revocation."""

from datetime import timedelta

import httpx
import jwt
import pytest

from app.authentication.jwt_handler import create_access_token, create_token
from app.core.config import settings


@pytest.mark.asyncio
async def test_valid_registration_and_login(client: httpx.AsyncClient):
    """Verify standard user registration and login flow within a tenant."""
    reg_data = {
        "email": "newuser@acme.com",
        "password": "ValidPassword123!",
        "full_name": "New User",
        "role": "member",
    }
    reg_resp = await client.post("/acme/auth/register", json=reg_data)
    assert reg_resp.status_code == 201
    user_info = reg_resp.json()
    assert user_info["email"] == "newuser@acme.com"

    # Login with newly created credentials
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "newuser@acme.com", "password": "ValidPassword123!"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens


@pytest.mark.asyncio
async def test_invalid_login_credentials(client: httpx.AsyncClient):
    """Verify wrong password or non-existent user returns 401."""
    resp_wrong_pw = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "WrongPassword!"},
    )
    assert resp_wrong_pw.status_code == 401
    assert "Invalid email or password" in resp_wrong_pw.json()["detail"]

    resp_nonexistent = await client.post(
        "/acme/auth/login",
        json={"email": "ghost@acme.com", "password": "Password123!"},
    )
    assert resp_nonexistent.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwt_rejection(client: httpx.AsyncClient):
    """Verify expired JWT tokens are rejected with 401."""
    # Create an already expired token (-10 minutes)
    expired_token = create_access_token(
        user_id="user-123",
        tenant_slug="acme",
        tenant_id="any-id",
        expires_delta=timedelta(minutes=-10),
    )
    resp = await client.get("/acme/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "Token has expired" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_jwt_signature_rejection(client: httpx.AsyncClient):
    """Verify JWT signed with a bogus secret key is rejected."""
    tampered_token = jwt.encode(
        {"sub": "admin", "tenant_slug": "acme", "type": "access", "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        "wrong-secret-key-that-does-not-match",
        algorithm="HS256",
    )
    resp = await client.get("/acme/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_or_audience(client: httpx.AsyncClient):
    """Verify tokens with wrong issuer or audience are rejected."""
    bad_iss_token = create_token(
        claims={"sub": "user-1", "tenant_slug": "acme", "type": "access"},
        expires_delta=timedelta(minutes=15),
    )
    # Tamper payload
    decoded = jwt.decode(bad_iss_token, settings.JWT_SECRET_KEY, algorithms=["HS256"], options={"verify_signature": False})
    decoded["iss"] = "malicious-issuer"
    tampered = jwt.encode(decoded, settings.JWT_SECRET_KEY, algorithm="HS256")

    resp = await client.get("/acme/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_revocation(client: httpx.AsyncClient):
    """Verify refresh token rotation and revocation."""
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    first_refresh = tokens["refresh_token"]

    # 1. Rotate refresh token
    refresh_resp = await client.post(
        "/acme/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    second_refresh = new_tokens["refresh_token"]
    assert second_refresh != first_refresh

    # 2. Attempt to reuse old refresh token -> MUST FAIL (401)
    reused_resp = await client.post(
        "/acme/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert reused_resp.status_code == 401
    assert "revoked" in reused_resp.json()["detail"].lower()

    # 3. Test logout revokes token
    logout_resp = await client.post(
        "/acme/auth/logout",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        json={"refresh_token": second_refresh},
    )
    assert logout_resp.status_code == 200

    # 4. Attempt to refresh with logged-out token -> MUST FAIL
    post_logout = await client.post(
        "/acme/auth/refresh",
        json={"refresh_token": second_refresh},
    )
    assert post_logout.status_code == 401
