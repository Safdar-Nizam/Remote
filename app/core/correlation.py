"""
Correlation ID middleware.
Attaches a unique correlation_id to every request and propagates it
through structlog context vars so all downstream logs include it.
"""

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Module-level context var for non-request contexts (workers, etc.)
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the current correlation ID from context."""
    return correlation_id_ctx.get() or str(uuid.uuid4())


def set_correlation_id(cid: str) -> None:
    """Explicitly set correlation ID (used by workers processing queued messages)."""
    correlation_id_ctx.set(cid)
    structlog.contextvars.bind_contextvars(correlation_id=cid)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Reads or generates a correlation_id per request
    2. Binds it to structlog context vars
    3. Returns it in the response header
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept from caller or generate fresh
        cid = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        correlation_id_ctx.set(cid)
        structlog.contextvars.bind_contextvars(correlation_id=cid)

        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = cid

        # Clean up context after response
        structlog.contextvars.unbind_contextvars("correlation_id")
        return response
