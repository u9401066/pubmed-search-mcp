"""Select structured evidence without substituting abstracts for missing sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SectionSelection:
    """Selection facts remain separate from upstream coverage and rendered text."""

    status: Literal["not_requested", "matched", "partial", "not_found", "unavailable"]
    requested: tuple[str, ...]
    available: tuple[str, ...]
    unmatched: tuple[str, ...]
    sections: tuple[dict[str, Any], ...]

    @property
    def body_available(self) -> bool:
        return bool(self.available)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requested": list(self.requested),
            "available": list(self.available),
            "unmatched": list(self.unmatched),
        }


def select_sections(parsed: dict[str, Any], sections_filter: str | None) -> SectionSelection:
    """Keep existing case-insensitive title matching, with explicit missing evidence."""
    available = tuple(section for section in parsed.get("sections", []) if str(section.get("content") or "").strip())
    titles = tuple(str(section.get("title") or "Body").strip() or "Body" for section in available)
    requested = tuple(
        dict.fromkeys(part.strip().lower() for part in (sections_filter or "").split(",") if part.strip())
    )

    def matches(request: str, title: str) -> bool:
        return request in title.lower() or title.lower() in request

    selected = tuple(
        section
        for section, title in zip(available, titles)
        if not requested or any(matches(request, title) for request in requested)
    )
    unmatched = tuple(request for request in requested if not any(matches(request, title) for title in titles))
    status: Literal["not_requested", "matched", "partial", "not_found", "unavailable"]
    if not available:
        status = "unavailable"
    elif not requested:
        status = "not_requested"
    elif not selected:
        status = "not_found"
    else:
        status = "partial" if unmatched else "matched"
    return SectionSelection(status, requested, titles, unmatched, selected)
