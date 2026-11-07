"""Pytest test configuration and fixtures."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.authentication.password import hash_password
from app.core.config import settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.routing.route_registry import tenant_app_cache
from app.tenants.models import Permission, Role, RolePermission, Tenant, TenantUser, User

# Use in-memory SQLite for testing
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
)

test_session_factory = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_database():
    """Setup clean tables and initial seed data for every test."""
    # Reset application cache between tests
    await tenant_app_cache.clear()

    # Re-create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Override get_db dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Also patch app.database.session.get_db_context and async_session_factory
    from app.database import session as db_session_module
    old_session_factory = db_session_module.async_session_factory
    db_session_module.async_session_factory = test_session_factory

    # Seed baseline roles and permissions
    async with test_session_factory() as session:
        perms_data = [
            ("users:read", "Read Users", "Allows viewing tenant users"),
            ("users:write", "Write Users", "Allows creating tenant users"),
            ("settings:read", "Read Settings", "Allows viewing tenant settings"),
            ("settings:write", "Write Settings", "Allows modifying tenant settings"),
            ("resources:read", "Read Resources", "Allows viewing tenant resources"),
            ("resources:write", "Write Resources", "Allows creating tenant resources"),
        ]
        perms = {
            code: Permission(code=code, name=name, description=desc)
            for code, name, desc in perms_data
        }
        session.add_all(perms.values())
        await session.flush()

        admin_role = Role(name="admin", description="Admin role")
        member_role = Role(name="member", description="Member role")
        viewer_role = Role(name="viewer", description="Viewer role")
        session.add_all([admin_role, member_role, viewer_role])
        await session.flush()

        admin_perms = [RolePermission(role_id=admin_role.id, permission_id=p.id) for p in perms.values()]
        member_perms = [
            RolePermission(role_id=member_role.id, permission_id=perms["users:read"].id),
            RolePermission(role_id=member_role.id, permission_id=perms["resources:read"].id),
            RolePermission(role_id=member_role.id, permission_id=perms["resources:write"].id),
        ]
        viewer_perms = [
            RolePermission(role_id=viewer_role.id, permission_id=perms["users:read"].id),
            RolePermission(role_id=viewer_role.id, permission_id=perms["resources:read"].id),
        ]
        session.add_all(admin_perms + member_perms + viewer_perms)

        # Seed pre-defined test tenants: 'acme' and 'globex' (active), and 'inactivetenant'
        acme = Tenant(
            slug="acme",
            name="Acme Corporation",
            status="active",
            config_metadata={"theme": "dark", "plan": "enterprise"},
        )
        globex = Tenant(
            slug="globex",
            name="Globex International",
            status="active",
            config_metadata={"theme": "light", "plan": "starter"},
        )
        inactive_t = Tenant(
            slug="inactivetenant",
            name="Inactive Corp",
            status="inactive",
            config_metadata={},
        )
        session.add_all([acme, globex, inactive_t])
        await session.flush()

        # Seed test users for Acme and Globex
        acme_admin_user = User(
            email="admin@acme.com",
            hashed_password=hash_password("Password123!"),
            full_name="Acme Admin",
            is_active=True,
        )
        acme_member_user = User(
            email="member@acme.com",
            hashed_password=hash_password("Password123!"),
            full_name="Acme Member",
            is_active=True,
        )
        globex_admin_user = User(
            email="admin@globex.com",
            hashed_password=hash_password("Password123!"),
            full_name="Globex Admin",
            is_active=True,
        )
        session.add_all([acme_admin_user, acme_member_user, globex_admin_user])
        await session.flush()

        # Memberships
        session.add_all([
            TenantUser(tenant_id=acme.id, user_id=acme_admin_user.id, role_id=admin_role.id, is_active=True),
            TenantUser(tenant_id=acme.id, user_id=acme_member_user.id, role_id=member_role.id, is_active=True),
            TenantUser(tenant_id=globex.id, user_id=globex_admin_user.id, role_id=admin_role.id, is_active=True),
        ])
        await session.commit()

    yield

    db_session_module.async_session_factory = old_session_factory
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client bound to the FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def admin_headers() -> dict:
    """Administrative authorization headers."""
    return {"X-Admin-Key": settings.ADMIN_API_KEY}
