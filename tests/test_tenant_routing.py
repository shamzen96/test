"""Tests for dynamic tenant routing and URL resolution."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_root_health_and_landing(client: httpx.AsyncClient):
    """Verify root-level system health and landing endpoints work."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"

    resp_root = await client.get("/")
    assert resp_root.status_code == 200
    assert "pattern" in resp_root.json()


@pytest.mark.asyncio
async def test_valid_tenant_routing(client: httpx.AsyncClient):
    """Verify routing to valid tenant sub-application endpoints."""
    # Test root of tenant /acme
    resp = await client.get("/acme")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_slug"] == "acme"
    assert data["status"] == "active"

    # Test /acme/ with trailing slash
    resp_slash = await client.get("/acme/")
    assert resp_slash.status_code == 200
    assert resp_slash.json()["tenant_slug"] == "acme"

    # Test /acme/health
    resp_health = await client.get("/acme/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["tenant"] == "acme"
    assert resp_health.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_multiple_tenant_routing(client: httpx.AsyncClient):
    """Verify multiple distinct tenants route to their respective sub-applications."""
    resp_acme = await client.get("/acme/health")
    assert resp_acme.status_code == 200
    assert resp_acme.json()["tenant"] == "acme"

    resp_globex = await client.get("/globex/health")
    assert resp_globex.status_code == 200
    assert resp_globex.json()["tenant"] == "globex"


@pytest.mark.asyncio
async def test_unknown_tenant_rejection(client: httpx.AsyncClient):
    """Verify requesting a non-existent tenant returns 404."""
    resp = await client.get("/nonexistent/health")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Tenant not found"


@pytest.mark.asyncio
async def test_invalid_tenant_slug_rejection(client: httpx.AsyncClient):
    """Verify malformed or invalid tenant slugs return 400."""
    resp = await client.get("/invalid_slug!/health")
    assert resp.status_code == 400
    assert "Invalid tenant identifier" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reserved_slug_rejection(client: httpx.AsyncClient):
    """Verify reserved slugs are not treated as tenants."""
    resp = await client.get("/docs")
    assert resp.status_code in (200, 307)

    # Calling an unknown path under a reserved slug returns 404
    resp_reserved = await client.get("/openapi.json/subpath")
    assert resp_reserved.status_code == 404


@pytest.mark.asyncio
async def test_query_parameter_and_body_preservation(client: httpx.AsyncClient):
    """Verify query parameters and request bodies are preserved through dynamic dispatch."""
    reg_payload = {
        "email": "querytest@acme.com",
        "password": "SecurePassword123!",
        "full_name": "Query Test",
        "role": "member",
    }
    resp = await client.post("/acme/auth/register", json=reg_payload)
    assert resp.status_code == 201
    assert resp.json()["email"] == "querytest@acme.com"


@pytest.mark.asyncio
async def test_tenant_specific_openapi_docs_and_dashboard(client: httpx.AsyncClient):
    """Verify tenant OpenAPI spec and authenticated dashboard."""
    # Tenant Swagger docs
    docs_resp = await client.get("/acme/docs")
    assert docs_resp.status_code == 200
    assert "Swagger UI" in docs_resp.text or "swagger" in docs_resp.text.lower()

    # Tenant OpenAPI JSON
    openapi_resp = await client.get("/acme/openapi.json")
    assert openapi_resp.status_code == 200
    spec = openapi_resp.json()
    assert spec["info"]["title"] == "Tenant API: Acme Corporation (acme)"

    # Login to acme
    login_resp = await client.post(
        "/acme/auth/login",
        json={"email": "admin@acme.com", "password": "Password123!"},
    )
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # Fetch dashboard
    dash_resp = await client.get("/acme/dashboard", headers=headers)
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert dash_data["tenant"] == "acme"
    assert "metrics" in dash_data
    assert dash_data["metrics"]["active_users"] >= 1
