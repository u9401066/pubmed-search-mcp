"""
PubTator3 Data Models

Dataclasses for PubTator3 API responses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pubmed_search.application.search.semantic_enhancer import ResolvedEntity

EntityType = Literal["gene", "disease", "chemical", "species", "variant"]
RelationType = Literal["treat", "associate", "cause", "interact", "inhibit", "stimulate"]


@dataclass
class EntityMatch:
    """
    Entity autocomplete result from PubTator3.

    Attributes:
        entity_id: PubTator3 entity ID (e.g., "@CHEMICAL_Propofol")
        name: Standard entity name
        type: Entity type (gene, disease, chemical, species, variant)
        identifier: External ID (MeSH, NCBI Gene ID, etc.)
        score: Match confidence score (0-1)
    """

    entity_id: str
    name: str
    type: str
    identifier: str | None = None
    score: float = 1.0

    @property
    def mesh_id(self) -> str | None:
        """Extract MeSH ID if identifier is a MeSH term."""
        match = re.fullmatch(r"(?:MESH:)?([DC][0-9]+)", self.identifier or "", re.IGNORECASE)
        return match.group(1).upper() if match else None

    def to_pubmed_query(self) -> str:
        """Convert to PubMed search query format."""
        if self.mesh_id:
            return f'"{self.name}"[MeSH Terms]'
        return f'"{self.name}"'


@dataclass
class RelationMatch:
    """
    Entity relation from PubTator3.

    Attributes:
        source_entity: Source entity ID
        source_name: Source entity name
        relation_type: Type of relation (treat, associate, etc.)
        target_entity: Target entity ID
        target_name: Target entity name
        evidence_count: Number of supporting articles
        pmids: Sample PMIDs as evidence
    """

    source_entity: str
    source_name: str
    relation_type: str
    target_entity: str
    target_name: str
    evidence_count: int = 0
    pmids: list[str] = field(default_factory=list)

    def get_evidence_pmids(self, limit: int = 5) -> list[str]:
        """Get top PMIDs as evidence."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        return self.pmids[:limit]


@dataclass
class EntitySearchResult:
    """
    Result from entity-based search.

    Combines entity information with document counts.
    """

    entity: ResolvedEntity
    document_count: int = 0
    related_entities: list[str] = field(default_factory=list)
