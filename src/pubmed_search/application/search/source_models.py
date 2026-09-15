"""Provider-neutral contracts for paged literature-source searches.

The application layer owns this envelope so infrastructure adapters can expose
provider DTOs without prematurely converting them into a second, lossy common
dictionary format.  Mapping a provider DTO into :class:`UnifiedArticle` remains
one explicit domain-service boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

SourceItemT = TypeVar("SourceItemT")


@dataclass(slots=True)
class SourceSearchPage(Generic[SourceItemT]):
    """One provider response page plus reproducibility and budget metadata.

    ``items`` deliberately retains provider DTOs. Callers map those DTOs exactly
    once at the explicit domain-service boundary; clients do not expose a second
    normalized-list search contract.
    """

    source: str
    items: list[SourceItemT] = field(default_factory=list)
    total: int | None = None
    next_token: str | int | None = None
    cursor: str | None = None
    query: str | None = None
    cost: float | None = None
    warnings: list[str] = field(default_factory=list)
    mode: str = "relevance"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        source: str,
        *,
        query: str | None = None,
        mode: str = "relevance",
        warning: str | None = None,
    ) -> SourceSearchPage[SourceItemT]:
        """Build an empty, typed page while retaining a diagnostic warning."""

        return cls(
            source=source,
            query=query,
            mode=mode,
            warnings=[warning] if warning else [],
        )


def coerce_optional_total(value: object) -> tuple[int | None, list[str]]:
    """Normalize provider totals without inventing a value on schema drift."""

    if value is None:
        return None, []
    if isinstance(value, bool):
        return None, ["Provider returned an invalid boolean total"]
    if isinstance(value, int) and value >= 0:
        return value, []
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if normalized.isascii() and normalized.isdecimal():
            return int(normalized), []
    return None, ["Provider returned an invalid non-negative integer total"]


__all__ = ["SourceSearchPage", "coerce_optional_total"]
