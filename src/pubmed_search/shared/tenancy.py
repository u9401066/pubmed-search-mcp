"""Tenant identity for multi-agent deployments.

A single process can serve many agents at once over Streamable HTTP. Everything
that used to be "the current session" must therefore be scoped to *which caller
is asking*. This module owns that scope and nothing else, so any layer can read
the current tenant without depending on the transport.

Identity precedence, strongest first:

1. ``auth`` - an authenticated principal from a verified bearer token. This is
   the only source that is a real security boundary.
2. ``transport`` - the server-issued Streamable HTTP session id. It prevents
   accidental crosstalk between concurrent agents but is not an authorization
   decision, so treat it as isolation-only.
3. ``stdio`` - one caller per process; everything maps to the default tenant.

Tenant ids reach the filesystem, so :func:`normalize_tenant_id` always returns a
slug plus a digest of the raw value: sanitizing alone could let two different
principals collapse onto the same directory.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Tenant used for stdio and for unauthenticated single-user deployments.
DEFAULT_TENANT_ID = "default"

#: Subdirectory holding per-tenant storage roots.
TENANT_DIR_NAME = "tenants"

#: Where a tenant identity came from, strongest first.
TenantSource = Literal["auth", "transport", "explicit", "stdio"]

#: Identity sources stable and trustworthy enough to own persisted artifacts.
_DURABLE_SOURCES: frozenset[str] = frozenset({"auth", "explicit", "stdio"})

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 40

#: Separator between slug and digest. Slugification maps every non-alphanumeric
#: character to "-", so a "." can only come from a value we normalized already.
_DIGEST_SEPARATOR = "."
_NORMALIZED_RE = re.compile(r"^[a-z0-9-]{1,40}\.[0-9a-f]{12}$")


def normalize_tenant_id(raw: str | None) -> str:
    """Return a filesystem-safe, collision-free tenant id for *raw*.

    The function is idempotent: passing an already-normalized id returns it
    unchanged, so resolving a tenant twice cannot silently split its storage.

    Args:
        raw: Untrusted identifier such as a token subject or transport session id.

    Returns:
        ``"default"`` for empty input, otherwise a lowercase slug joined to a
        digest of the original value so distinct principals never share a
        directory after sanitization.
    """
    value = (raw or "").strip()
    if not value or value == DEFAULT_TENANT_ID:
        return DEFAULT_TENANT_ID
    if _NORMALIZED_RE.match(value):
        return value

    slug = _SLUG_RE.sub("-", value.lower()).strip("-")[:_MAX_SLUG_LENGTH]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{slug}{_DIGEST_SEPARATOR}{digest}" if slug else f"tenant{_DIGEST_SEPARATOR}{digest}"


@dataclass(frozen=True)
class TenantIdentity:
    """Who the current request belongs to.

    Attributes:
        tenant_id: Normalized identifier used for storage and quota scoping.
        principal: Raw authenticated principal, when one was presented.
        source: Where the identity came from.
    """

    tenant_id: str = DEFAULT_TENANT_ID
    principal: str | None = None
    source: TenantSource = "stdio"

    @property
    def is_authenticated(self) -> bool:
        """Return whether this identity is backed by a verified credential."""
        return self.source == "auth"

    @property
    def is_default(self) -> bool:
        """Return whether this is the shared single-user tenant."""
        return self.tenant_id == DEFAULT_TENANT_ID

    @property
    def owns_durable_storage(self) -> bool:
        """Return whether this identity may own artifacts that outlive the connection.

        A transport session id fails on both counts that matter: it changes on
        every reconnect, so the owner could never find the data again, and it is
        a client-supplied header, so it separates callers without authenticating
        them. Durable artifacts therefore need a verified principal, an operator
        override, or single-user stdio.
        """
        return self.source in _DURABLE_SOURCES

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict for logs and diagnostics."""
        return {
            "tenant_id": self.tenant_id,
            "principal": self.principal,
            "source": self.source,
            "authenticated": self.is_authenticated,
            "owns_durable_storage": self.owns_durable_storage,
        }

    @classmethod
    def for_principal(cls, principal: str, *, source: TenantSource = "auth") -> TenantIdentity:
        """Build an identity from an authenticated principal or session id."""
        return cls(tenant_id=normalize_tenant_id(principal), principal=principal, source=source)


DEFAULT_TENANT = TenantIdentity()

_current_tenant: ContextVar[TenantIdentity] = ContextVar("pubmed_current_tenant", default=DEFAULT_TENANT)


def current_tenant() -> TenantIdentity:
    """Return the tenant bound to the current request context."""
    return _current_tenant.get()


def current_tenant_id() -> str:
    """Return the normalized tenant id bound to the current request context."""
    return _current_tenant.get().tenant_id


@contextmanager
def bind_tenant(identity: TenantIdentity) -> Iterator[TenantIdentity]:
    """Bind *identity* for the duration of the block, then restore the previous one.

    Args:
        identity: The tenant to make current.

    Yields:
        The bound identity, for convenience in ``with`` statements.
    """
    token = _current_tenant.set(identity)
    try:
        yield identity
    finally:
        _current_tenant.reset(token)


def tenant_data_dir(root: str | Path | None, tenant_id: str | None = None) -> str | None:
    """Return the storage root for a tenant under *root*.

    Every store that persists under the data directory must route through this
    function, otherwise one tenant's chronicles, pipelines, or notes land in
    another tenant's space.

    Args:
        root: Configured data directory, or ``None`` when persistence is off.
        tenant_id: Tenant to resolve. When omitted the tenant bound to the
            current request is used, and a caller that may not own durable
            storage gets ``None`` so nothing reaches disk. Passing an id
            explicitly is treated as an operator decision and always resolves
            to a path.

    Returns:
        *root* itself for the default tenant, so existing single-user installs
        keep their data; ``root/tenants/<tenant_id>`` otherwise. ``None`` when
        *root* is ``None`` or the current caller is not allowed to persist.
    """
    if root is None:
        return None

    if tenant_id:
        resolved = normalize_tenant_id(tenant_id)
    else:
        identity = current_tenant()
        if not identity.owns_durable_storage:
            return None
        resolved = identity.tenant_id

    if resolved == DEFAULT_TENANT_ID:
        return str(root)
    return str(Path(root) / TENANT_DIR_NAME / resolved)


__all__ = [
    "DEFAULT_TENANT",
    "DEFAULT_TENANT_ID",
    "TENANT_DIR_NAME",
    "TenantIdentity",
    "TenantSource",
    "bind_tenant",
    "current_tenant",
    "current_tenant_id",
    "normalize_tenant_id",
    "tenant_data_dir",
]
