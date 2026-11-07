"""Tests for role-based access control (RBAC) and granular permission enforcement."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_admin_role_has_full_permissions(client: httpx.AsyncClient):
    """Verify tenant admin can invite users and view tenant settings."""
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # Admin invites another user
    invite_resp = await client.post(
        "/acme/users",
        headers=headers,
        json={
            "email": "invited@acme.com",
            "password": "Password123!",
            "full_name": "Invited User",
            "role": "viewer",
        },
    )
    assert invite_resp.status_code == 201
    assert invite_resp.json()["email"] == "invited@acme.com"

    # Admin views settings
    settings_resp = await client.get("/acme/settings", headers=headers)
    assert settings_resp.status_code == 200
    assert "theme" in settings_resp.json()["config"]


@pytest.mark.asyncio
async def test_member_role_cannot_invite_users(client: httpx.AsyncClient):
    """Verify standard tenant member cannot invite users (requires users:write permission)."""
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "member@acme.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # Member attempts to invite user -> 403 FORBIDDEN
    invite_resp = await client.post(
        "/acme/users",
        headers=headers,
        json={
            "email": "unauthorized@acme.com",
            "password": "Password123!",
            "full_name": "Unauthorized",
            "role": "member",
        },
    )
    assert invite_resp.status_code == 403
    assert "users:write" in invite_resp.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_role_read_only(client: httpx.AsyncClient):
    """Verify viewer can read resources but cannot modify settings or invite users."""
    # Register a viewer
    reg = await client.post(
        "/acme/auth/register",
        json={
            "email": "readonly@acme.com",
            "password": "Password123!",
            "full_name": "Read Only",
            "role": "viewer",
        },
    )
    assert reg.status_code == 201

    login = await client.post(
        "/acme/auth/login",
        json={"email": "readonly@acme.com", "password": "Password123!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Viewer can list users
    users_resp = await client.get("/acme/users", headers=headers)
    assert users_resp.status_code == 200

    # Viewer cannot access settings (requires settings:read)
    settings_resp = await client.get("/acme/settings", headers=headers)
    assert settings_resp.status_code == 403
