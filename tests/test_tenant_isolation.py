"""Tests for strict multi-tenant isolation at application and database layers."""

import asyncio

import httpx
import pytest


@pytest.mark.asyncio
async def test_cross_tenant_token_rejection(client: httpx.AsyncClient):
    """Verify a valid token issued for Acme cannot access Globex endpoints."""
    # Login as Acme Admin
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    acme_token = login_resp.json()["access_token"]
    acme_auth_header = {"Authorization": f"Bearer {acme_token}"}

    # Verify Acme token works on Acme
    me_acme = await client.get("/acme/auth/me", headers=acme_auth_header)
    assert me_acme.status_code == 200
    assert me_acme.json()["email"] == "admin@acme.com"

    # Attempt to use Acme token on Globex -> MUST BE 403 FORBIDDEN
    cross_resp = await client.get("/globex/auth/me", headers=acme_auth_header)
    assert cross_resp.status_code == 403
    assert "Access denied" in cross_resp.json()["detail"]


@pytest.mark.asyncio
async def test_cross_tenant_resource_id_isolation(client: httpx.AsyncClient):
    """Verify resources created in Tenant A cannot be read or identified by Tenant B."""
    # 1. Login to Acme and create a resource
    acme_login = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    acme_headers = {"Authorization": f"Bearer {acme_login.json()['access_token']}"}

    create_acme_res = await client.post(
        "/acme/resources",
        headers=acme_headers,
        json={"title": "Acme Confidential", "content": "Internal Acme Financial Data"},
    )
    assert create_acme_res.status_code == 201
    acme_resource_id = create_acme_res.json()["id"]

    # 2. Login to Globex
    globex_login = await client.post(
        "/globex/auth/login",
        json={"email": "admin@globex.com", "password": "Password123!"},
    )
    globex_headers = {"Authorization": f"Bearer {globex_login.json()['access_token']}"}

    # 3. Globex attempts to access Acme's resource ID -> MUST BE 404 NOT FOUND
    globex_access = await client.get(
        f"/globex/resources/{acme_resource_id}",
        headers=globex_headers,
    )
    assert globex_access.status_code == 404
    assert "not found in this tenant" in globex_access.json()["detail"]


@pytest.mark.asyncio
async def test_database_queries_are_strictly_tenant_scoped(client: httpx.AsyncClient):
    """Verify listing resources returns strictly tenant-scoped data without leaking other tenants' records."""
    # Acme tokens
    acme_login = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    acme_headers = {"Authorization": f"Bearer {acme_login.json()['access_token']}"}

    # Globex tokens
    globex_login = await client.post(
        "/globex/auth/login",
        json={"email": "admin@globex.com", "password": "Password123!"},
    )
    globex_headers = {"Authorization": f"Bearer {globex_login.json()['access_token']}"}

    # Create 2 resources in Acme
    await client.post("/acme/resources", headers=acme_headers, json={"title": "A1", "content": "C1"})
    await client.post("/acme/resources", headers=acme_headers, json={"title": "A2", "content": "C2"})

    # Create 1 resource in Globex
    await client.post("/globex/resources", headers=globex_headers, json={"title": "G1", "content": "CG1"})

    # Fetch Acme list
    res_acme = await client.get("/acme/resources", headers=acme_headers)
    assert res_acme.status_code == 200
    acme_items = res_acme.json()
    assert len(acme_items) == 2
    assert all(item["title"].startswith("A") for item in acme_items)

    # Fetch Globex list
    res_globex = await client.get("/globex/resources", headers=globex_headers)
    assert res_globex.status_code == 200
    globex_items = res_globex.json()
    assert len(globex_items) == 1
    assert globex_items[0]["title"] == "G1"


@pytest.mark.asyncio
async def test_concurrent_requests_no_context_leakage(client: httpx.AsyncClient):
    """Verify simultaneous concurrent requests across tenants maintain strict isolated context."""
    acme_login = await client.post("/acme/auth/login", json={"email": "admin@acme.com", "password": "Password123!"})
    globex_login = await client.post("/globex/auth/login", json={"email": "admin@globex.com", "password": "Password123!"})

    acme_headers = {"Authorization": f"Bearer {acme_login.json()['access_token']}"}
    globex_headers = {"Authorization": f"Bearer {globex_login.json()['access_token']}"}

    async def fetch_acme():
        resp = await client.get("/acme/auth/me", headers=acme_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "admin@acme.com"

    async def fetch_globex():
        resp = await client.get("/globex/auth/me", headers=globex_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "admin@globex.com"

    # Fire 20 interleaved concurrent requests
    tasks = [fetch_acme() if i % 2 == 0 else fetch_globex() for i in range(20)]
    await asyncio.gather(*tasks)
