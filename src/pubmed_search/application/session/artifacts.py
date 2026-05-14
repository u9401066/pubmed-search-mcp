"""Persistent artifacts for large MCP tool outputs.

Artifacts are local files plus a small manifest.  Session state stores only
manifests, while the potentially large payloads remain on disk under a managed
root directory.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    token = token.strip("._-")
    return token[:80] or "artifact"


def _serialize_content(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")


class ArtifactStore:
    """Write and read local MCP output artifacts under one root."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        session_id: str,
        tool: str,
        kind: str,
        files: dict[str, Any],
        primary_file: str,
        summary: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not files:
            msg = "Artifact must contain at least one file"
            raise ValueError(msg)
        if primary_file not in files:
            msg = f"primary_file must be one of files: {primary_file}"
            raise ValueError(msg)

        safe_session = _safe_token(session_id)
        safe_tool = _safe_token(tool)
        safe_kind = _safe_token(kind)
        created_at = _utcnow_iso()
        seed = json.dumps(
            {
                "session_id": session_id,
                "tool": tool,
                "kind": kind,
                "created_at": created_at,
                "files": sorted(files),
            },
            sort_keys=True,
        ).encode("utf-8")
        artifact_id = f"{safe_tool}_{safe_kind}_{hashlib.sha256(seed).hexdigest()[:16]}"
        artifact_dir = self._resolve_under_root(safe_session, safe_tool, safe_kind, artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        file_manifests: dict[str, dict[str, Any]] = {}
        primary_sha = ""
        primary_size = 0
        for file_name, content in files.items():
            self._validate_file_name(file_name)
            data = _serialize_content(content)
            file_path = (artifact_dir / file_name).resolve()
            self._assert_under(file_path, artifact_dir)
            file_path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            file_manifests[file_name] = {
                "path": str(file_path),
                "size_bytes": len(data),
                "sha256": digest,
            }
            if file_name == primary_file:
                primary_sha = digest
                primary_size = len(data)

        manifest_path = artifact_dir / "manifest.json"
        manifest: dict[str, Any] = {
            "artifact_id": artifact_id,
            "session_id": session_id,
            "tool": tool,
            "kind": kind,
            "created_at": created_at,
            "artifact_uri": f"artifact://{safe_session}/{artifact_id}",
            "root_path": str(artifact_dir),
            "manifest_path": str(manifest_path.resolve()),
            "local_path": file_manifests[primary_file]["path"],
            "primary_file": primary_file,
            "size_bytes": primary_size,
            "sha256": primary_sha,
            "files": file_manifests,
            "summary": summary or {},
            "metadata": metadata or {},
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def read_file(self, manifest: dict[str, Any], file_name: str | None = None) -> tuple[dict[str, Any], str]:
        files = manifest.get("files")
        if not isinstance(files, dict):
            msg = "Artifact manifest has no files index"
            raise TypeError(msg)

        selected = file_name or str(manifest.get("primary_file") or "")
        if selected not in files:
            msg = f"Artifact file not found: {selected}"
            raise FileNotFoundError(msg)

        file_info = files[selected]
        if not isinstance(file_info, dict):
            msg = f"Malformed artifact file entry: {selected}"
            raise TypeError(msg)

        root_path = Path(str(manifest.get("root_path") or "")).resolve()
        self._assert_under(root_path, self.root_dir)
        file_path = Path(str(file_info.get("path") or "")).resolve()
        self._assert_under(file_path, root_path)
        data = file_path.read_bytes()
        expected_sha = str(file_info.get("sha256") or "")
        if not _SHA256_RE.fullmatch(expected_sha):
            msg = f"Artifact checksum missing or invalid: {selected}"
            raise ValueError(msg)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            msg = f"Artifact checksum mismatch: {selected}"
            raise ValueError(msg)
        return file_info, data.decode("utf-8")

    def _resolve_under_root(self, *parts: str) -> Path:
        path = self.root_dir.joinpath(*parts).resolve()
        self._assert_under(path, self.root_dir)
        return path

    @staticmethod
    def _validate_file_name(file_name: str) -> None:
        if not _SAFE_FILE_RE.match(file_name):
            msg = f"Unsafe artifact file name: {file_name}"
            raise ValueError(msg)

    @staticmethod
    def _assert_under(path: Path, root: Path) -> None:
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            msg = f"Artifact path escapes root: {path}"
            raise ValueError(msg) from exc
