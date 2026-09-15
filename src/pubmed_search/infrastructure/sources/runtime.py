"""Server-owned lifecycle for external source clients.

The MCP process may host more than one server (tests, embedded deployments, or
multiple ASGI apps).  Source clients therefore cannot live in module-level
singletons: their contact identity, credentials, connection pools, and shutdown
must belong to the server that created them.

Tool-call boundaries bind a :class:`SourceRuntime` through a ``ContextVar``.
Calls made outside an MCP server receive an ambient context-local runtime, which
keeps the Python API useful without reintroducing process-global mutable client
state.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from inspect import isawaitable
from threading import RLock
from typing import TYPE_CHECKING, Any, TypeVar, cast

from pubmed_search.shared.async_utils import SharedAsyncClientRuntime

from .contact import _normalize_contact_email

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

ClientKey = tuple[object, ...]
OwnedValue = TypeVar("OwnedValue")


@dataclass(slots=True)
class SourceRuntime:
    """External-source dependencies owned by one server instance."""

    contact_email: str | None = None
    shared_http: SharedAsyncClientRuntime = field(default_factory=SharedAsyncClientRuntime)
    _clients: dict[ClientKey, Any] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.contact_email = _normalize_contact_email(self.contact_email)

    def get_or_create_client(self, key: ClientKey, factory: Callable[[], OwnedValue]) -> OwnedValue:
        """Return the client cached under *key*, creating it atomically."""
        with self._lock:
            if key not in self._clients:
                client = factory()
                self._clients[key] = client
            return cast("OwnedValue", self._clients[key])

    def cached_clients(self) -> tuple[Any, ...]:
        """Return an immutable snapshot for diagnostics and lifecycle tests."""
        with self._lock:
            return tuple(self._clients.values())

    def set_owned_value(self, key: ClientKey, value: Any) -> None:
        """Replace a runtime-owned configuration or client value."""
        with self._lock:
            self._clients[key] = value

    def discard_owned_value(self, key: ClientKey) -> Any | None:
        """Forget and return a runtime-owned value without closing it."""
        with self._lock:
            return self._clients.pop(key, None)

    def discard_namespace(self, namespace: object) -> None:
        """Forget cached values whose key starts with *namespace*."""
        with self._lock:
            for key in tuple(self._clients):
                if key and key[0] == namespace:
                    self._clients.pop(key, None)

    async def close_source_clients(self) -> None:
        """Close and forget only the source clients owned by this runtime."""
        with self._lock:
            clients = tuple(self._clients.values())
            self._clients.clear()

        seen: set[int] = set()
        for client in clients:
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            closer = getattr(client, "close", None) or getattr(client, "aclose", None)
            if not callable(closer):
                continue
            try:
                outcome = closer()
                if isawaitable(outcome):
                    await outcome
            except Exception as exc:  # pragma: no cover - defensive shutdown path
                logger.warning(
                    "Failed to close source client %s (%s)",
                    type(client).__name__,
                    type(exc).__name__,
                )

    async def close(self) -> None:
        """Close every connection pool owned by this server runtime."""
        await self.close_source_clients()
        await self.shared_http.close()


_ACTIVE_SOURCE_RUNTIME: ContextVar[SourceRuntime | None] = ContextVar(
    "pubmed_source_runtime",
    default=None,
)


def get_source_runtime() -> SourceRuntime:
    """Return the bound runtime or create an ambient context-local runtime."""
    runtime = _ACTIVE_SOURCE_RUNTIME.get()
    if runtime is None:
        runtime = SourceRuntime()
        _ACTIVE_SOURCE_RUNTIME.set(runtime)
    return runtime


@contextmanager
def bind_source_runtime(runtime: SourceRuntime) -> Iterator[None]:
    """Bind one server's source runtime for the current execution context."""
    if not isinstance(runtime, SourceRuntime):
        raise TypeError("runtime must be a SourceRuntime")
    token: Token[SourceRuntime | None] = _ACTIVE_SOURCE_RUNTIME.set(runtime)
    try:
        yield
    finally:
        _ACTIVE_SOURCE_RUNTIME.reset(token)


async def close_ambient_source_runtime() -> None:
    """Close the runtime used by direct, non-server Python API calls."""
    runtime = _ACTIVE_SOURCE_RUNTIME.get()
    if runtime is not None:
        await runtime.close()


__all__ = [
    "SourceRuntime",
    "bind_source_runtime",
    "close_ambient_source_runtime",
    "get_source_runtime",
]
