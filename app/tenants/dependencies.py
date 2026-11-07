"""Tenant context variables and FastAPI dependencies."""

from contextvars import ContextVar

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TenantNotFoundError
from app.database.models import Tenant
from app.database.session import get_db
from app.tenants.repository import TenantRepository

# ContextVar for thread-safe, coroutine-safe tenant context propagation
_current_tenant_ctx: ContextVar[Tenant | None] = ContextVar("current_tenant", default=None)


def set_current_tenant(tenant: Tenant | None):
    """Set the active tenant in the current context."""
    return _current_tenant_ctx.set(tenant)


def reset_current_tenant(token):
    """Reset the tenant context to prevent context leakage."""
    _current_tenant_ctx.reset(token)


def get_current_tenant_from_context() -> Tenant | None:
    """Retrieve the current tenant from the context variable."""
    return _current_tenant_ctx.get()


async def get_current_tenant(request: Request) -> Tenant:
    """FastAPI dependency to retrieve the authenticated/active tenant for the request."""
    # Check request state first (injected by dispatcher), then ContextVar
    tenant = getattr(request.state, "tenant", None) or _current_tenant_ctx.get()
    if not tenant:
        raise TenantNotFoundError("No active tenant context found for this request")
    return tenant


async def get_tenant_repository(
    session: AsyncSession = Depends(get_db),
) -> TenantRepository:
    """FastAPI dependency providing a TenantRepository instance."""
    return TenantRepository(session)
