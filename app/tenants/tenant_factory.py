"""Tenant application factory for creating isolated FastAPI sub-applications."""

from fastapi import APIRouter, Depends, FastAPI, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authentication.dependencies import get_current_tenant_user
from app.authentication.permissions import PermissionChecker
from app.core.exceptions import ResourceNotFoundError
from app.database.models import Tenant, TenantResource, TenantUser
from app.database.session import get_db
from app.tenants.dependencies import get_current_tenant
from app.tenants.schemas import TenantResourceCreate, TenantResourceResponse
from app.tenants.service import TenantService


class UserRegisterSchema(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    role: str = Field(default="member")


class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class TokenResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class UserResponseSchema(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool


def create_tenant_app(tenant: Tenant) -> FastAPI:
    """Create an independently configured FastAPI sub-application for a tenant."""
    sub_app = FastAPI(
        title=f"Tenant API: {tenant.name} ({tenant.slug})",
        description=f"Isolated sub-application for tenant '{tenant.slug}'",
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # -------------------------------------------------------------
    # Root & Health Endpoints
    # -------------------------------------------------------------
    @sub_app.get("/", summary="Tenant Root")
    async def tenant_root(
        curr_tenant: Tenant = Depends(get_current_tenant),
    ):
        return {
            "tenant_id": curr_tenant.id,
            "tenant_slug": curr_tenant.slug,
            "tenant_name": curr_tenant.name,
            "status": curr_tenant.status,
            "message": f"Welcome to {curr_tenant.name} API",
        }

    @sub_app.get("/health", summary="Tenant Health Check")
    async def tenant_health(
        curr_tenant: Tenant = Depends(get_current_tenant),
    ):
        return {
            "status": "healthy",
            "tenant": curr_tenant.slug,
            "state": curr_tenant.status,
        }

    # -------------------------------------------------------------
    # Authentication Endpoints
    # -------------------------------------------------------------
    auth_router = APIRouter(prefix="/auth", tags=["Tenant Authentication"])

    @auth_router.post("/register", response_model=UserResponseSchema, status_code=status.HTTP_201_CREATED)
    async def register(
        payload: UserRegisterSchema,
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        service = TenantService(session)
        membership = await service.register_tenant_user(
            tenant_slug=curr_tenant.slug,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role_name=payload.role,
        )
        return UserResponseSchema(
            id=membership.user.id,
            email=membership.user.email,
            full_name=membership.user.full_name,
            role=membership.role.name if membership.role else "member",
            is_active=membership.is_active,
        )

    @auth_router.post("/login", response_model=TokenResponseSchema)
    async def login(
        payload: UserLoginSchema,
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        service = TenantService(session)
        return await service.authenticate_tenant_user(
            tenant_slug=curr_tenant.slug,
            email=payload.email,
            password=payload.password,
        )

    @auth_router.post("/refresh", response_model=TokenResponseSchema)
    async def refresh_token(
        payload: RefreshTokenSchema,
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        service = TenantService(session)
        return await service.refresh_user_token(
            tenant_slug=curr_tenant.slug,
            refresh_token=payload.refresh_token,
        )

    @auth_router.get("/me", response_model=UserResponseSchema)
    async def get_me(
        tenant_user: TenantUser = Depends(get_current_tenant_user),
    ):
        return UserResponseSchema(
            id=tenant_user.user.id,
            email=tenant_user.user.email,
            full_name=tenant_user.user.full_name,
            role=tenant_user.role.name if tenant_user.role else "member",
            is_active=tenant_user.is_active,
        )

    @auth_router.post("/logout")
    async def logout(
        payload: RefreshTokenSchema,
        curr_tenant: Tenant = Depends(get_current_tenant),
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        session: AsyncSession = Depends(get_db),
    ):
        service = TenantService(session)
        await service.logout_user(curr_tenant.slug, payload.refresh_token)
        return {"detail": "Logged out successfully"}

    sub_app.include_router(auth_router)

    # -------------------------------------------------------------
    # User Management Endpoints
    # -------------------------------------------------------------
    @sub_app.get("/users", response_model=list[UserResponseSchema], summary="List Tenant Users")
    async def list_users(
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        stmt = (
            select(TenantUser)
            .options(selectinload(TenantUser.user), selectinload(TenantUser.role))
            .where(TenantUser.tenant_id == curr_tenant.id)
        )
        res = await session.execute(stmt)
        members = res.scalars().all()
        return [
            UserResponseSchema(
                id=m.user.id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=m.role.name if m.role else "member",
                is_active=m.is_active,
            )
            for m in members
        ]

    @sub_app.post(
        "/users",
        response_model=UserResponseSchema,
        status_code=status.HTTP_201_CREATED,
        summary="Add/Invite Tenant User",
    )
    async def add_user(
        payload: UserRegisterSchema,
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        # Enforce permission
        checker = PermissionChecker("users:write")
        checker(tenant_user)

        service = TenantService(session)
        membership = await service.register_tenant_user(
            tenant_slug=curr_tenant.slug,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role_name=payload.role,
        )
        return UserResponseSchema(
            id=membership.user.id,
            email=membership.user.email,
            full_name=membership.user.full_name,
            role=membership.role.name if membership.role else "member",
            is_active=membership.is_active,
        )

    # -------------------------------------------------------------
    # Dashboard & Settings Endpoints
    # -------------------------------------------------------------
    @sub_app.get("/dashboard", summary="Tenant Dashboard")
    async def tenant_dashboard(
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        stmt_users = select(TenantUser).where(TenantUser.tenant_id == curr_tenant.id)
        res_users = await session.execute(stmt_users)
        user_count = len(res_users.scalars().all())

        stmt_res = select(TenantResource).where(TenantResource.tenant_id == curr_tenant.id)
        res_res = await session.execute(stmt_res)
        resource_count = len(res_res.scalars().all())

        return {
            "tenant": curr_tenant.slug,
            "metrics": {
                "active_users": user_count,
                "total_resources": resource_count,
            },
            "status": "operational",
        }

    @sub_app.get("/settings", summary="Tenant Settings")
    async def tenant_settings(
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
    ):
        checker = PermissionChecker("settings:read")
        checker(tenant_user)
        return {
            "tenant_id": curr_tenant.id,
            "slug": curr_tenant.slug,
            "name": curr_tenant.name,
            "config": curr_tenant.config_metadata,
        }

    # -------------------------------------------------------------
    # Tenant Isolated Resources Endpoints
    # -------------------------------------------------------------
    resources_router = APIRouter(prefix="/resources", tags=["Tenant Resources"])

    @resources_router.post(
        "",
        response_model=TenantResourceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_resource(
        payload: TenantResourceCreate,
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        resource = TenantResource(
            tenant_id=curr_tenant.id,
            owner_id=tenant_user.user.id,
            title=payload.title,
            content=payload.content,
        )
        session.add(resource)
        await session.commit()
        await session.refresh(resource)
        return resource

    @resources_router.get("", response_model=list[TenantResourceResponse])
    async def list_resources(
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        stmt = (
            select(TenantResource)
            .where(TenantResource.tenant_id == curr_tenant.id)
            .order_by(TenantResource.created_at.desc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @resources_router.get("/{resource_id}", response_model=TenantResourceResponse)
    async def get_resource(
        resource_id: str,
        tenant_user: TenantUser = Depends(get_current_tenant_user),
        curr_tenant: Tenant = Depends(get_current_tenant),
        session: AsyncSession = Depends(get_db),
    ):
        stmt = select(TenantResource).where(
            TenantResource.tenant_id == curr_tenant.id,
            TenantResource.id == resource_id,
        )
        res = await session.execute(stmt)
        resource = res.scalars().first()
        if not resource:
            raise ResourceNotFoundError(f"Resource '{resource_id}' not found in this tenant")
        return resource

    sub_app.include_router(resources_router)

    return sub_app
