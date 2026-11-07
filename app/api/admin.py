"""Administrative tenant management API endpoints."""


from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.authentication.dependencies import get_current_admin
from app.database.session import get_db
from app.tenants.schemas import TenantCreate, TenantResponse, TenantUpdate
from app.tenants.service import TenantService

router = APIRouter(
    prefix="/admin",
    tags=["Tenant Administration"],
    dependencies=[Depends(get_current_admin)],
)


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Tenant",
)
async def create_tenant(
    payload: TenantCreate,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.create_tenant(payload)


@router.get(
    "/tenants",
    response_model=list[TenantResponse],
    summary="List Tenants",
)
async def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, pattern="^(active|inactive|suspended)$"),
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.list_tenants(skip=skip, limit=limit, status=status)


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    summary="Get Tenant by ID",
)
async def get_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.get_tenant_by_id(tenant_id)


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    summary="Update Tenant",
)
async def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.update_tenant(tenant_id, payload)


@router.delete(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    summary="Safely Deactivate / Soft Delete Tenant",
)
async def delete_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.set_tenant_status(tenant_id, status="inactive")


@router.post(
    "/tenants/{tenant_id}/activate",
    response_model=TenantResponse,
    summary="Activate Tenant",
)
async def activate_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.set_tenant_status(tenant_id, status="active")


@router.post(
    "/tenants/{tenant_id}/deactivate",
    response_model=TenantResponse,
    summary="Deactivate Tenant",
)
async def deactivate_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
):
    service = TenantService(session)
    return await service.set_tenant_status(tenant_id, status="inactive")
