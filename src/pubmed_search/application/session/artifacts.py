"""Persistent artifacts for large MCP tool outputs.

Artifacts are local files plus a small manifest.  Session state stores only
manifests, while the potentially large payloads remain on disk under a managed
root directory.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pubmed_search.shared.credential_sanitizer import is_credential_field, redact_credential_assignments

_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    token = token.strip("._-")
    return token[:80] or "artifact"


def _redact_artifact_text(value: str) -> str:
    return redact_credential_assignments(value)


def _sanitize_artifact_value(value: Any) -> Any:
    """Remove credentials at the final durable artifact boundary."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if is_credential_field(str(key)) else _sanitize_artifact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_artifact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_artifact_text(value)
    return value


def _serialize_content(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    content = _sanitize_artifact_value(content)
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
        for file_name in files:
            self._validate_file_name(file_name)

        created_at = _utcnow_iso()
        artifact_id = uuid.uuid4().hex
        artifact_parent = self._resolve_under_root(safe_session, safe_tool, safe_kind)
        artifact_parent.mkdir(parents=True, exist_ok=True)
        artifact_dir = self._resolve_under_root(safe_session, safe_tool, safe_kind, artifact_id)
        staging_dir = Path(
            tempfile.mkdtemp(
                dir=artifact_parent,
                prefix=f".{artifact_id}.",
                suffix=".staging",
            )
        ).resolve()
        self._assert_under(staging_dir, artifact_parent)

        try:
            file_manifests: dict[str, dict[str, Any]] = {}
            primary_sha = ""
            primary_size = 0
            for file_name, content in files.items():
                data = _serialize_content(content)
                staging_path = (staging_dir / file_name).resolve()
                self._assert_under(staging_path, staging_dir)
                with staging_path.open("wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())

                published_path = (artifact_dir / file_name).resolve()
                self._assert_under(published_path, artifact_dir)
                digest = hashlib.sha256(data).hexdigest()
                file_manifests[file_name] = {
                    "path": str(published_path),
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
                "summary": _sanitize_artifact_value(summary or {}),
                "metadata": _sanitize_artifact_value(metadata or {}),
            }
            staging_manifest = staging_dir / "manifest.json"
            with staging_manifest.open("w", encoding="utf-8", newline="") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())

            # The final directory name is never visible until every payload and
            # the manifest are complete. UUID identity makes a destination
            # collision practically impossible without relying on wall clock.
            staging_dir.replace(artifact_dir)
            return manifest
        except BaseException:
            self._cleanup_staging_dir(staging_dir, artifact_parent)
            raise

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

    def discover(self, *, session_id: str) -> list[dict[str, Any]]:
        """Return fully published manifests that belong to *session_id*.

        Session indexing intentionally happens after an artifact directory is
        atomically published.  A process crash (or a full disk while updating
        the session JSON) can therefore leave a valid artifact that is not yet
        referenced by the session aggregate.  Discovery is the recovery side
        of that publication protocol: only complete, structurally consistent
        manifests under the expected session subtree are returned.
        """
        safe_session = _safe_token(session_id)
        if safe_session != session_id:
            msg = f"Unsafe artifact session id: {session_id}"
            raise ValueError(msg)

        session_root = self._resolve_under_root(safe_session)
        if not session_root.is_dir():
            return []

        manifests: list[dict[str, Any]] = []
        # The fixed tool/kind/artifact hierarchy avoids following arbitrary
        # recursive layouts while still supporting every current artifact.
        for manifest_path in sorted(session_root.glob("*/*/*/manifest.json")):
            resolved_manifest = manifest_path.resolve()
            self._assert_under(resolved_manifest, session_root)
            try:
                raw = json.loads(resolved_manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or raw.get("session_id") != session_id:
                continue

            artifact_dir = resolved_manifest.parent
            artifact_id = artifact_dir.name
            if raw.get("artifact_id") != artifact_id:
                continue
            if raw.get("artifact_uri") != f"artifact://{safe_session}/{artifact_id}":
                continue
            try:
                declared_root = Path(str(raw.get("root_path") or "")).resolve()
                declared_manifest = Path(str(raw.get("manifest_path") or "")).resolve()
                self._assert_under(declared_root, session_root)
                self._assert_under(declared_manifest, declared_root)
            except (OSError, ValueError):
                continue
            if declared_root != artifact_dir or declared_manifest != resolved_manifest:
                continue

            files = raw.get("files")
            primary_file = raw.get("primary_file")
            if not isinstance(files, dict) or not isinstance(primary_file, str) or primary_file not in files:
                continue
            primary_info = files.get(primary_file)
            if (
                not isinstance(primary_info, dict)
                or raw.get("sha256") != primary_info.get("sha256")
                or raw.get("size_bytes") != primary_info.get("size_bytes")
            ):
                continue
            valid = True
            for file_name, file_info in files.items():
                if not isinstance(file_name, str) or not isinstance(file_info, dict):
                    valid = False
                    break
                try:
                    file_path = Path(str(file_info.get("path") or "")).resolve()
                    self._assert_under(file_path, artifact_dir)
                except (OSError, ValueError):
                    valid = False
                    break
                checksum = str(file_info.get("sha256") or "")
                if not file_path.is_file() or _SHA256_RE.fullmatch(checksum) is None:
                    valid = False
                    break
            if valid:
                manifests.append(raw)

        manifests.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("artifact_id") or "")))
        return manifests

    def _resolve_under_root(self, *parts: str) -> Path:
        path = self.root_dir.joinpath(*parts).resolve()
        self._assert_under(path, self.root_dir)
        return path

    @staticmethod
    def _validate_file_name(file_name: str) -> None:
        if not _SAFE_FILE_RE.match(file_name):
            msg = f"Unsafe artifact file name: {file_name}"
            raise ValueError(msg)

    @classmethod
    def _cleanup_staging_dir(cls, staging_dir: Path, artifact_parent: Path) -> None:
        """Remove a failed private staging tree after validating its scope."""
        cls._assert_under(staging_dir, artifact_parent)
        if not staging_dir.name.startswith(".") or not staging_dir.name.endswith(".staging"):
            return
        with contextlib.suppress(OSError):
            shutil.rmtree(staging_dir)

    @staticmethod
    def _assert_under(path: Path, root: Path) -> None:
        def _canonical(candidate: Path) -> Path:
            resolved = str(candidate.resolve())
            if os.name == "nt":
                # Concurrent Windows resolution can return the same path in
                # extended-length form (\\?\C:\...) for one thread and normal
                # drive form for another. Normalize that namespace before the
                # containment check without weakening symlink resolution.
                if resolved.startswith("\\\\?\\UNC\\"):
                    resolved = f"\\\\{resolved[8:]}"
                elif resolved.startswith("\\\\?\\"):
                    resolved = resolved[4:]
                resolved = os.path.normcase(resolved)
            return Path(resolved)

        try:
            _canonical(path).relative_to(_canonical(root))
        except ValueError as exc:
            msg = f"Artifact path escapes root: {path}"
            raise ValueError(msg) from exc
