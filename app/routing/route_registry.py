"""Application cache and route registry for tenant sub-applications."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import logger
from app.database.models import Tenant


class TenantAppCache:
    """Thread-safe and async-safe LRU cache for dynamically created tenant sub-applications."""

    def __init__(self, max_size: int = settings.TENANT_CACHE_MAX_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, FastAPI] = OrderedDict()
        self._metadata: dict[str, dict] = {}
        self._global_lock = asyncio.Lock()
        self._slug_locks: dict[str, asyncio.Lock] = {}

    def _get_slug_lock(self, slug: str) -> asyncio.Lock:
        if slug not in self._slug_locks:
            self._slug_locks[slug] = asyncio.Lock()
        return self._slug_locks[slug]

    async def get(self, slug: str) -> FastAPI | None:
        """Retrieve cached tenant application and update LRU order."""
        async with self._global_lock:
            if slug in self._cache:
                self._cache.move_to_end(slug)
                return self._cache[slug]
            return None

    async def get_or_create(
        self,
        tenant: Tenant,
        app_factory: Callable[[Tenant], FastAPI],
    ) -> FastAPI:
        """Concurrency-safe retrieval or instantiation of a tenant sub-application."""
        slug = tenant.slug

        # First fast-path check
        app = await self.get(slug)
        if app is not None:
            return app

        # Acquire lock specific to this tenant slug to prevent race conditions during app creation
        slug_lock = self._get_slug_lock(slug)
        async with slug_lock:
            # Double check after acquiring slug lock
            app = await self.get(slug)
            if app is not None:
                return app

            logger.info(f"Creating new tenant FastAPI sub-application for slug='{slug}' (id='{tenant.id}')")
            app = app_factory(tenant)

            async with self._global_lock:
                # Evict oldest if exceeding max size
                if len(self._cache) >= self.max_size:
                    evicted_slug, _ = self._cache.popitem(last=False)
                    self._metadata.pop(evicted_slug, None)
                    logger.warning(f"Tenant sub-application cache reached max capacity. Evicted oldest: '{evicted_slug}'")

                self._cache[slug] = app
                self._metadata[slug] = {
                    "tenant_id": tenant.id,
                    "updated_at": tenant.updated_at,
                    "cached_at": datetime.now(UTC),
                }

            return app

    async def invalidate(self, slug: str) -> bool:
        """Invalidate and remove a tenant sub-application from cache."""
        async with self._global_lock:
            removed = self._cache.pop(slug, None)
            self._metadata.pop(slug, None)
            self._slug_locks.pop(slug, None)
            if removed:
                logger.info(f"Invalidated tenant sub-application cache for slug='{slug}'")
                return True
            return False

    async def clear(self) -> None:
        """Clear the entire tenant sub-application cache."""
        async with self._global_lock:
            self._cache.clear()
            self._metadata.clear()
            self._slug_locks.clear()
            logger.info("Cleared all tenant sub-application caches")

    def size(self) -> int:
        """Return the current number of cached applications."""
        return len(self._cache)


tenant_app_cache = TenantAppCache()
