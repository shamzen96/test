"""Repository for tenant data access and persistence."""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Tenant, TenantResource


class TenantRepository:
    """Data access layer for Tenant entities."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_tenants(
        self, skip: int = 0, limit: int = 100, status: str | None = None
    ) -> list[Tenant]:
        stmt = select(Tenant)
        if status:
            stmt = stmt.where(Tenant.status == status)
        stmt = stmt.offset(skip).limit(limit).order_by(Tenant.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant

    async def update(self, tenant: Tenant) -> Tenant:
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant

    async def soft_delete(self, tenant: Tenant) -> Tenant:
        """Deactivate tenant as a safe lifecycle policy."""
        tenant.status = "inactive"
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant

    # Tenant-scoped resources
    async def create_resource(self, resource: TenantResource) -> TenantResource:
        self.session.add(resource)
        await self.session.flush()
        await self.session.refresh(resource)
        return resource

    async def list_resources(self, tenant_id: str) -> list[TenantResource]:
        stmt = (
            select(TenantResource)
            .where(TenantResource.tenant_id == tenant_id)
            .order_by(TenantResource.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_resource(self, tenant_id: str, resource_id: str) -> TenantResource | None:
        stmt = select(TenantResource).where(
            TenantResource.tenant_id == tenant_id,
            TenantResource.id == resource_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
