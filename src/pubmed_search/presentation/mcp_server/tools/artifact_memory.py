"""Helpers for persisting MCP tool output artifacts."""

from __future__ import annotations

import logging
from typing import Any, cast

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
    artifact_uri = str(manifest.get("artifact_uri") or "")
    summary = cast("dict[str, Any]", manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {})
    metadata = cast("dict[str, Any]", manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {})
    files = sorted((manifest.get("files") or {}).keys())
    read_order = [file for file in summary.get("read_order", []) if file in files]
    for file in files:
        if file not in read_order:
            read_order.append(file)

    def _read_command(file_name: str) -> str:
        if not artifact_id:
            return ""
        return f'read_session(action="artifact", artifact_id="{artifact_id}", artifact_file="{file_name}")'

    def _read_uri_command(file_name: str) -> str:
        if not artifact_uri:
            return ""
        return f'read_session(action="artifact", artifact_uri="{artifact_uri}", artifact_file="{file_name}")'

    read_files = {file_name: _read_command(file_name) for file_name in read_order if _read_command(file_name)}
    read_files_by_uri = {
        file_name: _read_uri_command(file_name) for file_name in read_order if _read_uri_command(file_name)
    }
    audit_summary = cast("dict[str, Any]", summary.get("audit") if isinstance(summary.get("audit"), dict) else {})
    locator: dict[str, Any] = {
        "artifact_id": artifact_id,
        "session_id": manifest.get("session_id"),
        "artifact_uri": artifact_uri,
        "tool": manifest.get("tool"),
        "kind": manifest.get("kind"),
        "primary_file": primary_file,
        "size_bytes": manifest.get("size_bytes"),
        "schema_version": metadata.get("schema_version") or summary.get("schema_version"),
        "audit_status": summary.get("audit_status") or audit_summary.get("status"),
        "summary": summary,
        "files": files,
        "read_order": read_order,
        "read_files": read_files,
        "read_files_by_uri": read_files_by_uri,
        "remote_retrieval": {
            "artifact_uri": artifact_uri,
            "file_parameter": "artifact_file",
            "offset_parameter": "offset",
            "max_chars_parameter": "max_chars",
            "supports_paging": True,
            "read_via": _read_uri_command(primary_file) if primary_file else "",
        },
        "read_via_uri": _read_uri_command(primary_file) if primary_file else "",
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

    read_order = artifact.get("read_order") or artifact.get("files") or []
    audit_status = artifact.get("audit_status") or "unknown"
    uri_start = (artifact.get("read_files_by_uri") or {}).get("audit.json") or artifact.get("read_via_uri", "")
    id_start = (artifact.get("read_files") or {}).get("audit.json") or artifact.get("read_via", "")
    lines = [
        "",
        "---",
        "## Persistent Artifact",
        "",
        f"- Artifact ID: `{artifact.get('artifact_id', '')}`",
        f"- URI: `{artifact.get('artifact_uri', '')}`",
        f"- Audit status: `{audit_status}`",
        f"- Files: {', '.join(f'`{file}`' for file in read_order)}",
        "",
        "The response above is a compact summary. Use artifact files for the full result list, query strategy, and audit.",
    ]
    if uri_start:
        lines.append(f"- Start with URI: `{uri_start}`")
    if id_start:
        lines.append(f"- Start with ID: `{id_start}`")
    if artifact.get("local_path"):
        lines.insert(5, f"- Local file: `{artifact.get('local_path', '')}`")
    if artifact.get("manifest_path"):
        lines.insert(6 if artifact.get("local_path") else 5, f"- Manifest: `{artifact.get('manifest_path', '')}`")
    return "\n".join(lines)
