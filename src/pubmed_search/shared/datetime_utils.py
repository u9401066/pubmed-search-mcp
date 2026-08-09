"""Cross-version helpers for parsing persisted datetime values."""

from __future__ import annotations

from datetime import datetime


def parse_iso8601_datetime(value: str) -> datetime:
    """Parse ISO-8601 datetimes consistently on every supported Python.

    Python 3.10's :meth:`datetime.fromisoformat` rejects the RFC 3339 ``Z``
    UTC designator, while newer runtimes accept it. Normalize that designator
    before delegating so persisted data has the same contract on Python 3.10+.
    """
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)
