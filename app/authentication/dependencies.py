"""Authentication dependencies and tenant membership verification."""


from fastapi import Depends, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authentication.jwt_handler import decode_token
from app.core.config import settings
from app.core.exceptions import (
    AuthenticationRequiredError,
    CrossTenantAccessError,
    PermissionDeniedError,
)
from app.database.models import Role, RolePermission, Tenant, TenantUser, User
from app.database.session import get_db
from app.tenants.dependencies import get_current_tenant

security_bearer = HTTPBearer(auto_error=False)


async def get_current_tenant_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    current_tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db),
) -> TenantUser:
    """Validate JWT token, verify current tenant matching, and return active tenant membership."""
    if not credentials or not credentials.credentials:
        raise AuthenticationRequiredError("Authentication required")

    token = credentials.credentials
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise AuthenticationRequiredError("Invalid token type: expected access token")

    token_tenant_slug = payload.get("tenant_slug")
    token_tenant_id = payload.get("tenant_id")
    user_id = payload.get("sub")

    if not user_id:
        raise AuthenticationRequiredError("Invalid token: missing subject")

    # Strict Cross-Tenant Token Protection:
    # A token issued for 'acme' must NOT grant access to 'globex'
    if token_tenant_slug != current_tenant.slug or (token_tenant_id and token_tenant_id != current_tenant.id):
        raise CrossTenantAccessError("Access denied: token is not valid for this tenant")

    # Fetch user and tenant membership with permissions eagerly loaded
    stmt = (
        select(TenantUser)
        .options(
            selectinload(TenantUser.user),
            selectinload(TenantUser.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission),
        )
        .where(
            TenantUser.tenant_id == current_tenant.id,
            TenantUser.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    tenant_user = result.scalars().first()

    if not tenant_user or not tenant_user.is_active or not tenant_user.user.is_active:
        raise CrossTenantAccessError("Access denied: user is not an active member of this tenant")

    # Attach to request state for downstream logging/telemetry
    request.state.current_user = tenant_user.user
    request.state.tenant_user = tenant_user

    return tenant_user


async def get_current_admin(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    session: AsyncSession = Depends(get_db),
) -> bool:
    """Validate administrative access for /admin routes via API key or superuser token."""
    # Check admin API key first
    if x_admin_key and x_admin_key == settings.ADMIN_API_KEY:
        return True

    # Check superuser JWT if provided
    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials, verify_audience=False)
            user_id = payload.get("sub")
            if user_id:
                stmt = select(User).where(User.id == user_id, User.is_superuser == True)
                result = await session.execute(stmt)
                user = result.scalars().first()
                if user and user.is_active:
                    return True
        except Exception:
            pass

    raise PermissionDeniedError("Administrative credentials required")
