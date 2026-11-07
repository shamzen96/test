"""Tenant lifecycle and business logic service."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authentication.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)
from app.authentication.password import hash_password, verify_password
from app.core.exceptions import (
    AuthenticationRequiredError,
    ConflictError,
    CrossTenantAccessError,
    TenantInactiveError,
    TenantNotFoundError,
)
from app.database.models import AuditLog, RefreshToken, Role, Tenant, TenantUser, User
from app.routing.route_registry import tenant_app_cache
from app.tenants.repository import TenantRepository
from app.tenants.schemas import TenantCreate, TenantUpdate


class TenantService:
    """Service encapsulating tenant lifecycle, user registration, and authentication."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TenantRepository(session)

    async def create_tenant(self, data: TenantCreate, audit_user_id: str | None = None) -> Tenant:
        """Create a new tenant with conflict validation and audit logging."""
        existing = await self.repo.get_by_slug(data.slug)
        if existing:
            raise ConflictError(f"Tenant with slug '{data.slug}' already exists")

        tenant = Tenant(
            slug=data.slug,
            name=data.name,
            status="active",
            database_url=data.database_url,
            config_metadata=data.config_metadata,
        )
        tenant = await self.repo.create(tenant)

        # Audit log
        audit = AuditLog(
            tenant_id=tenant.id,
            user_id=audit_user_id,
            action="TENANT_CREATED",
            resource=f"tenants/{tenant.id}",
            details={"slug": tenant.slug, "name": tenant.name},
        )
        self.session.add(audit)
        await self.session.commit()
        return tenant

    async def get_tenant_by_id(self, tenant_id: str) -> Tenant:
        tenant = await self.repo.get_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")
        return tenant

    async def get_tenant_by_slug(self, slug: str) -> Tenant:
        tenant = await self.repo.get_by_slug(slug)
        if not tenant:
            raise TenantNotFoundError("Tenant not found")
        return tenant

    async def list_tenants(
        self, skip: int = 0, limit: int = 100, status: str | None = None
    ) -> list[Tenant]:
        return await self.repo.list_tenants(skip=skip, limit=limit, status=status)

    async def update_tenant(self, tenant_id: str, data: TenantUpdate) -> Tenant:
        tenant = await self.get_tenant_by_id(tenant_id)
        old_slug = tenant.slug

        if data.name is not None:
            tenant.name = data.name
        if data.config_metadata is not None:
            tenant.config_metadata = data.config_metadata
        if data.status is not None:
            tenant.status = data.status

        tenant = await self.repo.update(tenant)
        await self.session.commit()

        # Invalidate application cache to ensure updated configuration takes effect
        await tenant_app_cache.invalidate(old_slug)
        return tenant

    async def set_tenant_status(self, tenant_id: str, status: str) -> Tenant:
        tenant = await self.get_tenant_by_id(tenant_id)
        tenant.status = status
        tenant = await self.repo.update(tenant)
        await self.session.commit()

        # Invalidate sub-application cache
        await tenant_app_cache.invalidate(tenant.slug)
        return tenant

    async def register_tenant_user(
        self,
        tenant_slug: str,
        email: str,
        password: str,
        full_name: str,
        role_name: str = "member",
    ) -> TenantUser:
        """Register a user within a specific tenant."""
        tenant = await self.get_tenant_by_slug(tenant_slug)
        if tenant.status != "active":
            raise TenantInactiveError("Tenant is inactive")

        # Check if user already exists globally
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        user = result.scalars().first()

        if not user:
            user = User(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                is_active=True,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Check if already a member of this tenant
            stmt_mem = select(TenantUser).where(
                TenantUser.tenant_id == tenant.id,
                TenantUser.user_id == user.id,
            )
            res_mem = await self.session.execute(stmt_mem)
            if res_mem.scalars().first():
                raise ConflictError(f"User with email '{email}' is already a member of tenant '{tenant_slug}'")

        # Resolve role
        stmt_role = select(Role).where(Role.name == role_name)
        result_role = await self.session.execute(stmt_role)
        role = result_role.scalars().first()
        if not role:
            # Fallback to creating role if not present
            role = Role(name=role_name, description=f"{role_name.capitalize()} role")
            self.session.add(role)
            await self.session.flush()

        membership = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            role_id=role.id,
            is_active=True,
        )
        self.session.add(membership)
        await self.session.commit()

        # Reload with relationships
        stmt_full = (
            select(TenantUser)
            .options(selectinload(TenantUser.user), selectinload(TenantUser.role))
            .where(TenantUser.id == membership.id)
        )
        res_full = await self.session.execute(stmt_full)
        return res_full.scalars().one()

    async def authenticate_tenant_user(
        self, tenant_slug: str, email: str, password: str
    ) -> dict:
        """Authenticate user against tenant and return token pair."""
        tenant = await self.get_tenant_by_slug(tenant_slug)
        if tenant.status != "active":
            raise TenantInactiveError("Tenant is inactive")

        stmt = (
            select(TenantUser)
            .join(TenantUser.user)
            .options(selectinload(TenantUser.user), selectinload(TenantUser.role))
            .where(
                TenantUser.tenant_id == tenant.id,
                User.email == email,
            )
        )
        result = await self.session.execute(stmt)
        tenant_user = result.scalars().first()

        if not tenant_user or not tenant_user.is_active or not tenant_user.user.is_active:
            raise AuthenticationRequiredError("Invalid email or password")

        if not verify_password(password, tenant_user.user.hashed_password):
            raise AuthenticationRequiredError("Invalid email or password")

        role_name = tenant_user.role.name if tenant_user.role else "member"
        access_token = create_access_token(
            user_id=tenant_user.user.id,
            tenant_slug=tenant.slug,
            tenant_id=tenant.id,
            role=role_name,
        )
        refresh_token = create_refresh_token(
            user_id=tenant_user.user.id,
            tenant_slug=tenant.slug,
            tenant_id=tenant.id,
        )

        # Store hashed refresh token in database for rotation/revocation
        db_refresh = RefreshToken(
            token_hash=hash_token(refresh_token),
            user_id=tenant_user.user.id,
            tenant_id=tenant.id,
            expires_at=datetime.now(UTC),  # will be verified via jwt exp
        )
        self.session.add(db_refresh)
        await self.session.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": 1800,
        }

    async def refresh_user_token(self, tenant_slug: str, refresh_token: str) -> dict:
        """Rotate refresh token and issue a fresh access token."""
        tenant = await self.get_tenant_by_slug(tenant_slug)
        payload = decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise AuthenticationRequiredError("Invalid token type: expected refresh token")

        if payload.get("tenant_slug") != tenant.slug:
            raise CrossTenantAccessError("Access denied: token does not match tenant")

        token_h = hash_token(refresh_token)
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_h,
            RefreshToken.tenant_id == tenant.id,
        )
        result = await self.session.execute(stmt)
        stored_token = result.scalars().first()

        if not stored_token or stored_token.revoked_at is not None:
            raise AuthenticationRequiredError("Refresh token has been revoked or is invalid")

        # Revoke old refresh token (rotation)
        stored_token.revoked_at = datetime.now(UTC)

        # Issue new token pair
        user_id = payload["sub"]
        stmt_user = (
            select(TenantUser)
            .options(selectinload(TenantUser.role))
            .where(TenantUser.tenant_id == tenant.id, TenantUser.user_id == user_id)
        )
        res_user = await self.session.execute(stmt_user)
        tenant_user = res_user.scalars().first()

        if not tenant_user or not tenant_user.is_active:
            raise AuthenticationRequiredError("User is no longer active in this tenant")

        role_name = tenant_user.role.name if tenant_user.role else "member"
        new_access = create_access_token(
            user_id=user_id,
            tenant_slug=tenant.slug,
            tenant_id=tenant.id,
            role=role_name,
        )
        new_refresh = create_refresh_token(
            user_id=user_id,
            tenant_slug=tenant.slug,
            tenant_id=tenant.id,
        )

        new_db_refresh = RefreshToken(
            token_hash=hash_token(new_refresh),
            user_id=user_id,
            tenant_id=tenant.id,
            expires_at=datetime.now(UTC),
        )
        self.session.add(new_db_refresh)
        await self.session.commit()

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": 1800,
        }

    async def logout_user(self, tenant_slug: str, refresh_token: str) -> bool:
        """Revoke a refresh token on logout."""
        tenant = await self.get_tenant_by_slug(tenant_slug)
        token_h = hash_token(refresh_token)
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_h,
            RefreshToken.tenant_id == tenant.id,
        )
        result = await self.session.execute(stmt)
        token_rec = result.scalars().first()
        if token_rec:
            token_rec.revoked_at = datetime.now(UTC)
            await self.session.commit()
            return True
        return False
