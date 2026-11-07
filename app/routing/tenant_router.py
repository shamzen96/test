"""Dynamic tenant mount and routing mechanisms."""

import re

from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.routing.tenant_dispatcher import TenantDispatcher


class DynamicTenantMount(Mount):
    """Custom ASGI Mount supporting parameterized tenant paths like '/{tenant}'."""

    def __init__(
        self,
        path: str = "/{tenant}",
        app: ASGIApp | None = None,
        name: str | None = "tenant_mount",
    ):
        super().__init__(path=path, app=app or TenantDispatcher(), name=name)
        # Regex captures /{tenant} or /{tenant}/...
        # Captures any first path segment to allow TenantDispatcher to validate slug syntax
        self.pattern = re.compile(r"^/(?P<tenant>[^/]+)(?P<subpath>/.*)?$")

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            match = self.pattern.match(path)
            if match:
                tenant = match.group("tenant").lower()

                # Bypass reserved administrative and system routes so they match explicit routes
                if tenant in settings.RESERVED_TENANT_SLUGS:
                    return Match.NONE, {}

                subpath = match.group("subpath") or "/"
                root_path = scope.get("root_path", "")

                child_scope = dict(scope)
                child_scope["path_params"] = dict(scope.get("path_params", {}))
                child_scope["path_params"]["tenant"] = tenant
                child_scope["root_path"] = f"{root_path}/{tenant}"
                child_scope["path"] = subpath
                child_scope["endpoint"] = self.app

                return Match.FULL, child_scope

        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def mount_tenant_dispatcher(
    fastapi_app,
    dispatcher: TenantDispatcher | None = None,
    path: str = "/{tenant}",
) -> None:
    """Convenience helper to mount the DynamicTenantMount onto a FastAPI application."""
    dynamic_mount = DynamicTenantMount(path=path, app=dispatcher or TenantDispatcher())
    fastapi_app.router.routes.append(dynamic_mount)
