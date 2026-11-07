"""Database session management and lifecycle."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import logger
from app.database.base import Base

# Detect Vercel serverless environment
IS_VERCEL = os.environ.get("VERCEL") == "1"

# Determine target database URL with safe fallback for initial Vercel deployments
database_url = settings.DATABASE_URL
if IS_VERCEL and ("localhost" in database_url or "127.0.0.1" in database_url):
    logger.warning("Vercel environment detected with localhost DATABASE_URL. Falling back to /tmp/tenant_db.sqlite")
    database_url = "sqlite+aiosqlite:////tmp/tenant_db.sqlite"

# Engine configuration
connect_args = {}
engine_kwargs = {
    "echo": settings.DEBUG and "sqlite" not in database_url,
    "pool_pre_ping": True,
}

if "sqlite" in database_url:
    connect_args["check_same_thread"] = False
elif IS_VERCEL:
    # Use NullPool in serverless environments to prevent connection exhaustion
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW

engine: AsyncEngine = create_async_engine(
    database_url,
    connect_args=connect_args,
    **engine_kwargs,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for obtaining a database session outside HTTP requests."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables and seed foundational roles and permissions."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default roles and permissions if they don't exist
    from sqlalchemy import select

    from app.database.models import Permission, Role, RolePermission

    async with async_session_factory() as session:
        # Check if permissions exist
        result = await session.execute(select(Permission))
        if not result.scalars().first():
            logger.info("Seeding initial roles and permissions...")
            perms_data = [
                ("users:read", "Read Users", "Allows viewing tenant users"),
                ("users:write", "Write Users", "Allows creating and updating tenant users"),
                ("settings:read", "Read Settings", "Allows viewing tenant settings"),
                ("settings:write", "Write Settings", "Allows modifying tenant settings"),
                ("resources:read", "Read Resources", "Allows viewing tenant resources"),
                ("resources:write", "Write Resources", "Allows managing tenant resources"),
            ]
            perms = {
                code: Permission(code=code, name=name, description=desc)
                for code, name, desc in perms_data
            }
            session.add_all(perms.values())
            await session.flush()

            # Create default roles
            admin_role = Role(name="admin", description="Full administrative access within tenant")
            member_role = Role(name="member", description="Standard tenant member access")
            viewer_role = Role(name="viewer", description="Read-only tenant access")
            session.add_all([admin_role, member_role, viewer_role])
            await session.flush()

            # Assign permissions to roles
            admin_perms = [
                RolePermission(role_id=admin_role.id, permission_id=p.id)
                for p in perms.values()
            ]
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
            await session.commit()
            logger.info("Initial roles and permissions seeded successfully.")
