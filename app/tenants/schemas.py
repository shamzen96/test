"""Pydantic schemas for tenant management and domain entities."""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings

TENANT_SLUG_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Tenant human-readable display name")
    config_metadata: dict[str, Any] = Field(default_factory=dict, description="Custom tenant configuration metadata")


class TenantCreate(TenantBase):
    slug: str = Field(..., min_length=2, max_length=64, description="Unique URL-friendly tenant identifier")
    database_url: str | None = Field(default=None, description="Optional custom tenant database connection URL")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        slug_clean = v.strip().lower()
        if not TENANT_SLUG_REGEX.match(slug_clean):
            raise ValueError(
                "Tenant slug must be 3-64 characters, lowercase alphanumeric with hyphens or underscores, "
                "and cannot start or end with a hyphen/underscore."
            )
        if slug_clean in settings.RESERVED_TENANT_SLUGS:
            raise ValueError(f"Tenant slug '{slug_clean}' is reserved and cannot be used.")
        return slug_clean


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    config_metadata: dict[str, Any] | None = None
    status: str | None = Field(None, pattern="^(active|inactive|suspended)$")


class TenantResponse(BaseModel):
    """Public tenant response. Excludes sensitive database connection information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    status: str
    config_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TenantResourceCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)


class TenantResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    owner_id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
