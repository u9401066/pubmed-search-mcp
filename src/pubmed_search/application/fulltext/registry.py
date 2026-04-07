"""Policy registry for selecting fulltext retrieval strategies.

Design:
    This registry is the application-layer source of truth for fulltext source
    metadata and policy ordering. It converts identifier availability and
    compatibility flags into a stable retrieval plan.

Maintenance:
    Update policy precedence and source metadata here when retrieval behavior
    changes. Infrastructure modules should consume this registry rather than
    embedding their own policy branching.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

FulltextPolicyKey = Literal["structured_first", "standard_discovery", "expanded_discovery"]


@dataclass(frozen=True)
class FulltextSourceDefinition:
    """Registry metadata for one fulltext-capable source."""

    key: str
    label: str
    priority: int
    identifier_support: tuple[str, ...]
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class FulltextPolicyDefinition:
    """Ordered source policy used by fulltext orchestration."""

    key: FulltextPolicyKey
    label: str
    sources: tuple[str, ...]


DEFAULT_SOURCES: tuple[FulltextSourceDefinition, ...] = (
    FulltextSourceDefinition(
        key="europe_pmc",
        label="Europe PMC",
        priority=1,
        identifier_support=("pmcid",),
        capabilities=("structured", "pdf"),
    ),
    FulltextSourceDefinition(
        key="unpaywall",
        label="Unpaywall",
        priority=2,
        identifier_support=("doi",),
        capabilities=("pdf", "landing_page_resolution"),
    ),
    FulltextSourceDefinition(
        key="core",
        label="CORE",
        priority=3,
        identifier_support=("doi",),
        capabilities=("pdf", "landing_page_resolution", "fulltext_text"),
    ),
    FulltextSourceDefinition(
        key="extended",
        label="Extended (15 sources)",
        priority=4,
        identifier_support=("pmid", "pmcid", "doi"),
        capabilities=("pdf", "landing_page_resolution", "fulltext_text"),
    ),
)

DEFAULT_POLICIES: tuple[FulltextPolicyDefinition, ...] = (
    FulltextPolicyDefinition(
        key="structured_first",
        label="Structured first",
        sources=("europe_pmc", "unpaywall", "core", "extended"),
    ),
    FulltextPolicyDefinition(
        key="standard_discovery",
        label="Standard discovery",
        sources=("unpaywall", "core"),
    ),
    FulltextPolicyDefinition(
        key="expanded_discovery",
        label="Expanded discovery",
        sources=("unpaywall", "core", "extended"),
    ),
)


class FulltextRegistry:
    """Metadata registry for fulltext orchestration policies and sources."""

    def __init__(
        self,
        *,
        sources: tuple[FulltextSourceDefinition, ...] = DEFAULT_SOURCES,
        policies: tuple[FulltextPolicyDefinition, ...] = DEFAULT_POLICIES,
    ) -> None:
        self._sources = {source.key: source for source in sources}
        self._policies = {policy.key: policy for policy in policies}

    def get_source_definition(self, key: str) -> FulltextSourceDefinition:
        return self._sources[key]

    def get_policy_definition(self, key: FulltextPolicyKey) -> FulltextPolicyDefinition:
        return self._policies[key]

    def label_for(self, key: str) -> str:
        return self.get_source_definition(key).label

    def resolve_policy(
        self,
        *,
        pmcid: str | None,
        pmid: str | None,
        doi: str | None,
        extended_sources: bool,
    ) -> FulltextPolicyDefinition:
        """Resolve a retrieval policy from normalized identifiers and compatibility hints."""
        if not any((pmcid, pmid, doi)):
            msg = "At least one identifier is required to resolve a fulltext policy"
            raise ValueError(msg)

        if pmcid:
            policy_key: FulltextPolicyKey = "structured_first"
        elif extended_sources:
            policy_key = "expanded_discovery"
        else:
            policy_key = "standard_discovery"
        return self.get_policy_definition(policy_key)


@lru_cache(maxsize=1)
def get_fulltext_registry() -> FulltextRegistry:
    """Return the singleton fulltext registry."""
    return FulltextRegistry()