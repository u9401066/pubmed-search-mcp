"""Tenant identity for multi-agent deployments.

A single process can serve many agents at once over Streamable HTTP. Everything
that used to be "the current session" must therefore be scoped to *which caller
is asking*. This module owns that scope and nothing else, so any layer can read
the current tenant without depending on the transport.

Identity precedence, strongest first:

1. ``auth`` - an authenticated principal from a verified bearer token. This is
   the only source that is a real security boundary.
2. ``transport`` - a legacy Streamable HTTP session id. It prevents accidental
   crosstalk but is client-supplied and not an authorization decision.
3. ``local_http`` - trusted loopback HTTP in explicit single-user local mode;
   it shares the durable default store but is distinct from stdio for responses.
4. ``anonymous_http`` - modern/stateless HTTP without a verified principal.
   It is request-scoped and may never own persisted data.
5. ``stdio`` - one local caller per process; everything maps to the default tenant.

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

#: Stable diagnostic id for anonymous HTTP. Its session manager is request-scoped,
#: so this identifier is never a key in the persistent registry cache.
ANONYMOUS_HTTP_TENANT_ID = "anonymous-http"

#: Subdirectory holding per-tenant storage roots.
TENANT_DIR_NAME = "tenants"

#: Where a tenant identity came from, strongest first.
TenantSource = Literal["auth", "transport", "local_http", "anonymous_http", "explicit", "stdio"]

#: Identity sources stable and trustworthy enough to own persisted artifacts.
_DURABLE_SOURCES: frozenset[str] = frozenset({"auth", "local_http", "explicit", "stdio"})

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 40

#: Separator between slug and digest.
_DIGEST_SEPARATOR = "."


class _NormalizedTenantId(str):
    """Opaque marker for ids normalized inside this process.

    A textual shape cannot prove that a value has already been normalized: an
    untrusted principal can deliberately choose that same shape.  Keeping the
    marker in the string's runtime type preserves idempotency for internal
    re-resolution without granting raw principals a collision primitive.
    """

    __slots__ = ()


def normalize_tenant_id(raw: str | None, *, allow_default: bool = True) -> str:
    """Return a filesystem-safe, collision-free tenant id for *raw*.

    The function is idempotent for values it previously returned.  It does not
    infer that status from a caller-controlled string pattern, because a raw
    principal could otherwise impersonate another principal's normalized id.

    Args:
        raw: Untrusted identifier such as a token subject or transport session id.
        allow_default: Preserve the reserved local ``default`` tenant.  Remote
            principal construction disables this so an authenticated subject
            named ``default`` cannot enter the single-user storage root.

    Returns:
        ``"default"`` for empty input when ``allow_default`` is enabled,
        otherwise a lowercase slug joined to a digest of the original value so
        distinct principals never share a directory after sanitization.
    """
    if isinstance(raw, _NormalizedTenantId):
        return raw

    value = (raw or "").strip()
    if allow_default and (not value or value == DEFAULT_TENANT_ID):
        return DEFAULT_TENANT_ID

    slug = _SLUG_RE.sub("-", value.lower()).strip("-")[:_MAX_SLUG_LENGTH]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    normalized = f"{slug}{_DIGEST_SEPARATOR}{digest}" if slug else f"tenant{_DIGEST_SEPARATOR}{digest}"
    return _NormalizedTenantId(normalized)


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
        return cls(
            tenant_id=normalize_tenant_id(principal, allow_default=False),
            principal=principal,
            source=source,
        )


DEFAULT_TENANT = TenantIdentity()
LOCAL_HTTP_TENANT = TenantIdentity(source="local_http")
ANONYMOUS_HTTP_TENANT = TenantIdentity(
    tenant_id=ANONYMOUS_HTTP_TENANT_ID,
    principal=None,
    source="anonymous_http",
)

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
    "ANONYMOUS_HTTP_TENANT",
    "ANONYMOUS_HTTP_TENANT_ID",
    "DEFAULT_TENANT",
    "DEFAULT_TENANT_ID",
    "LOCAL_HTTP_TENANT",
    "TENANT_DIR_NAME",
    "TenantIdentity",
    "TenantSource",
    "bind_tenant",
    "current_tenant",
    "current_tenant_id",
    "normalize_tenant_id",
    "tenant_data_dir",
]
