"""Global middlewares for request identification, timing, and security headers."""

import time
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import logger


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to inject Request-ID, measure processing time, and set security headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or capture request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Unhandled error for {request.method} {request.url.path} "
                f"[request_id={request_id}] duration={duration_ms:.2f}ms: {exc}"
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Inject tracing and security headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
