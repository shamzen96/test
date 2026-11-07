"""JWT token generation, signature verification, and claims decoding."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationRequiredError


def create_token(
    claims: dict[str, Any],
    expires_delta: timedelta,
    token_type: str = "access",
) -> str:
    """Create a signed JWT token with standard claims."""
    now = datetime.now(UTC)
    expire = now + expires_delta

    to_encode = claims.copy()
    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
        "type": token_type,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def create_access_token(
    user_id: str,
    tenant_slug: str,
    tenant_id: str,
    role: str = "member",
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a tenant-scoped access token."""
    delta = expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_token(
        claims={
            "sub": user_id,
            "tenant_slug": tenant_slug,
            "tenant_id": tenant_id,
            "role": role,
        },
        expires_delta=delta,
        token_type="access",
    )


def create_refresh_token(
    user_id: str,
    tenant_slug: str,
    tenant_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a tenant-scoped refresh token."""
    delta = expires_delta or timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return create_token(
        claims={
            "sub": user_id,
            "tenant_slug": tenant_slug,
            "tenant_id": tenant_id,
        },
        expires_delta=delta,
        token_type="refresh",
    )


def decode_token(token: str, verify_audience: bool = True) -> dict[str, Any]:
    """Decode and rigorously validate JWT signature and standard claims."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE if verify_audience else None,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthenticationRequiredError("Token has expired")
    except (jwt.InvalidIssuerError, jwt.InvalidAudienceError):
        raise AuthenticationRequiredError("Invalid token issuer or audience")
    except jwt.PyJWTError as e:
        raise AuthenticationRequiredError(f"Invalid authentication token: {str(e)}")


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of a token for safe database persistence and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
