"""Bind a tenant to every inbound MCP request.

Installed as low-level server middleware so it wraps every request regardless of
which tool handles it, and so the binding lives in the same context as the
handler coroutine that later calls ``get_session_manager()``.

Identity is taken from the verified access token when auth is configured. That
is the only remote source that is a security boundary. Legacy HTTP session ids
are isolation-only, and modern/stateless anonymous service HTTP is request-scoped.
Explicit local mode instead binds loopback HTTP to the durable default tenant.

The same wrapper holds a per-tenant concurrency slot, so one busy agent cannot
occupy the whole upstream budget while other agents wait.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server.auth.middleware.auth_context import get_access_token

from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter
from pubmed_search.shared.async_utils import tenant_slot
from pubmed_search.shared.tenancy import (
    ANONYMOUS_HTTP_TENANT,
    DEFAULT_TENANT,
    LOCAL_HTTP_TENANT,
    TenantIdentity,
    bind_tenant,
    current_tenant,
)

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

    from pubmed_search.application.session.registry import SessionManagerRegistry

logger = logging.getLogger(__name__)

#: Header carrying the server-issued Streamable HTTP session id.
SESSION_ID_HEADER = "mcp-session-id"


def _request_headers(ctx: ServerRequestContext[Any, Any]) -> dict[str, str] | None:
    """Return lowercase request headers when the transport exposes them."""
    request = getattr(ctx, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    try:
        return {str(key).lower(): str(value) for key, value in headers.items()}
    except Exception:
        return None


def resolve_tenant(
    ctx: ServerRequestContext[Any, Any],
    *,
    isolation_enabled: bool = True,
    trusted_local_http: bool = False,
) -> TenantIdentity:
    """Resolve the tenant for one inbound request.

    Args:
        ctx: The low-level server request context.
        isolation_enabled: Whether legacy transport identifiers may isolate
            otherwise anonymous remote callers.
        trusted_local_http: Map unauthenticated HTTP to the durable default
            tenant. This is safe only for the explicit local mode, whose
            launcher enforces loopback/Host/Origin boundaries.

    Returns:
        The resolved identity. Falls back to the default tenant when no
        credential and no transport session are available (stdio).
    """
    token = get_access_token()
    principal = getattr(token, "subject", None) or getattr(token, "client_id", None) if token else None
    if principal:
        return TenantIdentity.for_principal(str(principal), source="auth")

    request = getattr(ctx, "request", None)
    if request is None:
        return DEFAULT_TENANT

    if trusted_local_http:
        return LOCAL_HTTP_TENANT

    if not isolation_enabled:
        return ANONYMOUS_HTTP_TENANT

    headers = _request_headers(ctx)
    session_id = (headers or {}).get(SESSION_ID_HEADER)
    if session_id:
        return TenantIdentity.for_principal(session_id, source="transport")

    return ANONYMOUS_HTTP_TENANT


def durable_storage_denied(tool_name: str, *, output_format: str = "markdown") -> str | None:
    """Return a formatted refusal when the caller may not own persisted data.

    Args:
        tool_name: Tool to name in the error payload.
        output_format: Response format used when access must be refused.

    Returns:
        ``None`` when the caller may persist, otherwise a formatted error.
    """
    tenant = current_tenant()
    if tenant.owns_durable_storage:
        return None

    logger.warning(
        "Refusing durable write for %s: tenant %s came from %s, which is not a security boundary",
        tool_name,
        tenant.tenant_id,
        tenant.source,
    )
    return ResponseFormatter.error(
        error="Saved research artifacts require an authenticated caller",
        suggestion=(
            "This server derives your identity from the transport session id, which changes on every "
            "reconnect and is client-supplied, so anything saved now would be unreachable later and "
            "unprotected from other callers. Ask the operator to set PUBMED_AUTH_TOKENS, or run the "
            "server locally over stdio."
        ),
        tool_name=tool_name,
        output_format=output_format,
    )


def build_tenancy_middleware(
    *,
    isolation_enabled: bool = True,
    max_concurrency: int = 0,
    registry: SessionManagerRegistry | None = None,
    trusted_local_http: bool = False,
) -> Any:
    """Build the server middleware that binds a tenant around each request.

    Args:
        isolation_enabled: Whether to derive per-caller tenants at all.
        max_concurrency: Maximum concurrent requests per tenant. Values below 1
            disable the fair-share cap.
        registry: Session-manager registry used to bind ephemeral request state.
        trusted_local_http: Whether anonymous HTTP is the trusted, durable local
            caller. Never enable this for service mode.

    Returns:
        A middleware callable suitable for ``Server.middleware.append(...)``.
    """

    async def tenancy_middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        identity = resolve_tenant(
            ctx,
            isolation_enabled=isolation_enabled,
            trusted_local_http=trusted_local_http,
        )
        with bind_tenant(identity):
            logger.debug("Handling %s for tenant %s (%s)", ctx.method, identity.tenant_id, identity.source)
            if registry is None:
                async with tenant_slot(max_concurrency, identity.tenant_id):
                    return await call_next(ctx)

            with registry.bind_request(identity):
                async with tenant_slot(max_concurrency, identity.tenant_id):
                    return await call_next(ctx)

    return tenancy_middleware


__all__ = ["SESSION_ID_HEADER", "build_tenancy_middleware", "durable_storage_denied", "resolve_tenant"]
