"""Strict ICD code value objects used by terminology workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

IcdVersion = Literal["ICD-9-CM", "ICD-10-CM"]
MAX_ICD_CODE_CHARS = 8

_ICD10_CM_RE = re.compile(r"[A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?")
_ICD9_CM_NUMERIC_RE = re.compile(r"[0-9]{3}(?:\.[0-9]{1,2})?")
_ICD9_CM_V_RE = re.compile(r"V[0-9]{2}(?:\.[0-9]{1,2})?")
_ICD9_CM_E_RE = re.compile(r"E[0-9]{3}(?:\.[0-9])?")


class IcdCodeValidationError(ValueError):
    """Raised when an ICD code is malformed or ambiguous."""


@dataclass(frozen=True, slots=True)
class IcdCode:
    """A canonical ICD code plus its detected code-system version."""

    value: str
    version: IcdVersion


def normalize_icd_code(value: object) -> IcdCode:
    """Validate one complete ICD-9-CM or ICD-10-CM diagnosis code.

    This parser intentionally does not extract a code from surrounding prose.
    Bare numeric values are treated as ICD-9-CM only when the complete value
    matches the diagnosis-code grammar.
    """

    if not isinstance(value, str):
        raise IcdCodeValidationError("ICD code must be a string")
    code = value.strip().upper()
    if not code:
        raise IcdCodeValidationError("ICD code is empty")
    if len(code) > MAX_ICD_CODE_CHARS:
        raise IcdCodeValidationError(f"ICD code exceeds {MAX_ICD_CODE_CHARS} characters")
    matches_icd9 = any(pattern.fullmatch(code) for pattern in (_ICD9_CM_NUMERIC_RE, _ICD9_CM_V_RE, _ICD9_CM_E_RE))
    matches_icd10 = _ICD10_CM_RE.fullmatch(code) is not None
    if matches_icd9 and matches_icd10:
        raise IcdCodeValidationError(
            "Code is syntactically ambiguous between ICD-9-CM and ICD-10-CM; provide an unambiguous code"
        )
    if matches_icd9:
        return IcdCode(value=code, version="ICD-9-CM")
    if matches_icd10:
        return IcdCode(value=code, version="ICD-10-CM")
    raise IcdCodeValidationError("Value is not a complete ICD-9-CM or ICD-10-CM diagnosis code")


__all__ = [
    "IcdCode",
    "IcdCodeValidationError",
    "IcdVersion",
    "MAX_ICD_CODE_CHARS",
    "normalize_icd_code",
]
