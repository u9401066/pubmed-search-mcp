"""Regression coverage for fulltext policy registry selection.

Design:
    These tests pin the policy-selection rules that sit above the downloader
    implementation. They verify that identifier combinations resolve to the
    expected retrieval policy and that the cached registry remains stable.

Maintenance:
    Update these tests when policy ordering or registry singleton behavior
    changes. Keep them focused on selection semantics rather than transport or
    parser details.
"""

from __future__ import annotations

import pytest

from pubmed_search.infrastructure.sources.fulltext_registry import FulltextRegistry, get_fulltext_registry


class TestFulltextRegistry:
    def test_structured_first_policy_for_pmcid(self):
        registry = FulltextRegistry()

        policy = registry.resolve_policy(
            pmcid="PMC7096777",
            pmid=None,
            doi=None,
            extended_sources=False,
        )

        assert policy.key == "structured_first"
        assert policy.sources[0] == "europe_pmc"

    def test_expanded_policy_for_extended_sources(self):
        registry = FulltextRegistry()

        policy = registry.resolve_policy(
            pmcid=None,
            pmid="12345678",
            doi="10.1234/test",
            extended_sources=True,
        )

        assert policy.key == "expanded_discovery"
        assert "extended" in policy.sources

    def test_requires_at_least_one_identifier(self):
        registry = FulltextRegistry()

        with pytest.raises(ValueError, match="At least one identifier"):
            registry.resolve_policy(
                pmcid=None,
                pmid=None,
                doi=None,
                extended_sources=False,
            )

    def test_singleton_registry(self):
        assert get_fulltext_registry() is get_fulltext_registry()
