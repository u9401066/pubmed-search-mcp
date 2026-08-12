"""Shared, precision-aware chronology rules for Research Chronicles.

Chronicle dates may have year, month, or day precision.  Sorting is stable and
never uses an entry identifier to invent an order between observations made at
the same reported time.  Provenance edges use interval semantics: one entry
precedes another only when its latest possible date is earlier than the other
entry's earliest possible date.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_YEAR_RE = re.compile(r"^(\d{4})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_UNDATED_LABELS = frozenset({"", "n/a", "na", "none", "undated", "unknown"})


@dataclass(frozen=True)
class ChronicleTime:
    """A parsed Chronicle time represented as a precision interval."""

    year: int
    month: int | None
    day: int | None
    precision: str
    earliest: date
    latest: date

    @property
    def sort_key(self) -> tuple[int, int, int, int, int]:
        """Return a deterministic key without an identifier tie-breaker."""
        precision_rank = {"year": 0, "month": 1, "day": 2}[self.precision]
        return (0, self.year, self.month or 0, self.day or 0, precision_rank)


def parse_chronicle_time(value: Any) -> ChronicleTime | None:
    """Parse an ISO year, year-month, or calendar date.

    ``None`` represents either an explicitly undated value or malformed input;
    :func:`chronicle_time_status` distinguishes those cases for audit output.
    """
    text = str(value or "").strip()
    match = _YEAR_RE.fullmatch(text)
    if match:
        year = int(match.group(1))
        if not 1 <= year <= 9999:
            return None
        return ChronicleTime(
            year=year,
            month=None,
            day=None,
            precision="year",
            earliest=date(year, 1, 1),
            latest=date(year, 12, 31),
        )

    match = _MONTH_RE.fullmatch(text)
    if match:
        year, month = (int(part) for part in match.groups())
        if not 1 <= year <= 9999 or not 1 <= month <= 12:
            return None
        return ChronicleTime(
            year=year,
            month=month,
            day=None,
            precision="month",
            earliest=date(year, month, 1),
            latest=date(year, month, calendar.monthrange(year, month)[1]),
        )

    match = _DAY_RE.fullmatch(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        return ChronicleTime(
            year=year,
            month=month,
            day=day,
            precision="day",
            earliest=parsed,
            latest=parsed,
        )
    return None


def chronicle_time_status(value: Any) -> str:
    """Return ``valid``, ``undated``, or ``invalid`` for an entry time."""
    text = str(value or "").strip()
    if text.casefold() in _UNDATED_LABELS:
        return "undated"
    return "valid" if parse_chronicle_time(text) is not None else "invalid"


def chronology_key(value: Any) -> tuple[int, int, int, int, int]:
    """Return the shared stable-sort key, placing undated values last."""
    raw = getattr(value, "time_start", value)
    parsed = parse_chronicle_time(raw)
    return parsed.sort_key if parsed is not None else (1, 10_000, 13, 32, 3)


def definitely_precedes(left: Any, right: Any) -> bool:
    """Return whether reported precision proves that *left* precedes *right*."""
    left_time = parse_chronicle_time(getattr(left, "time_start", left))
    right_time = parse_chronicle_time(getattr(right, "time_start", right))
    return bool(left_time and right_time and left_time.latest < right_time.earliest)


__all__ = [
    "ChronicleTime",
    "chronicle_time_status",
    "chronology_key",
    "definitely_precedes",
    "parse_chronicle_time",
]
