"""Tests for low-level ASGI TenantDispatcher behavior, caching, and scope handling."""

import pytest

from app.routing.route_registry import tenant_app_cache
from app.routing.tenant_dispatcher import TenantDispatcher


@pytest.mark.asyncio
async def test_dispatcher_lifespan_events():
    """Verify ASGI Lifespan events are acknowledged properly."""
    dispatcher = TenantDispatcher()

    messages_to_receive = [
        {"type": "lifespan.startup"},
        {"type": "lifespan.shutdown"},
    ]
    sent_messages = []

    async def mock_receive():
        if messages_to_receive:
            return messages_to_receive.pop(0)
        return {"type": "unknown"}

    async def mock_send(message):
        sent_messages.append(message)

    await dispatcher({"type": "lifespan"}, mock_receive, mock_send)

    assert len(sent_messages) == 2
    assert sent_messages[0]["type"] == "lifespan.startup.complete"
    assert sent_messages[1]["type"] == "lifespan.shutdown.complete"


@pytest.mark.asyncio
async def test_tenant_subapplication_caching_and_reuse():
    """Verify tenant sub-applications are cached and reused rather than recreated per request."""
    # Ensure cache is initially empty
    await tenant_app_cache.clear()
    assert tenant_app_cache.size() == 0

    dispatcher = TenantDispatcher()

    # Create dummy HTTP ASGI scope for /acme/health
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "root_path": "/acme",
        "path_params": {"tenant": "acme"},
        "headers": [(b"host", b"test")],
        "query_string": b"",
    }

    sent_messages = []
    async def mock_receive():
        return {"type": "http.request"}

    async def mock_send(msg):
        sent_messages.append(msg)

    # First request: loads tenant from db and creates sub-app
    await dispatcher(scope.copy(), mock_receive, mock_send)
    assert tenant_app_cache.size() == 1
    first_app = await tenant_app_cache.get("acme")
    assert first_app is not None

    # Second request: reuses cached application
    sent_messages.clear()
    await dispatcher(scope.copy(), mock_receive, mock_send)
    assert tenant_app_cache.size() == 1
    second_app = await tenant_app_cache.get("acme")

    # MUST be the exact same object in memory
    assert first_app is second_app
