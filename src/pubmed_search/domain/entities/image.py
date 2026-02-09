"""
Domain Entity: ImageResult

Unified biomedical image search result.
Pure domain entity — no source-specific factory methods.
Source mapping is handled by Infrastructure layer mappers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum


class ImageSource(str, Enum):
    """Image source identifier (consistent with ArticleType/MilestoneType Enum pattern)."""

    OPENI = "openi"
    EUROPE_PMC = "europe_pmc"
    MEDPIX = "medpix"


@dataclass
class ImageResult:
    """
    Unified biomedical image search result.

    Pure Domain entity — no source-specific factory methods.
    Source mapping is handled by Infrastructure layer mappers.
    This is an intentional architectural improvement over
    UnifiedArticle.from_pubmed() pattern.
    """

    # Image information
    image_url: str
    thumbnail_url: str | None = None
    caption: str = ""
    label: str = ""  # e.g., "Figure 1"

    # Source information
    source: ImageSource | str = ""  # ImageSource enum value
    source_id: str = ""  # Internal source ID

    # Associated article information
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    article_title: str = ""
    journal: str = ""
    authors: str = ""
    pub_year: int | None = None

    # Image classification (Open-i specific, may be empty for other sources)
    image_type: str | None = None  # "xg" (X-ray), "mc" (Microscopy)
    mesh_terms: list[str] = field(default_factory=list)
    collection: str | None = None  # "pmc", "mpx", "iu"

    @property
    def has_article_link(self) -> bool:
        """Whether this image has an associated article identifier."""
        return bool(self.pmid or self.pmcid or self.doi)

    @property
    def best_identifier(self) -> str:
        """Best available article identifier."""
        if self.pmid:
            return f"PMID:{self.pmid}"
        if self.pmcid:
            return self.pmcid
        if self.doi:
            return f"DOI:{self.doi}"
        return self.source_id

    def to_dict(self) -> dict:
        """Serialize to dictionary (auto-tracks new fields)."""
        return dataclasses.asdict(self)
