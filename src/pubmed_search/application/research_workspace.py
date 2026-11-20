"""Record an agent's literature research as a resumable, linked workspace."""

from __future__ import annotations

import re
from typing import Any, Protocol

from pubmed_search.application.workspace_handoff import source_handoffs
from pubmed_search.shared.credential_sanitizer import contains_credential_material

ACTIVITIES = ("explore", "expand", "examine", "explain")
_SCOPES = ("none", "metadata", "abstract", "fulltext")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
_MAX_CURSOR = (1 << 63) - 1


class ResearchWorkspaceStore(Protocol):
    def create(self, workspace_id: str, question: str) -> dict[str, Any]: ...

    def append(self, workspace_id: str, record: dict[str, Any]) -> dict[str, Any]: ...

    def read(self, workspace_id: str, after: int | None, limit: int, open_offset: int) -> dict[str, Any]: ...

    def list_workspaces(self, offset: int, limit: int) -> dict[str, Any]: ...


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(
            f"{field} must be a stable identifier of 1 to 96 letters, digits, underscores, dots or hyphens"
        )
    return value


def _text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\0" in value:
        raise ValueError(f"{field} must contain 1 to {maximum} characters")
    if contains_credential_material(value):
        raise ValueError(f"{field} contains credential material")
    return value.strip()


def _references(values: list[str] | None, field: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 32:
        raise ValueError(f"{field} must be an array of up to 32 references")
    result = []
    for raw in values:
        if field == "source_refs":
            value = _text(raw, field, 512)
            namespace, _, reference = value.partition(":")
            if not _NAMESPACE.fullmatch(namespace) or not reference.strip() or not value.isprintable():
                raise ValueError("source_refs need a namespace and identifier, such as pmid:3878092")
            value = f"{namespace.lower()}:{reference.strip()}"
        else:
            value = _identifier(raw, field)
        if value not in result:
            result.append(value)
    return result


def _page_number(value: int, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


class ResearchWorkspaceService:
    """Accept explicit research decisions and their sources in any activity order."""

    def __init__(self, store: ResearchWorkspaceStore) -> None:
        self._store = store

    def create(self, workspace_id: str, question: str) -> dict[str, Any]:
        return self._store.create(_identifier(workspace_id, "workspace_id"), _text(question, "question", 2000))

    def list_workspaces(self, *, offset: int = 0, limit: int = 25) -> dict[str, Any]:
        return self._store.list_workspaces(
            _page_number(offset, "offset", 0, _MAX_CURSOR), _page_number(limit, "limit", 1, 100)
        )

    def read(
        self, workspace_id: str, *, after: int | None = None, limit: int = 25, open_offset: int = 0
    ) -> dict[str, Any]:
        workspace = self._store.read(
            _identifier(workspace_id, "workspace_id"),
            None if after is None else _page_number(after, "after", 0, _MAX_CURSOR),
            _page_number(limit, "limit", 1, 100),
            _page_number(open_offset, "open_offset", 0, _MAX_CURSOR),
        )
        for item in (*workspace["records"], *workspace["open_actions"]):
            item["source_handoffs"] = source_handoffs(item["source_refs"])
        return workspace

    def record(
        self,
        workspace_id: str,
        record_id: str,
        activity: str,
        note: str,
        *,
        source_refs: list[str] | None = None,
        evidence_scope: str = "none",
        locator: str | None = None,
        parent_ids: list[str] | None = None,
        next_action: str | None = None,
        resolves: list[str] | None = None,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Append one immutable observation or decision. Its ID is also its retry key."""
        _identifier(workspace_id, "workspace_id")
        _identifier(record_id, "record_id")
        if activity not in ACTIVITIES:
            raise ValueError(f"activity must be one of {', '.join(ACTIVITIES)}")
        if evidence_scope not in _SCOPES:
            raise ValueError(f"evidence_scope must be one of {', '.join(_SCOPES)}")
        if actor not in ("agent", "human"):
            raise ValueError("actor must be agent or human")
        refs = _references(source_refs, "source_refs")
        if evidence_scope != "none" and not refs:
            raise ValueError("An evidence scope requires at least one source reference")
        if evidence_scope == "fulltext" and locator is None:
            raise ValueError("Full-text evidence requires a passage locator")
        if locator is not None and evidence_scope == "none":
            raise ValueError("A passage locator requires an evidence scope")
        record = {
            "record_id": record_id,
            "activity": activity,
            "note": _text(note, "note", 4000),
            "source_refs": refs,
            "evidence_scope": evidence_scope,
            "locator": None if locator is None else _text(locator, "locator", 1000),
            "parent_ids": _references(parent_ids, "parent_ids"),
            "next_action": None if next_action is None else _text(next_action, "next_action", 1000),
            "resolves": _references(resolves, "resolves"),
            "actor": actor,
            "verification_status": "unverified",
        }
        return self._store.append(workspace_id, record)
