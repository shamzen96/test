"""ASGI-compatible dynamic tenant dispatcher."""

import re

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.core.logging import logger
from app.database.session import get_db_context
from app.routing.route_registry import tenant_app_cache
from app.tenants.dependencies import reset_current_tenant, set_current_tenant
from app.tenants.repository import TenantRepository

TENANT_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


class TenantDispatcher:
    """Dynamic ASGI dispatcher that resolves incoming requests to tenant-specific sub-applications."""

    def __init__(self, app_factory=None):
        self.app_factory = app_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI request handler."""
        if self.app_factory is None:
            from app.tenants.tenant_factory import create_tenant_app
            self.app_factory = create_tenant_app
        # 1. Handle ASGI Lifespan events
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] not in ("http", "websocket"):
            return

        # 2. Extract tenant slug
        tenant_slug = scope.get("path_params", {}).get("tenant")
        if not tenant_slug:
            # Fallback: parse from path
            path = scope.get("path", "")
            parts = [p for p in path.split("/") if p]
            if parts:
                tenant_slug = parts[0]

        if not tenant_slug:
            response = JSONResponse(
                {"detail": "Tenant identifier required"},
                status_code=400,
            )
            await response(scope, receive, send)
            return

        tenant_slug = tenant_slug.lower()

        # 3. Validate tenant syntax and reserved words
        if tenant_slug in settings.RESERVED_TENANT_SLUGS:
            response = JSONResponse({"detail": "Tenant not found"}, status_code=404)
            await response(scope, receive, send)
            return

        if not TENANT_SLUG_PATTERN.match(tenant_slug):
            response = JSONResponse(
                {"detail": "Invalid tenant identifier"},
                status_code=400,
            )
            await response(scope, receive, send)
            return

        # 4. Look up tenant in database
        try:
            async with get_db_context() as session:
                repo = TenantRepository(session)
                tenant = await repo.get_by_slug(tenant_slug)
        except Exception as exc:
            logger.error(f"Database error resolving tenant '{tenant_slug}': {exc}")
            response = JSONResponse(
                {"detail": "Internal server error resolving tenant"},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        # 5. Validate tenant existence and active status
        if not tenant:
            response = JSONResponse({"detail": "Tenant not found"}, status_code=404)
            await response(scope, receive, send)
            return

        if tenant.status != "active":
            response = JSONResponse({"detail": "Tenant is inactive"}, status_code=400)
            await response(scope, receive, send)
            return

        # 6. Resolve / Create cached tenant sub-application
        try:
            tenant_app = await tenant_app_cache.get_or_create(
                tenant=tenant,
                app_factory=self.app_factory,
            )
        except Exception as exc:
            logger.error(f"Failed to create tenant sub-application for '{tenant_slug}': {exc}")
            response = JSONResponse(
                {"detail": "Internal server error initializing tenant application"},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        # 7. Propagate tenant context
        token = set_current_tenant(tenant)
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["tenant"] = tenant

        # Ensure root_path and path are appropriately scoped if dispatched directly
        if not scope.get("root_path", "").endswith(f"/{tenant.slug}"):
            # Strip tenant prefix from path if present
            raw_path = scope.get("path", "")
            prefix = f"/{tenant.slug}"
            if raw_path.startswith(prefix):
                remaining = raw_path[len(prefix):]
                scope["path"] = remaining if remaining else "/"
                scope["root_path"] = scope.get("root_path", "") + prefix

        try:
            # 8. Forward request to tenant sub-application
            await tenant_app(scope, receive, send)
        except Exception as exc:
            logger.error(f"Unhandled exception in tenant '{tenant.slug}' sub-app: {exc}")
            response = JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )
            await response(scope, receive, send)
        finally:
            # 9. Clean up context to avoid leakage across requests
            reset_current_tenant(token)
