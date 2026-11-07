"""Application configuration and settings."""


from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Dynamic Multi Tenant API"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/tenant_db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30

    # Authentication & Security
    JWT_SECRET_KEY: str = "production-ready-super-secret-key-minimum-32-characters"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "dynamic-tenant-api"
    JWT_AUDIENCE: str = "tenant-users"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ADMIN_API_KEY: str = "admin-secret-key-change-in-production"

    # Dynamic Routing & Caching
    TENANT_CACHE_MAX_SIZE: int = 1000
    TENANT_CACHE_TTL_SECONDS: int = 3600

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Reserved routes that cannot be used as tenant slugs
    RESERVED_TENANT_SLUGS: set[str] = {
        "admin",
        "api",
        "health",
        "docs",
        "redoc",
        "openapi.json",
        "metrics",
        "favicon.ico",
        "static",
    }

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


settings = Settings()
