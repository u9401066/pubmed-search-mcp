"""Typed provenance for the optional ClinicalTrials.gov unified-search adjunct."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pubmed_search.shared.source_contracts import (
    SourceAdapterError,
    normalize_source_adapter_error,
)

ClinicalTrialsRetrievalStatus = Literal["not_requested", "pending", "complete", "empty", "timeout", "error"]
ClinicalTrialsFormatStatus = Literal["not_requested", "pending", "complete", "not_applicable", "error"]
ClinicalTrialsStatus = Literal["not_requested", "pending", "complete", "empty", "timeout", "error", "format_error"]

_NCT_ID_RE = re.compile(r"^NCT\d{8}$")
_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ClinicalTrialsResponseError(TypeError):
    """Raised when the adjunct violates its normalized result-list contract."""


class ClinicalTrialsFormatError(RuntimeError):
    """Raised when a non-empty adjunct result cannot be rendered."""


@dataclass(slots=True)
class ClinicalTrialsCoverage:
    """Mutable execution-to-render handoff with sanitized adjunct provenance."""

    requested: bool = False
    attempted: bool = False
    retrieval_status: ClinicalTrialsRetrievalStatus = "not_requested"
    format_status: ClinicalTrialsFormatStatus = "not_requested"
    returned: int = 0
    error: SourceAdapterError | None = None
    error_type: str | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def requested_search(cls, *, markdown_output: bool) -> ClinicalTrialsCoverage:
        """Create the initial state for one explicitly requested adjunct."""
        return cls(
            requested=True,
            attempted=True,
            retrieval_status="pending",
            format_status="pending" if markdown_output else "not_applicable",
        )

    @property
    def status(self) -> ClinicalTrialsStatus:
        """Return the effective end-to-end adjunct state."""
        if not self.requested:
            return "not_requested"
        if self.format_status == "error":
            return "format_error"
        if self.retrieval_status == "pending" or (
            self.retrieval_status == "complete" and self.format_status == "pending"
        ):
            return "pending"
        return self.retrieval_status

    @property
    def complete(self) -> bool:
        """Whether retrieval and every applicable projection completed."""
        return self.retrieval_status in {"complete", "empty"} and self.format_status in {
            "complete",
            "not_applicable",
        }

    def record_retrieval(self, returned: int) -> None:
        """Record a validated success, preserving a real zero-result outcome."""
        self.returned = returned
        self.retrieval_status = "complete" if returned else "empty"
        if not returned:
            self.format_status = "not_applicable"

    def record_failure(
        self,
        error: Exception,
        *,
        status: Literal["timeout", "error"] = "error",
        operation: str = "adjunct_search",
    ) -> None:
        """Record a normalized retrieval failure without raw exception text."""
        self.retrieval_status = status
        self.format_status = "not_applicable"
        self.error = normalize_clinical_trials_error(error, operation=operation)
        self.error_type = type(error).__name__
        warning = "ClinicalTrials.gov adjunct timed out" if status == "timeout" else "ClinicalTrials.gov adjunct failed"
        if warning not in self.warnings:
            self.warnings.append(warning)

    def record_validation_failure(self, error: Exception) -> None:
        """Record a response-contract violation as a non-retryable failure."""
        self.retrieval_status = "error"
        self.format_status = "not_applicable"
        self.error = SourceAdapterError(
            source="clinical_trials",
            operation="adjunct_search",
            message="ClinicalTrials.gov returned an invalid response",
            kind="validation",
            retryable=False,
        )
        self.error_type = type(error).__name__
        if "ClinicalTrials.gov adjunct returned an invalid response" not in self.warnings:
            self.warnings.append("ClinicalTrials.gov adjunct returned an invalid response")

    def record_format_success(self) -> None:
        """Mark the requested Markdown projection as successfully rendered."""
        if self.retrieval_status == "complete":
            self.format_status = "complete"

    def record_format_failure(self, error: Exception) -> None:
        """Record a sanitized presentation failure while retaining result counts."""
        self.format_status = "error"
        self.error = SourceAdapterError(
            source="clinical_trials",
            operation="format_markdown",
            message="ClinicalTrials.gov results could not be rendered",
            kind="unexpected",
            retryable=False,
        )
        self.error_type = type(error).__name__
        if "ClinicalTrials.gov results could not be rendered" not in self.warnings:
            self.warnings.append("ClinicalTrials.gov results could not be rendered")

    def to_dict(self) -> dict[str, Any]:
        """Return the versioned, JSON-safe coverage contract."""
        error_payload: dict[str, Any] | None = None
        if self.error is not None:
            error_payload = {
                "source": self.error.source,
                "operation": self.error.operation,
                "message": self.error.message,
                "kind": self.error.kind,
                "retryable": self.error.retryable,
                "status_code": self.error.status_code,
                "exception_type": self.error_type,
            }
        return {
            "schema_version": "clinical-trials-adjunct/v1",
            "source": "clinical_trials",
            "requested": self.requested,
            "attempted": self.attempted,
            "status": self.status,
            "retrieval_status": self.retrieval_status,
            "format_status": self.format_status,
            "returned": self.returned,
            "complete": self.complete,
            "warnings": list(self.warnings),
            "error": error_payload,
        }


def normalize_clinical_trials_error(error: Exception, *, operation: str) -> SourceAdapterError:
    """Normalize adjunct errors, including sanitized provider wrapper errors."""
    normalized = normalize_source_adapter_error("clinical_trials", operation, error)
    if normalized.kind != "unexpected":
        return normalized

    raw_status_code = getattr(error, "status_code", None)
    status_code = (
        raw_status_code
        if isinstance(raw_status_code, int) and not isinstance(raw_status_code, bool) and 100 <= raw_status_code <= 599
        else None
    )
    if status_code is not None:
        return SourceAdapterError(
            source="clinical_trials",
            operation=operation,
            message=f"Upstream returned HTTP {status_code}",
            kind="http",
            retryable=status_code in _RETRYABLE_HTTP_STATUSES,
            status_code=status_code,
        )
    if bool(getattr(error, "retryable", False)):
        return SourceAdapterError(
            source="clinical_trials",
            operation=operation,
            message="Upstream request failed",
            kind="retryable",
            retryable=True,
        )
    return normalized


def clinical_trials_error_payload(coverage: ClinicalTrialsCoverage) -> dict[str, Any] | None:
    """Project the current sanitized error into unified source-errors format."""
    error = coverage.error
    if error is None:
        return None
    payload: dict[str, Any] = {
        "source": error.source,
        "operation": error.operation,
        "message": error.message,
        "kind": error.kind,
        "retryable": error.retryable,
        "status": "timeout" if error.kind == "timeout" else "error",
        "exception_type": coverage.error_type,
    }
    if error.status_code is not None:
        payload["status_code"] = error.status_code
    return payload


def validate_clinical_trials_rows(raw_rows: Any, *, limit: int) -> list[dict[str, Any]]:
    """Validate the normalized ClinicalTrials.gov row contract fail-closed."""
    if not isinstance(raw_rows, list) or len(raw_rows) > limit:
        raise ClinicalTrialsResponseError

    rows: list[dict[str, Any]] = []
    scalar_fields = ("title", "official_title", "status", "phase", "start_date", "url", "sponsor")
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ClinicalTrialsResponseError
        nct_id = raw_row.get("nct_id")
        if not isinstance(nct_id, str) or not _NCT_ID_RE.fullmatch(nct_id):
            raise ClinicalTrialsResponseError
        if any(field in raw_row and not isinstance(raw_row[field], str) for field in scalar_fields):
            raise ClinicalTrialsResponseError
        conditions = raw_row.get("conditions", [])
        if not isinstance(conditions, list) or any(not isinstance(condition, str) for condition in conditions):
            raise ClinicalTrialsResponseError
        interventions = raw_row.get("interventions", [])
        if not isinstance(interventions, list) or any(
            not isinstance(intervention, dict)
            or any(field in intervention and not isinstance(intervention[field], str) for field in ("type", "name"))
            for intervention in interventions
        ):
            raise ClinicalTrialsResponseError
        enrollment = raw_row.get("enrollment")
        if enrollment is not None and (
            not isinstance(enrollment, int) or isinstance(enrollment, bool) or enrollment < 0
        ):
            raise ClinicalTrialsResponseError

        row = dict(raw_row)
        row["url"] = f"https://clinicaltrials.gov/study/{nct_id}"
        rows.append(row)
    return rows


__all__ = [
    "ClinicalTrialsCoverage",
    "ClinicalTrialsFormatError",
    "ClinicalTrialsResponseError",
    "clinical_trials_error_payload",
    "normalize_clinical_trials_error",
    "validate_clinical_trials_rows",
]
