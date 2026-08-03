"""Bearer-token guard and tenant resolution for the auxiliary HTTP API.

The MCP endpoint is protected by the SDK's auth layer, but the auxiliary
read-only routes (`/api/cached_article`, `/api/session/summary`, ...) are plain
Starlette routes and would otherwise be reachable by anyone who can hit the
port. This module applies the same static tokens to them and resolves the
caller's tenant so one agent cannot read another's cache.

When no tokens are configured the guard allows every caller and maps them to the
default tenant, which keeps single-user local deployments working unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pubmed_search.shared.tenancy import DEFAULT_TENANT, TenantIdentity

if TYPE_CHECKING:
    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.application.session.registry import SessionManagerRegistry
    from pubmed_search.infrastructure.auth import StaticTokenVerifier

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "bearer "


@dataclass(frozen=True)
class AuthOutcome:
    """Result of guarding one auxiliary HTTP request.

    Attributes:
        identity: The resolved tenant, or ``None`` when the request is rejected.
        status_code: HTTP status to return when ``identity`` is ``None``.
        detail: Error message to return when ``identity`` is ``None``.
    """

    identity: TenantIdentity | None
    status_code: int = 401
    detail: str = "Unauthorized"

    @property
    def allowed(self) -> bool:
        """Return whether the request may proceed."""
        return self.identity is not None


class AuxiliaryApiGuard:
    """Authenticate auxiliary HTTP requests and resolve their tenant."""

    def __init__(
        self,
        *,
        verifier: StaticTokenVerifier | None,
        registry: SessionManagerRegistry,
        require_auth: bool = False,
    ) -> None:
        """Create the guard.

        Args:
            verifier: Token verifier, or ``None`` for an open deployment.
            registry: Per-tenant session manager registry.
            require_auth: Reject unauthenticated requests even when no verifier
                is configured. Use this to fail closed on misconfiguration.
        """
        self._verifier = verifier
        self._registry = registry
        self._require_auth = require_auth

    @property
    def enforcing(self) -> bool:
        """Return whether requests must present a valid bearer token."""
        return self._verifier is not None or self._require_auth

    @property
    def registry(self) -> SessionManagerRegistry:
        """Return the per-tenant session manager registry."""
        return self._registry

    async def authenticate(self, request: Any) -> AuthOutcome:
        """Authenticate *request* and resolve its tenant.

        Args:
            request: The Starlette request.

        Returns:
            An :class:`AuthOutcome` carrying the tenant, or the rejection reason.
        """
        if self._verifier is None:
            if self._require_auth:
                return AuthOutcome(None, 503, "Auth is required but no tokens are configured")
            return AuthOutcome(DEFAULT_TENANT)

        header = str(request.headers.get("authorization", "")).strip()
        if not header.lower().startswith(_BEARER_PREFIX):
            return AuthOutcome(None, 401, "Missing bearer token")

        token = await self._verifier.verify_token(header[len(_BEARER_PREFIX) :].strip())
        if token is None:
            return AuthOutcome(None, 403, "Invalid bearer token")

        principal = token.subject or token.client_id
        return AuthOutcome(TenantIdentity.for_principal(str(principal), source="auth"))

    def session_manager_for(self, identity: TenantIdentity) -> SessionManager:
        """Return the session manager owned by *identity*."""
        return self._registry.for_tenant(identity.tenant_id)


__all__ = ["AuthOutcome", "AuxiliaryApiGuard"]
