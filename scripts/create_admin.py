"""Script to create a superadmin user for system-level administration."""

import asyncio
import sys
from sqlalchemy import select
from app.authentication.password import hash_password
from app.database.models import User
from app.database.session import async_session_factory, init_db


async def create_admin(email: str, password: str, full_name: str) -> None:
    """Create or update a superadmin user."""
    await init_db()

    async with async_session_factory() as session:
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        existing_user = result.scalars().first()

        if existing_user:
            print(f"User {email} already exists. Promoting to superuser...")
            existing_user.is_superuser = True
            existing_user.is_active = True
            existing_user.hashed_password = hash_password(password)
        else:
            print(f"Creating superadmin user: {email}")
            user = User(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                is_active=True,
                is_superuser=True,
            )
            session.add(user)

        await session.commit()
        print(f"Superadmin user '{email}' created successfully.")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@example.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "AdminSecretPassword123!"
    full_name = sys.argv[3] if len(sys.argv) > 3 else "System Administrator"

    asyncio.run(create_admin(email, password, full_name))

