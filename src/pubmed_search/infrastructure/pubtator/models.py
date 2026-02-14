"""
PubTator3 Data Models

Dataclasses for PubTator3 API responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
        if self.identifier and self.identifier.startswith(("D", "C")):
            return self.identifier
        return None

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
        return self.pmids[:limit]


@dataclass
class PubTatorEntity:
    """
    Resolved entity with full context.

    Used after entity resolution to provide standardized
    identifiers for downstream processing.
    """

    original_text: str  # Original user input
    resolved_name: str  # Standardized name
    entity_type: str  # Type category (gene, disease, chemical, etc.)
    entity_id: str  # PubTator3 ID
    mesh_id: str | None = None  # MeSH ID (if available)
    ncbi_id: str | None = None  # NCBI Gene/Taxonomy ID (if applicable)

    def to_search_term(self) -> str:
        """Generate optimal search term for PubMed."""
        if self.mesh_id:
            return f'"{self.resolved_name}"[MeSH Terms]'
        if self.entity_type == "gene" and self.ncbi_id:
            return f"{self.resolved_name}[Gene Name]"
        return f'"{self.resolved_name}"'


@dataclass
class EntitySearchResult:
    """
    Result from entity-based search.

    Combines entity information with document counts.
    """

    entity: PubTatorEntity
    document_count: int = 0
    related_entities: list[str] = field(default_factory=list)
