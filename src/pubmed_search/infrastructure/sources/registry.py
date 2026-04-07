"""Source registry and source-selection helpers.

The registry centralizes metadata about current integrations and provides
selection semantics for user-facing source expressions such as:

    auto,-semantic_scholar
    all,-crossref
    pubmed,openalex

It is intentionally metadata-driven so new APIs can be added by registering a
source definition first, then wiring the actual client and search adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from pubmed_search.shared.settings import load_settings

SourceCategory = Literal["search", "enrichment", "fulltext", "preprint", "image", "structured"]
SourceAccessTier = Literal["open", "commercial", "institutional"]
SourceSelectionMode = Literal["auto", "explicit", "all"]
SourceAutoDispatchProfile = Literal[
    "lookup_identifier",
    "lookup",
    "simple",
    "moderate",
    "complex_comparison",
    "complex_systematic",
    "complex_default",
    "ambiguous",
]

_DISABLED_SOURCES_ENV = "PUBMED_SEARCH_DISABLED_SOURCES"


def normalize_source_name(value: str) -> str:
    """Normalize user-supplied source tokens to registry keys."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


@dataclass(frozen=True)
class SourceDefinition:
    """Metadata for one external source integration."""

    key: str
    label: str
    category: SourceCategory
    access_tier: SourceAccessTier = "open"
    selectable_in_unified: bool = False
    supports_primary_search: bool = False
    enabled_by_default: bool = True
    implemented: bool = True
    aliases: tuple[str, ...] = ()
    required_env_vars: tuple[str, ...] = ()
    enable_env_var: str | None = None
    alternate_search_runner: str | None = None
    auto_dispatch_profiles: tuple[SourceAutoDispatchProfile, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class SourceSelection:
    """Resolved source selection after parsing a user expression."""

    mode: SourceSelectionMode
    sources: tuple[str, ...]
    requested: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    available_sources: tuple[str, ...] = ()


@dataclass(eq=False)
class SourceSelectionError(ValueError):
    """Raised when a source expression references invalid or unavailable sources."""

    message: str
    invalid_sources: tuple[str, ...] = field(default_factory=tuple)
    unavailable_sources: tuple[str, ...] = field(default_factory=tuple)
    available_sources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class SourceRegistry:
    """Central registry for source metadata and source-expression parsing."""

    def __init__(self, definitions: tuple[SourceDefinition, ...]) -> None:
        self._definitions = {definition.key: definition for definition in definitions}
        self._aliases: dict[str, str] = {}
        for definition in definitions:
            self._aliases[normalize_source_name(definition.key)] = definition.key
            for alias in definition.aliases:
                self._aliases[normalize_source_name(alias)] = definition.key

    def resolve_key(self, value: str) -> str | None:
        return self._aliases.get(normalize_source_name(value))

    def get(self, value: str) -> SourceDefinition | None:
        key = self.resolve_key(value)
        if key is None:
            return None
        return self._definitions.get(key)

    def list_unified_sources(self) -> list[str]:
        return [
            definition.key
            for definition in self._definitions.values()
            if definition.selectable_in_unified and self.is_enabled(definition.key)
        ]

    def filter_unified_sources(self, sources: list[str]) -> list[str]:
        filtered: list[str] = []
        seen: set[str] = set()
        for source in sources:
            definition = self.get(source)
            if definition is None or not definition.selectable_in_unified:
                continue
            if not self.is_enabled(definition.key) or definition.key in seen:
                continue
            filtered.append(definition.key)
            seen.add(definition.key)
        return filtered

    def list_auto_dispatch_sources(self, profile: SourceAutoDispatchProfile) -> list[str]:
        return [
            definition.key
            for definition in self._definitions.values()
            if definition.selectable_in_unified
            and profile in definition.auto_dispatch_profiles
            and self.is_enabled(definition.key)
        ]

    def is_enabled(self, value: str) -> bool:
        definition = self.get(value)
        if definition is None or not definition.implemented:
            return False

        settings = load_settings()

        if definition.key in self._disabled_sources_from_env(settings.disabled_sources):
            return False

        if definition.enabled_by_default:
            return True

        if definition.key == "scopus":
            return settings.scopus_enabled and bool(settings.scopus_api_key)

        if definition.key == "web_of_science":
            return settings.web_of_science_enabled and bool(settings.web_of_science_api_key)

        return False

    def resolve_unified_sources(
        self,
        expression: str,
        *,
        auto_sources: list[str],
    ) -> SourceSelection:
        """Resolve a unified-search source expression into concrete source keys."""
        tokens = [token.strip() for token in expression.split(",") if token.strip()]
        include_auto = False
        include_all = False
        include: list[str] = []
        exclude: list[str] = []
        invalid: list[str] = []
        unavailable: list[str] = []

        for token in tokens:
            is_exclusion = token.startswith("-")
            raw_name = token[1:] if is_exclusion else token
            normalized = normalize_source_name(raw_name)

            if normalized in {"auto", "all"}:
                if is_exclusion:
                    invalid.append(token)
                elif normalized == "auto":
                    include_auto = True
                else:
                    include_all = True
                continue

            definition = self.get(normalized)
            if definition is None or not definition.selectable_in_unified:
                invalid.append(raw_name)
                continue
            if not self.is_enabled(definition.key):
                unavailable.append(definition.key)
                continue

            if is_exclusion:
                exclude.append(definition.key)
            else:
                include.append(definition.key)

        available_sources = tuple(self.list_unified_sources())
        invalid = _dedupe(invalid)
        unavailable = _dedupe(unavailable)
        if invalid or unavailable:
            message_parts: list[str] = []
            if invalid:
                message_parts.append(f"Invalid source(s): {', '.join(invalid)}")
            if unavailable:
                message_parts.append(f"Unavailable source(s): {', '.join(unavailable)}")
            raise SourceSelectionError(
                "; ".join(message_parts),
                invalid_sources=tuple(invalid),
                unavailable_sources=tuple(unavailable),
                available_sources=available_sources,
            )

        auto_base = self.filter_unified_sources(auto_sources)
        requested = _dedupe(include)
        excluded = _dedupe(exclude)

        if include_all:
            mode: SourceSelectionMode = "all"
            base = list(available_sources)
        elif include_auto or (not requested and excluded):
            mode = "auto"
            base = auto_base + requested
        elif requested:
            mode = "explicit"
            base = requested
        else:
            mode = "auto"
            base = auto_base

        resolved = [source for source in _dedupe(base) if source not in excluded]
        if not resolved:
            raise SourceSelectionError(
                "No sources remain after applying exclusions",
                available_sources=available_sources,
            )

        return SourceSelection(
            mode=mode,
            sources=tuple(resolved),
            requested=tuple(requested),
            excluded=tuple(excluded),
            available_sources=available_sources,
        )

    def _disabled_sources_from_env(self, disabled_sources: tuple[str, ...] | None = None) -> set[str]:
        disabled: set[str] = set()
        raw_values = disabled_sources or ()
        if not raw_values:
            return disabled
        for token in raw_values:
            candidate = token.strip()
            if not candidate:
                continue
            key = self.resolve_key(candidate)
            if key is not None:
                disabled.add(key)
        return disabled


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_ALL_AUTO_DISPATCH_PROFILES: tuple[SourceAutoDispatchProfile, ...] = (
    "lookup_identifier",
    "lookup",
    "simple",
    "moderate",
    "complex_comparison",
    "complex_systematic",
    "complex_default",
    "ambiguous",
)

_OPENALEX_AUTO_DISPATCH_PROFILES: tuple[SourceAutoDispatchProfile, ...] = (
    "complex_comparison",
    "complex_systematic",
    "complex_default",
    "ambiguous",
)

_SEMANTIC_SCHOLAR_AUTO_DISPATCH_PROFILES: tuple[SourceAutoDispatchProfile, ...] = (
    "complex_comparison",
    "complex_systematic",
)

_EUROPE_PMC_AUTO_DISPATCH_PROFILES: tuple[SourceAutoDispatchProfile, ...] = (
    "complex_systematic",
)

_CROSSREF_AUTO_DISPATCH_PROFILES: tuple[SourceAutoDispatchProfile, ...] = (
    "lookup",
    "moderate",
    "complex_default",
)


@lru_cache(maxsize=1)
def get_source_registry() -> SourceRegistry:
    """Return the singleton source registry."""
    return SourceRegistry(
        (
            SourceDefinition(
                key="pubmed",
                label="PubMed",
                category="search",
                selectable_in_unified=True,
                supports_primary_search=True,
                auto_dispatch_profiles=_ALL_AUTO_DISPATCH_PROFILES,
            ),
            SourceDefinition(
                key="openalex",
                label="OpenAlex",
                category="search",
                selectable_in_unified=True,
                supports_primary_search=True,
                alternate_search_runner="openalex",
                auto_dispatch_profiles=_OPENALEX_AUTO_DISPATCH_PROFILES,
            ),
            SourceDefinition(
                key="semantic_scholar",
                label="Semantic Scholar",
                category="search",
                selectable_in_unified=True,
                supports_primary_search=True,
                aliases=("semantic-scholar",),
                alternate_search_runner="semantic_scholar",
                auto_dispatch_profiles=_SEMANTIC_SCHOLAR_AUTO_DISPATCH_PROFILES,
            ),
            SourceDefinition(
                key="europe_pmc",
                label="Europe PMC",
                category="search",
                selectable_in_unified=True,
                supports_primary_search=True,
                aliases=("europe-pmc",),
                alternate_search_runner="europe_pmc",
                auto_dispatch_profiles=_EUROPE_PMC_AUTO_DISPATCH_PROFILES,
            ),
            SourceDefinition(
                key="core",
                label="CORE",
                category="search",
                selectable_in_unified=True,
                supports_primary_search=True,
                alternate_search_runner="core",
            ),
            SourceDefinition(
                key="scopus",
                label="Scopus",
                category="search",
                access_tier="commercial",
                selectable_in_unified=True,
                supports_primary_search=True,
                enabled_by_default=False,
                aliases=("elsevier_scopus",),
                required_env_vars=("SCOPUS_API_KEY",),
                enable_env_var="SCOPUS_ENABLED",
                alternate_search_runner="scopus",
                description="Elsevier Scopus connector. Default off until licensed credentials are configured.",
            ),
            SourceDefinition(
                key="web_of_science",
                label="Web of Science",
                category="search",
                access_tier="commercial",
                selectable_in_unified=True,
                supports_primary_search=True,
                enabled_by_default=False,
                aliases=("web-of-science", "wos", "clarivate_wos"),
                required_env_vars=("WEB_OF_SCIENCE_API_KEY",),
                enable_env_var="WEB_OF_SCIENCE_ENABLED",
                alternate_search_runner="web_of_science",
                description="Clarivate Web of Science connector. Default off until licensed credentials are configured.",
            ),
            SourceDefinition(
                key="crossref",
                label="CrossRef",
                category="enrichment",
                selectable_in_unified=True,
                supports_primary_search=False,
                auto_dispatch_profiles=_CROSSREF_AUTO_DISPATCH_PROFILES,
            ),
            SourceDefinition(key="arxiv", label="arXiv", category="preprint"),
            SourceDefinition(key="medrxiv", label="medRxiv", category="preprint"),
            SourceDefinition(key="biorxiv", label="bioRxiv", category="preprint"),
            SourceDefinition(key="unpaywall", label="Unpaywall", category="fulltext"),
            SourceDefinition(key="openurl", label="OpenURL", category="fulltext"),
            SourceDefinition(key="openi", label="Open-i", category="image"),
            SourceDefinition(key="clinical_trials", label="ClinicalTrials.gov", category="structured"),
            SourceDefinition(key="ncbi_extended", label="NCBI Extended", category="structured"),
        )
    )


__all__ = [
    "SourceAutoDispatchProfile",
    "SourceDefinition",
    "SourceRegistry",
    "SourceSelection",
    "SourceSelectionError",
    "get_source_registry",
    "normalize_source_name",
]
