"""Helpers for persisting MCP tool output artifacts."""

from __future__ import annotations

import logging
from typing import Any

from pubmed_search.shared.settings import load_settings

from ._common import get_session_manager

logger = logging.getLogger(__name__)


def artifact_persistence_enabled() -> bool:
    """Return whether a session manager is available for artifact persistence."""
    return get_session_manager() is not None


def artifact_locator(
    manifest: dict[str, Any] | None,
    *,
    include_local_paths: bool = False,
) -> dict[str, Any] | None:
    """Return the compact artifact locator suitable for tool responses."""
    if not manifest:
        return None

    primary_file = str(manifest.get("primary_file") or "")
    artifact_id = str(manifest.get("artifact_id") or "")
    locator: dict[str, Any] = {
        "artifact_id": artifact_id,
        "session_id": manifest.get("session_id"),
        "artifact_uri": manifest.get("artifact_uri"),
        "tool": manifest.get("tool"),
        "kind": manifest.get("kind"),
        "primary_file": primary_file,
        "size_bytes": manifest.get("size_bytes"),
        "summary": manifest.get("summary") or {},
        "files": sorted((manifest.get("files") or {}).keys()),
        "read_via": (
            f'read_session(action="artifact", artifact_id="{artifact_id}", artifact_file="{primary_file}")'
            if artifact_id and primary_file
            else ""
        ),
    }
    if include_local_paths:
        locator["local_path"] = manifest.get("local_path")
        locator["manifest_path"] = manifest.get("manifest_path")
    return {key: value for key, value in locator.items() if value not in (None, "", [])}


def persist_tool_artifact(
    *,
    tool: str,
    kind: str,
    files: dict[str, Any],
    primary_file: str,
    summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a tool artifact through the active session manager if available."""
    session_manager = get_session_manager()
    if session_manager is None:
        return None

    try:
        manifest = session_manager.save_artifact(
            tool=tool,
            kind=kind,
            files=files,
            primary_file=primary_file,
            summary=summary,
            metadata=metadata,
        )
        settings = load_settings()
        return artifact_locator(manifest, include_local_paths=settings.artifact_include_local_paths)
    except Exception as exc:
        logger.warning("Failed to persist %s artifact: %s", tool, exc)
        return None


def artifact_markdown_note(artifact: dict[str, Any] | None) -> str:
    """Render a compact local-first artifact note for markdown responses."""
    if not artifact:
        return ""

    lines = [
        "",
        "---",
        "## Persistent Artifact",
        "",
        f"- Artifact ID: `{artifact.get('artifact_id', '')}`",
        f"- URI: `{artifact.get('artifact_uri', '')}`",
        "",
        'Use `read_session(action="artifact", artifact_id="...")` to retrieve the saved content.',
    ]
    if artifact.get("local_path"):
        lines.insert(5, f"- Local file: `{artifact.get('local_path', '')}`")
    if artifact.get("manifest_path"):
        lines.insert(6 if artifact.get("local_path") else 5, f"- Manifest: `{artifact.get('manifest_path', '')}`")
    return "\n".join(lines)
