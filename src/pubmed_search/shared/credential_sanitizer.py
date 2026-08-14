"""Credential detection and redaction for user-controlled search inputs."""

from __future__ import annotations

import re
from typing import Any

_GENERIC_CREDENTIAL_LABEL = (
    r"api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|cookie|password|secret|token"
)
# Provider-specific environment/header names used by this repository.  Keep
# this explicit: matching every ``*_KEY`` would reject legitimate biomedical
# identifiers, while omitting the prefix-bearing aliases would let secrets
# pass through the durable search-history boundary.
_KNOWN_CREDENTIAL_LABEL = (
    r"ncbi[_-]?api[_-]?key|core[_-]?api[_-]?key|s2[_-]?api[_-]?key|"
    r"semantic[_-]?scholar[_-]?api[_-]?key|openalex[_-]?api[_-]?key|"
    r"scopus[_-]?api[_-]?key|scopus[_-]?insttoken|web[_-]?of[_-]?science[_-]?api[_-]?key|"
    r"clinicalkey[_-]?ai[_-]?client[_-]?secret|pubmed[_-]?auth[_-]?tokens|"
    r"browser[_-]?fetch(?:[_-]?broker)?[_-]?token|ezproxy[_-]?cookie|"
    r"x[_-]?els[_-]?api[_-]?key|x[_-]?els[_-]?insttoken|x[_-]?api[_-]?key"
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:^|[?&\s,:{;])"
    rf"(?:[\"']?(?:{_GENERIC_CREDENTIAL_LABEL}|{_KNOWN_CREDENTIAL_LABEL})[\"']?)"
    r"\s*[:=]\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s,;&#}]+))"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/-]+=*)")
_SECRET_FIELD_RE = re.compile(
    rf"(?i)(?:(?:^|[_-])(?:{_GENERIC_CREDENTIAL_LABEL})(?:$|[_-])|^(?:{_KNOWN_CREDENTIAL_LABEL})$)"
)


def extract_credential_values(text: str) -> frozenset[str]:
    """Return credential values that were explicitly labelled in *text*."""
    values: set[str] = set()
    for match in _ASSIGNMENT_RE.finditer(text):
        value = next((group for group in match.groups() if group), "")
        if value:
            values.add(value)
    values.update(match.group(1) for match in _BEARER_RE.finditer(text) if match.group(1))
    return frozenset(values)


def contains_credential_material(text: str) -> bool:
    """Return whether a search input appears to embed a credential."""
    return bool(extract_credential_values(text))


def is_credential_field(name: str) -> bool:
    """Return whether a mapping field is credential-bearing."""
    return bool(_SECRET_FIELD_RE.search(name.strip("\"'")))


def redact_credential_assignments(text: str) -> str:
    """Redact labelled credentials while preserving the surrounding syntax."""

    def _redact_match(match: re.Match[str]) -> str:
        matched = match.group(0)
        for group_index in range(1, 4):
            if match.group(group_index) is None:
                continue
            start = match.start(group_index) - match.start()
            end = match.end(group_index) - match.start()
            return f"{matched[:start]}[REDACTED]{matched[end:]}"
        return "[REDACTED]"

    redacted = _ASSIGNMENT_RE.sub(_redact_match, text)
    return _BEARER_RE.sub("Bearer [REDACTED]", redacted)


def redact_known_credential_values(value: Any, secrets: frozenset[str]) -> Any:
    """Recursively remove already-identified secret values from a payload."""
    if isinstance(value, dict):
        return {str(key): redact_known_credential_values(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_known_credential_values(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted(secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


__all__ = [
    "contains_credential_material",
    "extract_credential_values",
    "is_credential_field",
    "redact_credential_assignments",
    "redact_known_credential_values",
]
