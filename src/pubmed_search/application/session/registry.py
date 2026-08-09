"""Per-tenant session manager pool.

:class:`~pubmed_search.application.session.manager.SessionManager` keeps a single
"current session" in memory, so one shared instance makes concurrent agents read
each other's cached articles, search history, ``pmids="last"``, and artifacts.
This registry gives every tenant its own manager and its own storage root.

The default tenant deliberately keeps writing to ``data_dir`` itself so existing
single-user installs keep their history after upgrading; additional tenants get
``data_dir/tenants/<tenant_id>``.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from pubmed_search.shared.tenancy import (
    DEFAULT_TENANT_ID,
    TENANT_DIR_NAME,
    current_tenant,
    normalize_tenant_id,
    tenant_data_dir,
)

from .manager import SessionManager

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from pubmed_search.shared.tenancy import TenantIdentity

logger = logging.getLogger(__name__)


class SessionManagerRegistry:
    """Resolve a :class:`SessionManager` per tenant, creating one on first use."""

    def __init__(
        self,
        data_dir: str | Path | None,
        *,
        factory: Callable[[str | None], SessionManager] | None = None,
        default_manager: SessionManager | None = None,
    ) -> None:
        """Create the registry.

        Args:
            data_dir: Root directory for session persistence, or ``None`` for
                in-memory sessions (tests, ephemeral deployments).
            factory: Builds a manager for a resolved data directory. Injectable
                so tests can substitute a fake without touching the filesystem.
            default_manager: Existing manager for the durable default tenant.
                This lets the MCP registry reuse the DI container singleton
                instead of opening the same persistence root twice.
        """
        self._data_dir = str(data_dir) if data_dir else None
        self._factory = factory or (lambda path: SessionManager(data_dir=path))
        self._default_manager = default_manager
        self._managers: dict[str, SessionManager] = {}
        self._lock = threading.RLock()
        self._request_manager: ContextVar[SessionManager | None] = ContextVar(
            f"pubmed_ephemeral_session_manager_{id(self)}",
            default=None,
        )

    @property
    def data_dir(self) -> str | None:
        """Return the configured root data directory."""
        return self._data_dir

    def tenant_data_dir(self, tenant_id: str) -> str | None:
        """Return the storage root for *tenant_id*.

        Args:
            tenant_id: A normalized tenant id.

        Returns:
            The default tenant keeps the shared root for backward compatibility;
            every other tenant gets an isolated subdirectory. ``None`` when the
            registry runs without persistence.
        """
        return tenant_data_dir(self._data_dir, tenant_id)

    def for_tenant(self, tenant_id: str | None = None) -> SessionManager:
        """Return the session manager for *tenant_id*, creating it if needed.

        Args:
            tenant_id: Tenant to resolve. Defaults to the tenant bound to the
                current request context. A caller whose identity cannot own
                durable storage gets an in-memory manager, so reconnecting
                does not leave an unreachable directory behind on every attempt.

        Returns:
            A manager private to that tenant.
        """
        if tenant_id:
            resolved = normalize_tenant_id(tenant_id)
            storage_root = self.tenant_data_dir(resolved)
        else:
            identity = current_tenant()
            resolved = identity.tenant_id
            if not identity.owns_durable_storage:
                request_manager = self._request_manager.get()
                if request_manager is not None:
                    return request_manager
                # Defensive fallback for direct calls outside the MCP middleware:
                # remain in-memory and, crucially, never populate the registry.
                return self._factory(None)
            storage_root = self.tenant_data_dir(resolved)

        with self._lock:
            manager = self._managers.get(resolved)
            if manager is None:
                manager = (
                    self._default_manager
                    if resolved == DEFAULT_TENANT_ID and self._default_manager is not None
                    else self._factory(storage_root)
                )
                self._managers[resolved] = manager
                logger.info(
                    "Created %s session manager for tenant %s",
                    "persistent" if storage_root else "in-memory",
                    resolved,
                )
            return manager

    @contextmanager
    def bind_request(self, identity: TenantIdentity) -> Iterator[SessionManager | None]:
        """Bind one non-durable session manager for the current request.

        Authenticated and local stdio callers use the normal memoized registry.
        Anonymous/transport-derived callers instead receive one fresh in-memory
        manager for this request only; it is discarded when middleware exits.
        """
        if identity.owns_durable_storage:
            yield None
            return

        token = self._request_manager.set(self._factory(None))
        try:
            yield self._request_manager.get()
        finally:
            self._request_manager.reset(token)

    def known_tenants(self) -> list[str]:
        """Return tenant ids that have an active session manager."""
        with self._lock:
            return sorted(self._managers)

    def stats(self) -> dict[str, object]:
        """Return a diagnostics snapshot for health and readiness endpoints."""
        with self._lock:
            tenants = sorted(self._managers)
            return {
                "data_dir": self._data_dir,
                "active_tenants": len(tenants),
                "tenants": tenants,
            }


__all__ = ["TENANT_DIR_NAME", "SessionManagerRegistry"]
