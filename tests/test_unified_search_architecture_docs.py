"""Contracts for the bilingual unified_search architecture inventory."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    ROOT / "docs/UNIFIED_SEARCH_ARCHITECTURE.md",
    ROOT / "docs/UNIFIED_SEARCH_ARCHITECTURE.zh-TW.md",
)

REQUIRED_RUNTIME_SYMBOLS = (
    "create_copilot_server",
    "wrap_copilot_compatibility",
    "CopilotStudioCompatibilityMiddleware",
    "PubMedMCPServer.tool",
    "PubMedMCPServer.call_tool",
    "MAX_MCP_TEXT_RESPONSE_CHARS",
    "tool_annotations",
    "tool_meta",
    "register_all_tools",
    "register_unified_search_tools",
    "PubMedSearchClient.unified_search",
    "UnifiedSearchUseCase.execute",
    "SourceBrokerPort",
    "SourceRegistryPort",
    "EnrichmentPort",
    "UnifiedSearchOutcome",
    "UnifiedSourceBroker",
    "UnifiedEnrichmentAdapter",
    "run_unified_search",
    "validate_unified_search_input_envelope",
    "normalize_unified_search_request",
    "_parse_filters_detailed",
    "_parse_options_detailed",
    "QueryAnalyzer.analyze",
    "SemanticEnhancer.enhance",
    "_build_mesh_query",
    "_build_entity_query",
    "_build_broad_query",
    "_basic_enhancement",
    "build_unified_search_plan",
    "_validate_query_dialect",
    "DispatchStrategy.get_sources",
    "SourceRegistry.resolve_unified_sources",
    "SourceAdapterResult",
    "coerce_optional_total",
    "build_default_search_functions",
    "validate_source_adapter_result",
    "_execute_deep_search",
    "execute_unified_search",
    "ClinicalTrialsCoverage",
    "validate_clinical_trials_rows",
    "clinical_trials_error_payload",
    "clinical-trials-adjunct/v1",
    "gather_source_adapter_calls",
    "execute_source_adapter_call",
    "_search_pubmed_adapter",
    "_search_europe_pmc_adapter",
    "_search_openalex_adapter",
    "_search_semantic_scholar_adapter",
    "_search_core_adapter",
    "_search_scopus_adapter",
    "_search_web_of_science_adapter",
    "_search_arxiv_adapter",
    "_search_medrxiv_adapter",
    "_search_biorxiv_adapter",
    "ResultAggregator",
    "UnionFind",
    "calculate_reproducibility",
    "_score_query_formality",
    "_score_result_stability",
    "_score_audit_completeness",
    "_enrich_with_crossref",
    "_enrich_with_unpaywall",
    "_format_unified_results",
    "_format_as_json",
    "_serialize_with_response_cap",
    "build_unified_search_artifact_envelope",
    "audit_unified_search_artifact",
    "SearchRunJournal",
    "_execute_pipeline_mode_outcome",
    "parse_pipeline_config_text",
    "parse_pipeline_config_file",
    "LimitBudget",
    "validate_pipeline_budgets",
    "validate_pipeline_action_contracts",
    "validate_pipeline_details_pmids",
    "validate_pipeline_discovery_pmid",
    "PipelineExecutor",
    "PipelineExecutor.execute",
    "alternate_search_adapter",
    "generate_pipeline_report",
)

REMOVED_RUNTIME_SYMBOLS = (
    "copilot_tools.py",
    "register_copilot_compatible_tools",
    "_default_deep_search_functions",
    "_coerce_deep_adapter_result",
    "_coerce_source_adapter_outcome",
    "_map_legacy_normalized_items",
    "alternate_search_fn",
    "`_parse_filters`",
    "`_parse_options`",
    "`_search_europe_pmc`",
    "`_search_openalex`",
    "`_search_semantic_scholar`",
    "`_search_core`",
    "`_search_scopus`",
    "`_search_web_of_science`",
    "`_search_preprint_source`",
    "`_search_arxiv`",
    "`_search_medrxiv`",
    "`_search_biorxiv`",
    "ResearchTree.to_mermaid_mindmap",
    "`_execute_pipeline_mode`",
    "_NoAliasSafeLoader",
    "_allows_preprint_articles",
    "_enrich_with_similarity_scores",
    "_enrich_with_api_similarity",
    "peer_reviewed_only",
    "similarity_score",
    "estimated_recall",
    "estimated_precision",
    "rank_correlation",
    "context_graph",
    "UnifiedSearchService",
    "application/unified/service.py",
    "presentation/mcp_server/tools/unified_source_search.py",
)

MERMAID_PATTERN = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def test_bilingual_pages_inventory_the_reachable_runtime_and_boundaries() -> None:
    for document in DOCS:
        content = document.read_text(encoding="utf-8")

        assert content.count("```mermaid") == 5
        assert "canonical adapter" in content.lower()
        assert "canonical registry" in content.lower()
        assert "contract v3" in content.lower()
        assert "result_filter_counts" in content
        assert "SourceAdapterResult" in content
        assert "`total_count >= len(items) >= 0`" in content
        assert "`status/items/errors`" in content
        assert "`SourceAdapterError.source/operation`" in content
        assert "500k" in content
        assert "depth 24" in content
        assert "2,000" in content
        assert "SourceRegistryPort" in content
        assert "non-empty finalized `strategies`" in content
        assert "tuple-returning" in content
        assert "pipeline" in content.lower()
        assert "Chronicle" in content
        for symbol in REQUIRED_RUNTIME_SYMBOLS:
            assert symbol in content, f"{document.name} is missing {symbol}"
        for symbol in REMOVED_RUNTIME_SYMBOLS:
            assert symbol not in content, f"{document.name} retains removed symbol {symbol}"

        source_search_row = next(line for line in content.splitlines() if "[`sources/unified_broker.py`]" in line)
        assert "`_search_pubmed`" not in source_search_row
        assert "`_require_source_adapter_result`" not in source_search_row
        source_contract_row = next(line for line in content.splitlines() if "[`source_contracts.py`]" in line)
        assert "`validate_source_adapter_result`" in source_contract_row

        pipeline_executor_row = next(line for line in content.splitlines() if "[`pipeline/executor.py`]" in line)
        assert "`alternate_search_adapter`" in pipeline_executor_row
        assert "SourceAdapterResult" in pipeline_executor_row

        unified_tool_row = next(line for line in content.splitlines() if "[`unified.py`]" in line)
        assert "`register_unified_search_tools`" in unified_tool_row
        assert "`_execute_pipeline_mode`" not in unified_tool_row
        assert "`_parse_filters`" not in unified_tool_row

        unified_pipeline_row = next(line for line in content.splitlines() if "[`unified_pipeline.py`]" in line)
        assert "`_execute_pipeline_mode_outcome`" in unified_pipeline_row
        assert "`_execute_pipeline_mode`" not in unified_pipeline_row


def test_bilingual_pages_share_the_same_five_architecture_diagrams() -> None:
    english_text = DOCS[0].read_text(encoding="utf-8")
    chinese_text = DOCS[1].read_text(encoding="utf-8")
    english = MERMAID_PATTERN.findall(english_text)
    chinese = MERMAID_PATTERN.findall(chinese_text)

    assert len(english) == len(chinese) == 5
    assert english == chinese

    english_inventory = english_text.split("## 4.", maxsplit=1)[1].split("## 5.", maxsplit=1)[0]
    chinese_inventory = chinese_text.split("## 4.", maxsplit=1)[1].split("## 5.", maxsplit=1)[0]
    assert set(re.findall(r"`([^`\n]+)`", english_inventory)) == set(re.findall(r"`([^`\n]+)`", chinese_inventory))


def test_bilingual_page_local_links_resolve() -> None:
    missing: list[str] = []
    for document in DOCS:
        for raw_target in LINK_PATTERN.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_text = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
            if not path_text:
                continue
            candidate = (document.parent / path_text).resolve()
            if not candidate.is_relative_to(ROOT) or not candidate.exists():
                missing.append(f"{document.name} -> {raw_target}")

    assert missing == []


def test_bilingual_pages_separate_completed_fixes_from_open_roadmap() -> None:
    english = DOCS[0].read_text(encoding="utf-8")
    chinese = DOCS[1].read_text(encoding="utf-8")

    for content in (english, chinese):
        assert "100k" in content
        assert "error-sentinel filtering" in content
        assert "rank_percentile" in content
        assert "exclude_detected_preprints" in content
        assert "include_detected_preprints" in content
        assert "heuristic_recall_proxy" in content
        assert "heuristic_precision_proxy" in content
        assert "pairwise_overlap" in content
        assert "MERMAID_NODE_MODULES" in content
        assert "LimitBudget" in content
        assert "MAX_PIPELINE_DETAILS_PMIDS" in content
        assert "SourceAdapterCall" in content
        assert "global 500k" in content.lower()
        assert "Context-gated ICD-9-CM detection" in content

        roadmap = content.split("## 7.", maxsplit=1)[1]
        assert "Pipeline structured output lacks the normal cap" not in roadmap
        assert "Pipeline structured output 無 normal response cap" not in roadmap
        assert "Pipeline fan-out has no run budget" not in roadmap
        assert "Pipeline fan-out 缺總預算" not in roadmap
        assert "Inline the reachable `_search_pubmed` relaxation wrapper" not in roadmap
        assert "將 reachable `_search_pubmed` relaxation wrapper" not in roadmap
        assert "ICD-9 false positive" not in roadmap

    assert "Improvements implemented in this audit" in english
    assert "Prioritized roadmap" in english
    assert "本輪已落地的改進" in chinese
    assert "改善路線圖" in chinese
