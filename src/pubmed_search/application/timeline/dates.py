"""Publication date parsing shared by timeline ordering and milestone events."""

from __future__ import annotations

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTHS = {name: month for month, name in enumerate(_MONTH_NAMES, start=1)}
_MONTHS.update({name[:3]: month for month, name in enumerate(_MONTH_NAMES, start=1)})
_MONTHS["sept"] = 9


def parse_publication_month(value: object) -> int | None:
    """Accept month names or integer text; booleans are not calendar dates."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lower()
    try:
        month = int(text)
    except ValueError:
        return _MONTHS.get(text)
    return month if 1 <= month <= 12 else None


def parse_publication_year(value: object) -> int | None:
    """Parse a plausible four-digit publication year without raising."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if len(text) != 4 or not text.isdecimal():
        return None
    year = int(text)
    return year if 1000 <= year <= 9999 else None
