"""Small, dependency-free helpers for crash-safe local file persistence."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
    """Replace *path* atomically after fully writing and syncing a sibling file.

    A unique temporary file avoids collisions between independent store
    instances.  Closing it before :func:`os.replace` also keeps the operation
    compatible with Windows.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Call ``os.replace`` directly instead of routing through
        # ``Path.replace``.  Besides matching the contract documented above,
        # this keeps the atomic publication boundary explicit and consistent
        # across Python versions (``pathlib`` used a cached accessor on 3.10).
        os.replace(temporary, destination)  # noqa: PTH105 -- see compatibility note
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: str | Path, payload: Any, *, indent: int = 2) -> None:
    """Serialize *payload* as UTF-8 JSON and atomically replace *path*."""
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent))


__all__ = ["atomic_write_json", "atomic_write_text"]
