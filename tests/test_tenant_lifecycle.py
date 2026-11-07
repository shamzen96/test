"""Tests for administrative tenant lifecycle management, status changes, and cache invalidation."""

import httpx
import pytest

from app.routing.route_registry import tenant_app_cache


@pytest.mark.asyncio
async def test_full_tenant_lifecycle(client: httpx.AsyncClient, admin_headers: dict):
    """Test full tenant lifecycle: Create -> Access -> Deactivate -> Invalidate -> Re-activate -> Delete."""
    # 1. Admin creates a new tenant 'cyberdyne'
    create_payload = {
        "slug": "cyberdyne",
        "name": "Cyberdyne Systems",
        "config_metadata": {"tier": "defense"},
    }
    create_resp = await client.post("/admin/tenants", headers=admin_headers, json=create_payload)
    assert create_resp.status_code == 201
    tenant_data = create_resp.json()
    tenant_id = tenant_data["id"]
    assert tenant_data["slug"] == "cyberdyne"
    assert tenant_data["status"] == "active"

    # 2. Access newly created tenant immediately
    access_resp = await client.get("/cyberdyne/health")
    assert access_resp.status_code == 200
    assert access_resp.json()["tenant"] == "cyberdyne"

    # Verify cached
    cached = await tenant_app_cache.get("cyberdyne")
    assert cached is not None

    # 3. Admin deactivates tenant
    deact_resp = await client.post(f"/admin/tenants/{tenant_id}/deactivate", headers=admin_headers)
    assert deact_resp.status_code == 200
    assert deact_resp.json()["status"] == "inactive"

    # Verify cache was invalidated
    cached_after_deact = await tenant_app_cache.get("cyberdyne")
    assert cached_after_deact is None

    # 4. Accessing inactive tenant MUST be rejected with 400
    inactive_req = await client.get("/cyberdyne/health")
    assert inactive_req.status_code == 400
    assert "Tenant is inactive" in inactive_req.json()["detail"]

    # 5. Admin reactivates tenant
    act_resp = await client.post(f"/admin/tenants/{tenant_id}/activate", headers=admin_headers)
    assert act_resp.status_code == 200
    assert act_resp.json()["status"] == "active"

    # 6. Accessing reactivated tenant succeeds
    reactivated_req = await client.get("/cyberdyne/health")
    assert reactivated_req.status_code == 200
    assert reactivated_req.json()["status"] == "healthy"

    # 7. Safe soft delete (sets status="inactive")
    del_resp = await client.delete(f"/admin/tenants/{tenant_id}", headers=admin_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "inactive"

    # Verify again inactive
    post_del_req = await client.get("/cyberdyne/health")
    assert post_del_req.status_code == 400


@pytest.mark.asyncio
async def test_admin_list_and_get_tenant(client: httpx.AsyncClient, admin_headers: dict):
    """Test listing tenants and fetching tenant details by ID."""
    # List all tenants
    list_resp = await client.get("/admin/tenants", headers=admin_headers)
    assert list_resp.status_code == 200
    tenants = list_resp.json()
    assert len(tenants) >= 2
    slugs = [t["slug"] for t in tenants]
    assert "acme" in slugs
    assert "globex" in slugs

    # Fetch acme by ID
    acme_id = [t["id"] for t in tenants if t["slug"] == "acme"][0]
    get_resp = await client.get(f"/admin/tenants/{acme_id}", headers=admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["slug"] == "acme"


@pytest.mark.asyncio
async def test_admin_patch_tenant(client: httpx.AsyncClient, admin_headers: dict):
    """Test updating tenant name and metadata via PATCH."""
    list_resp = await client.get("/admin/tenants", headers=admin_headers)
    acme_id = [t["id"] for t in list_resp.json() if t["slug"] == "acme"][0]

    patch_payload = {
        "name": "Acme Global Industries",
        "config_metadata": {"theme": "neon", "plan": "enterprise_plus"},
    }
    patch_resp = await client.patch(f"/admin/tenants/{acme_id}", headers=admin_headers, json=patch_payload)
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Acme Global Industries"
    assert updated["config_metadata"]["theme"] == "neon"


@pytest.mark.asyncio
async def test_admin_conflict_duplicate_slug(client: httpx.AsyncClient, admin_headers: dict):
    """Verify attempting to create a tenant with existing slug returns 409 Conflict."""
    conflict_payload = {
        "slug": "acme",
        "name": "Duplicate Acme",
    }
    resp = await client.post("/admin/tenants", headers=admin_headers, json=conflict_payload)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_unauthorized_without_key(client: httpx.AsyncClient):
    """Verify admin endpoints reject requests without proper administrative credentials."""
    resp = await client.get("/admin/tenants")
    assert resp.status_code == 403
    assert "Administrative credentials required" in resp.json()["detail"]
