"""Application contracts for entitlement-gated clinical evidence lookup.

The contract intentionally models a single, de-identified citation lookup. It
is not a diagnostic, differential-diagnosis, conversational, or article-text
capability and is not part of the generic literature-search facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ClinicalEvidenceUseCase(str, Enum):
    """The only allowed use case for the restricted data-plane adapter."""

    EVIDENCE_LOOKUP = "evidence_lookup"


@dataclass(frozen=True, slots=True)
class ClinicalEvidenceCitationRequest:
    """A de-identified evidence question with per-request end-user context."""

    question: str
    end_user_id: str
    end_user_persona: str
    secondary_org_id: str | None = None
    input_is_deidentified: bool = False
    use_case: ClinicalEvidenceUseCase = ClinicalEvidenceUseCase.EVIDENCE_LOOKUP


@dataclass(frozen=True, slots=True)
class ClinicalCitationMetadata:
    """Allowlisted citation metadata with licensed content fields removed."""

    reference_id: str
    document_title: str | None = None
    container_title: str | None = None
    authors: tuple[str, ...] = ()
    doi: str | None = None
    pmid: str | None = None
    identifier: str | None = None
    identifier_type: str | None = None
    publication_date: str | None = None
    href: str | None = None


@dataclass(frozen=True, slots=True)
class ClinicalCitationBatch:
    """Ephemeral, non-exhaustive provider result containing metadata only."""

    citations: tuple[ClinicalCitationMetadata, ...]
    provider_reference_count: int
    dropped_reference_count: int
    source: str = field(default="clinicalkey_ai", init=False)
    retrieval_mode: str = field(default="ai_curated_non_exhaustive", init=False)
    license_restricted: bool = field(default=True, init=False)
    warnings: tuple[str, ...] = field(
        default=(
            "AI-curated citations are non-exhaustive and require independent verification.",
            "Not for diagnosis, differential diagnosis, or patient-specific advice.",
        ),
        init=False,
    )


class ClinicalEvidenceCitationProvider(Protocol):
    """Application port implemented by an entitlement-gated data-plane client."""

    async def fetch_citations(
        self,
        request: ClinicalEvidenceCitationRequest,
    ) -> ClinicalCitationBatch: ...
