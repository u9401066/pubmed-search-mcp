"""Tenant-scoped citation export artifacts."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from pubmed_search.shared.file_io import atomic_write_text
from pubmed_search.shared.tenancy import TenantIdentity, tenant_data_dir

EXPORTS_DIR_NAME = "exports"
_EXPORT_ID_RE = re.compile(r"^[0-9a-f]{32}\.(?:bib|csv|json|ris|txt)$")


def tenant_export_root(data_dir: str | Path | None, identity: TenantIdentity) -> Path | None:
    """Return the export root owned by a durable identity."""
    if not identity.owns_durable_storage:
        return None
    scoped_root = tenant_data_dir(data_dir, identity.tenant_id)
    return Path(scoped_root) / EXPORTS_DIR_NAME if scoped_root else None


def write_export_artifact(content: str, *, extension: str, root: Path) -> tuple[str, Path]:
    """Write an export under *root* and return its opaque id and path."""
    normalized_extension = extension.strip().lower().lstrip(".")
    if normalized_extension not in {"bib", "csv", "json", "ris", "txt"}:
        normalized_extension = "txt"
    export_id = f"{uuid.uuid4().hex}.{normalized_extension}"
    root.mkdir(parents=True, exist_ok=True)
    path = root / export_id
    atomic_write_text(path, content)
    return export_id, path


def resolve_export_artifact(root: Path, export_id: str) -> Path | None:
    """Resolve an opaque export id without allowing traversal or symlinks."""
    if Path(export_id).name != export_id or not _EXPORT_ID_RE.fullmatch(export_id):
        return None

    root_resolved = root.resolve()
    candidate = root / export_id
    if candidate.is_symlink():
        return None
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
        return None
    return resolved


def list_export_artifacts(root: Path) -> list[dict[str, int | str]]:
    """List safe artifacts under *root* without exposing filesystem paths."""
    if not root.exists():
        return []

    artifacts: list[dict[str, int | str]] = []
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file() or not _EXPORT_ID_RE.fullmatch(entry.name):
            continue
        artifacts.append({"export_id": entry.name, "size_bytes": entry.stat().st_size})
    return sorted(artifacts, key=lambda item: str(item["export_id"]))


__all__ = [
    "EXPORTS_DIR_NAME",
    "list_export_artifacts",
    "resolve_export_artifact",
    "tenant_export_root",
    "write_export_artifact",
]
