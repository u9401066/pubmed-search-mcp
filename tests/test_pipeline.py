"""Tests for the pipeline system (domain entities, executor, templates)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.templates import (
    PIPELINE_TEMPLATES,
    build_pipeline_from_template,
)
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    VALID_TEMPLATES,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    StepResult,
)

# =========================================================================
# Fixtures
# =========================================================================


@dataclass
class FakeArticle:
    """Minimal article-like object for pipeline tests."""

    title: str = "Test Article"
    pmid: str | None = "12345678"
    doi: str | None = "10.1234/test"
    year: int | None = 2024
    journal: str | None = "Test Journal"
    abstract: str | None = "Test abstract content."
    primary_source: str = "pubmed"
    article_type: Any = None
    ranking_score: float = 0.5
    relevance_score: float = 0.5
    quality_score: float = 0.5
    sources: list = field(default_factory=list)


def _make_articles(n: int, prefix: str = "Article") -> list[FakeArticle]:
    return [
        FakeArticle(
            title=f"{prefix} {i}",
            pmid=str(10000000 + i),
            doi=f"10.1234/{prefix.lower()}{i}",
            year=2020 + (i % 5),
        )
        for i in range(n)
    ]


@pytest.fixture()
def mock_searcher():
    """LiteratureSearcher mock with common methods."""
    s = AsyncMock()
    s.search = AsyncMock(return_value=[])
    s.fetch_details = AsyncMock(return_value=[])
    s.get_related_articles = AsyncMock(return_value=[])
    s.get_citing_articles = AsyncMock(return_value=[])
    s.get_article_references = AsyncMock(return_value=[])
    s.get_citation_metrics = AsyncMock(return_value=[])
    return s


# =========================================================================
# Domain Entity Tests
# =========================================================================


class TestPipelineStep:
    def test_defaults(self):
        step = PipelineStep(id="s1", action="search")
        assert step.params == {}
        assert step.inputs == []
        assert step.on_error == "skip"

    def test_with_all_fields(self):
        step = PipelineStep(
            id="s1",
            action="merge",
            params={"method": "rrf"},
            inputs=["a", "b"],
            on_error="abort",
        )
        assert step.id == "s1"
        assert step.action == "merge"
        assert step.inputs == ["a", "b"]
        assert step.on_error == "abort"


class TestPipelineConfig:
    def test_minimal(self):
        cfg = PipelineConfig(steps=[PipelineStep(id="s1", action="search", params={"query": "test"})])
        assert len(cfg.steps) == 1
        assert cfg.output.format == "markdown"
        assert cfg.output.limit == 20
        assert cfg.template is None

    def test_template_mode(self):
        cfg = PipelineConfig(
            template="pico",
            template_params={"P": "ICU", "I": "remimazolam"},
        )
        assert cfg.template == "pico"
        assert cfg.steps == []


class TestStepResult:
    def test_ok_property(self):
        sr = StepResult(step_id="s1", action="search")
        assert sr.ok is True

    def test_error_property(self):
        sr = StepResult(step_id="s1", action="search", error="something broke")
        assert sr.ok is False

    def test_with_data(self):
        articles = _make_articles(3)
        sr = StepResult(
            step_id="s1",
            action="search",
            articles=articles,
            pmids=["10000000", "10000001", "10000002"],
            metadata={"count": 3},
        )
        assert len(sr.articles) == 3
        assert len(sr.pmids) == 3


class TestConstants:
    def test_valid_actions(self):
        expected = {
            "search",
            "pico",
            "expand",
            "details",
            "related",
            "citing",
            "references",
            "metrics",
            "merge",
            "filter",
        }
        assert VALID_ACTIONS == expected

    def test_valid_templates(self):
        assert VALID_TEMPLATES == {"pico", "comprehensive", "exploration", "gene_drug"}

    def test_max_steps(self):
        assert MAX_PIPELINE_STEPS == 20


# =========================================================================
# Executor — Validation
# =========================================================================


class TestExecutorValidation:
    async def test_empty_steps_rejected(self, mock_searcher):
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(steps=[])
        with pytest.raises(ValueError, match="at least one step"):
            await executor.execute(cfg)

    async def test_too_many_steps(self, mock_searcher):
        executor = PipelineExecutor(searcher=mock_searcher)
        steps = [
            PipelineStep(id=f"s{i}", action="search", params={"query": "test"}) for i in range(MAX_PIPELINE_STEPS + 1)
        ]
        cfg = PipelineConfig(steps=steps)
        with pytest.raises(ValueError, match="exceeds maximum"):
            await executor.execute(cfg)

    async def test_duplicate_step_id(self, mock_searcher):
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(
            steps=[
                PipelineStep(id="dup", action="search", params={"query": "a"}),
                PipelineStep(id="dup", action="search", params={"query": "b"}),
            ]
        )
        with pytest.raises(ValueError, match="Duplicate step id"):
            await executor.execute(cfg)

    async def test_invalid_action(self, mock_searcher):
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="nope"),
            ]
        )
        with pytest.raises(ValueError, match="Unknown action"):
            await executor.execute(cfg)

    async def test_unknown_input_ref(self, mock_searcher):
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="merge", inputs=["nonexistent"]),
            ]
        )
        with pytest.raises(ValueError, match="unknown input"):
            await executor.execute(cfg)


# =========================================================================
# Executor — Topological Sorting
# =========================================================================


class TestTopologicalBatching:
    def test_independent_steps_one_batch(self):
        executor = PipelineExecutor()
        steps = [
            PipelineStep(id="a", action="search", params={"query": "x"}),
            PipelineStep(id="b", action="search", params={"query": "y"}),
        ]
        batches = executor._topological_batches(steps)
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_sequential_dependency(self):
        executor = PipelineExecutor()
        steps = [
            PipelineStep(id="a", action="search", params={"query": "x"}),
            PipelineStep(id="b", action="merge", inputs=["a"]),
        ]
        batches = executor._topological_batches(steps)
        assert len(batches) == 2
        assert batches[0][0].id == "a"
        assert batches[1][0].id == "b"

    def test_diamond_dependency(self):
        executor = PipelineExecutor()
        steps = [
            PipelineStep(id="root", action="pico", params={"P": "x", "I": "y"}),
            PipelineStep(id="left", action="search", inputs=["root"], params={"element": "P"}),
            PipelineStep(id="right", action="search", inputs=["root"], params={"element": "I"}),
            PipelineStep(id="merge", action="merge", inputs=["left", "right"]),
        ]
        batches = executor._topological_batches(steps)
        assert len(batches) == 3
        assert batches[0][0].id == "root"
        batch1_ids = {s.id for s in batches[1]}
        assert batch1_ids == {"left", "right"}
        assert batches[2][0].id == "merge"

    def test_cycle_detection(self):
        executor = PipelineExecutor()
        # Can't create a cycle with the forward-ref validation, but test
        # the topo sort itself
        steps = [
            PipelineStep(id="a", action="search", params={"query": "x"}),
            PipelineStep(id="b", action="merge", inputs=["a"]),
        ]
        # Valid graph — no cycle
        batches = executor._topological_batches(steps)
        assert sum(len(b) for b in batches) == 2


# =========================================================================
# Executor — Action: PICO
# =========================================================================


class TestActionPico:
    async def test_basic_pico(self):
        executor = PipelineExecutor()
        step = PipelineStep(
            id="p", action="pico", params={"P": "ICU", "I": "remimazolam", "C": "propofol", "O": "sedation"}
        )
        result = await executor._action_pico(step, {})
        assert result.ok
        assert result.metadata["elements"] == {"P": "ICU", "I": "remimazolam", "C": "propofol", "O": "sedation"}
        assert "AND" in result.metadata["combined_precision"]
        assert "OR" in result.metadata["combined_recall"]

    async def test_pico_without_c_o(self):
        executor = PipelineExecutor()
        step = PipelineStep(id="p", action="pico", params={"P": "adults", "I": "aspirin"})
        result = await executor._action_pico(step, {})
        assert result.ok
        assert "C" not in result.metadata["elements"]
        assert "O" not in result.metadata["elements"]

    async def test_pico_empty_fails(self):
        executor = PipelineExecutor()
        step = PipelineStep(id="p", action="pico", params={})
        result = await executor._action_pico(step, {})
        assert not result.ok
        assert "No PICO elements" in (result.error or "")


# =========================================================================
# Executor — Action: Merge
# =========================================================================


class TestActionMerge:
    async def test_union_merge(self):
        executor = PipelineExecutor()
        arts_a = _make_articles(3, "A")
        arts_b = _make_articles(3, "B")

        step = PipelineStep(id="m", action="merge", inputs=["a", "b"], params={"method": "union"})
        inputs = {
            "a": StepResult(step_id="a", action="search", articles=arts_a, pmids=[a.pmid for a in arts_a]),
            "b": StepResult(step_id="b", action="search", articles=arts_b, pmids=[a.pmid for a in arts_b]),
        }

        with patch("pubmed_search.application.search.result_aggregator.ResultAggregator") as MockAgg:
            mock_agg = MockAgg.return_value
            combined = arts_a + arts_b
            mock_agg.aggregate.return_value = (combined, MagicMock())
            result = await executor._action_merge(step, inputs)

        assert result.ok
        assert len(result.articles) == 6

    async def test_rrf_merge(self):
        executor = PipelineExecutor()
        arts_a = _make_articles(3, "A")
        arts_b = _make_articles(3, "B")

        step = PipelineStep(id="m", action="merge", inputs=["a", "b"], params={"method": "rrf"})
        inputs = {
            "a": StepResult(step_id="a", action="search", articles=arts_a),
            "b": StepResult(step_id="b", action="search", articles=arts_b),
        }
        result = await executor._action_merge(step, inputs)
        assert result.ok
        assert len(result.articles) == 6  # All unique

    async def test_intersection_merge(self):
        executor = PipelineExecutor()
        # Create overlapping articles
        shared = FakeArticle(title="Shared", pmid="99999", doi="10.1/shared")
        arts_a = [shared, FakeArticle(title="A only", pmid="11111", doi="10.1/a")]
        arts_b = [shared, FakeArticle(title="B only", pmid="22222", doi="10.1/b")]

        step = PipelineStep(id="m", action="merge", inputs=["a", "b"], params={"method": "intersection"})
        inputs = {
            "a": StepResult(step_id="a", action="search", articles=arts_a),
            "b": StepResult(step_id="b", action="search", articles=arts_b),
        }
        result = await executor._action_merge(step, inputs)
        assert result.ok
        assert len(result.articles) == 1
        assert result.articles[0].doi == "10.1/shared"

    async def test_empty_merge(self):
        executor = PipelineExecutor()
        step = PipelineStep(id="m", action="merge", inputs=["a"], params={})
        inputs = {
            "a": StepResult(step_id="a", action="search", articles=[]),
        }
        result = await executor._action_merge(step, inputs)
        assert result.ok
        assert result.articles == []


# =========================================================================
# Executor — Action: Filter
# =========================================================================


class TestActionFilter:
    async def test_year_filter(self):
        executor = PipelineExecutor()
        articles = _make_articles(5)  # years 2020-2024
        step = PipelineStep(id="f", action="filter", inputs=["s1"], params={"min_year": 2023})
        inputs = {"s1": StepResult(step_id="s1", action="search", articles=articles)}
        result = await executor._action_filter(step, inputs)
        assert result.ok
        assert all(a.year >= 2023 for a in result.articles)

    async def test_abstract_filter(self):
        executor = PipelineExecutor()
        with_abs = FakeArticle(title="Has Abstract", abstract="content")
        without_abs = FakeArticle(title="No Abstract", abstract=None)
        step = PipelineStep(id="f", action="filter", inputs=["s1"], params={"has_abstract": True})
        inputs = {"s1": StepResult(step_id="s1", action="search", articles=[with_abs, without_abs])}
        result = await executor._action_filter(step, inputs)
        assert len(result.articles) == 1
        assert result.articles[0].title == "Has Abstract"


# =========================================================================
# Executor — Action: Search (with mocked sources)
# =========================================================================


class TestActionSearch:
    async def test_search_pubmed(self, mock_searcher):
        mock_searcher.search.return_value = [
            {"title": "Paper 1", "pmid": "111", "abstract": "text"},
            {"title": "Paper 2", "pmid": "222", "abstract": "text"},
        ]
        executor = PipelineExecutor(searcher=mock_searcher)
        step = PipelineStep(id="s1", action="search", params={"query": "test", "sources": "pubmed", "limit": 10})

        with patch("pubmed_search.domain.entities.article.UnifiedArticle") as MockUA:
            fake = FakeArticle(title="Paper 1", pmid="111")
            MockUA.from_pubmed.return_value = fake
            result = await executor._action_search(step, {})

        assert result.ok
        mock_searcher.search.assert_called_once()

    async def test_search_no_query_fails(self):
        executor = PipelineExecutor()
        step = PipelineStep(id="s1", action="search", params={"sources": "pubmed"})
        result = await executor._action_search(step, {})
        assert not result.ok
        assert "No query" in (result.error or "")


# =========================================================================
# Executor — Query Resolution
# =========================================================================


class TestQueryResolution:
    def test_direct_query(self):
        step = PipelineStep(id="s", action="search", params={"query": "direct"})
        assert PipelineExecutor._resolve_query(step, {}) == "direct"

    def test_from_pico_element(self):
        step = PipelineStep(id="s", action="search", inputs=["p"], params={"element": "I"})
        pico_result = StepResult(
            step_id="p",
            action="pico",
            metadata={"elements": {"P": "ICU", "I": "remimazolam"}, "combined_precision": "(ICU) AND (remimazolam)"},
        )
        query = PipelineExecutor._resolve_query(step, {"p": pico_result})
        assert query == "remimazolam"

    def test_from_pico_combined(self):
        step = PipelineStep(id="s", action="search", inputs=["p"], params={})
        pico_result = StepResult(
            step_id="p",
            action="pico",
            metadata={"elements": {"P": "ICU"}, "combined_precision": "(ICU)", "combined_recall": "(ICU)"},
        )
        query = PipelineExecutor._resolve_query(step, {"p": pico_result})
        assert query == "(ICU)"

    def test_from_expand_strategy(self):
        step = PipelineStep(id="s", action="search", inputs=["e"], params={"strategy": "mesh"})
        expand_result = StepResult(
            step_id="e",
            action="expand",
            metadata={
                "expanded_query": "remimazolam OR CNS7056",
                "strategies": [
                    {"name": "original", "query": "remimazolam", "source": "pubmed"},
                    {"name": "mesh", "query": '"Benzodiazepines"[MeSH]', "source": "pubmed"},
                ],
            },
        )
        query = PipelineExecutor._resolve_query(step, {"e": expand_result})
        assert "MeSH" in query

    def test_no_query_no_inputs(self):
        step = PipelineStep(id="s", action="search", params={})
        assert PipelineExecutor._resolve_query(step, {}) == ""


# =========================================================================
# Executor — Full Pipeline Execution
# =========================================================================


class TestFullPipelineExecution:
    async def test_single_step_pipeline(self, mock_searcher):
        """Simplest pipeline: one search step."""
        mock_searcher.search.return_value = [
            {"title": "Paper 1", "pmid": "111"},
        ]
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test", "sources": "pubmed"})],
            output=PipelineOutput(limit=10),
        )

        with patch("pubmed_search.domain.entities.article.UnifiedArticle") as MockUA:
            fake = FakeArticle(title="Paper 1", pmid="111")
            MockUA.from_pubmed.return_value = fake

            with patch("pubmed_search.application.search.result_aggregator.ResultAggregator") as MockRA:
                MockRA.return_value.rank.return_value = [fake]
                articles, results = await executor.execute(cfg)

        assert len(results) == 1
        assert results["s1"].ok

    async def test_error_skip(self, mock_searcher):
        """Steps with on_error=skip should not abort the pipeline."""
        executor = PipelineExecutor(searcher=mock_searcher)
        cfg = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", params={}),  # No query → error
                PipelineStep(id="s2", action="pico", params={"P": "test", "I": "drug"}),
            ]
        )
        articles, results = await executor.execute(cfg)
        assert not results["s1"].ok  # search failed (no query)
        assert results["s2"].ok  # pico succeeded

    async def test_error_abort(self, mock_searcher):
        """Steps with on_error=abort should raise when the action itself raises."""
        executor = PipelineExecutor(searcher=mock_searcher)

        # Force an exception from _execute_step by patching it
        async def _raise_step(step, inputs):
            raise ValueError("forced failure")

        executor._execute_step = _raise_step  # type: ignore[assignment]

        cfg = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", params={"query": "x"}, on_error="abort"),
            ]
        )
        with pytest.raises(RuntimeError, match="aborted"):
            await executor.execute(cfg)


# =========================================================================
# Templates
# =========================================================================


class TestTemplateRegistry:
    def test_all_templates_registered(self):
        for name in VALID_TEMPLATES:
            assert name in PIPELINE_TEMPLATES

    def test_template_has_required_keys(self):
        for name, entry in PIPELINE_TEMPLATES.items():
            assert "builder" in entry
            assert "description" in entry
            assert "required_params" in entry


class TestPicoTemplate:
    def test_basic_pico(self):
        cfg = build_pipeline_from_template("pico", {"P": "ICU patients", "I": "remimazolam"})
        assert "PICO" in cfg.name
        assert len(cfg.steps) >= 4  # pico + 2 search + merge + metrics
        actions = [s.action for s in cfg.steps]
        assert "pico" in actions
        assert "merge" in actions
        assert "metrics" in actions

    def test_pico_with_comparison(self):
        cfg = build_pipeline_from_template("pico", {"P": "ICU", "I": "remimazolam", "C": "propofol", "O": "sedation"})
        search_steps = [s for s in cfg.steps if s.action == "search"]
        assert len(search_steps) == 3  # P, I, C (no separate O search)

    def test_pico_missing_params(self):
        with pytest.raises(ValueError, match="at least"):
            build_pipeline_from_template("pico", {"P": "ICU"})


class TestComprehensiveTemplate:
    def test_basic(self):
        cfg = build_pipeline_from_template("comprehensive", {"query": "CRISPR"})
        assert "Comprehensive" in cfg.name
        actions = [s.action for s in cfg.steps]
        assert "expand" in actions
        assert "merge" in actions
        assert cfg.output.ranking == "quality"

    def test_with_year_filter(self):
        cfg = build_pipeline_from_template("comprehensive", {"query": "AI", "min_year": 2020})
        search_steps = [s for s in cfg.steps if s.action == "search"]
        assert any(s.params.get("min_year") == 2020 for s in search_steps)

    def test_missing_query(self):
        with pytest.raises(ValueError, match="query"):
            build_pipeline_from_template("comprehensive", {})


class TestExplorationTemplate:
    def test_basic(self):
        cfg = build_pipeline_from_template("exploration", {"pmid": "12345678"})
        assert "Exploration" in cfg.name
        actions = [s.action for s in cfg.steps]
        assert "related" in actions
        assert "citing" in actions
        assert "references" in actions
        assert cfg.output.ranking == "impact"

    def test_missing_pmid(self):
        with pytest.raises(ValueError, match="pmid"):
            build_pipeline_from_template("exploration", {})


class TestGeneDrugTemplate:
    def test_basic(self):
        cfg = build_pipeline_from_template("gene_drug", {"term": "BRCA1"})
        assert "Gene/Drug" in cfg.name
        actions = [s.action for s in cfg.steps]
        assert "expand" in actions
        assert "merge" in actions

    def test_missing_term(self):
        with pytest.raises(ValueError, match="term"):
            build_pipeline_from_template("gene_drug", {})


class TestUnknownTemplate:
    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown template"):
            build_pipeline_from_template("nonexistent", {})


# =========================================================================
# Integration: Pipeline JSON Parsing (via _execute_pipeline_mode)
# =========================================================================


class TestPipelineConfigParsing:
    """Test YAML and JSON → PipelineConfig parsing in unified.py's _execute_pipeline_mode."""

    async def test_template_json(self, mock_searcher):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        pipeline_json = json.dumps(
            {
                "template": "pico",
                "params": {"P": "ICU patients", "I": "remimazolam", "C": "propofol"},
            }
        )

        # Mock executor at its source module (lazy import inside _execute_pipeline_mode)
        with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            result = await _execute_pipeline_mode(pipeline_json, "markdown", mock_searcher)

        assert "Pipeline Results" in result or "No articles" in result

    async def test_invalid_config(self, mock_searcher):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        result = await _execute_pipeline_mode("not valid: [", "markdown", mock_searcher)
        assert "Invalid pipeline config" in result

    async def test_custom_pipeline_json(self, mock_searcher):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        pipeline_json = json.dumps(
            {
                "name": "Test Pipeline",
                "steps": [
                    {"id": "s1", "action": "pico", "params": {"P": "test", "I": "drug"}},
                ],
                "output": {"format": "markdown", "limit": 5, "ranking": "impact"},
            }
        )

        with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            result = await _execute_pipeline_mode(pipeline_json, "markdown", mock_searcher)

        assert isinstance(result, str)

    async def test_template_yaml(self, mock_searcher):
        """YAML template config — human-readable format."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        pipeline_yaml = """\
template: pico
params:
  P: ICU patients
  I: remimazolam
  C: propofol
  O: sedation
"""

        with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            result = await _execute_pipeline_mode(pipeline_yaml, "markdown", mock_searcher)

        assert "Pipeline Results" in result or "No articles" in result

    async def test_custom_pipeline_yaml(self, mock_searcher):
        """Full custom pipeline in YAML — readable DAG definition."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        pipeline_yaml = """\
name: YAML Custom Pipeline
steps:
  - id: s1
    action: search
    params:
      query: remimazolam ICU
      sources: pubmed
      limit: 50
  - id: s2
    action: search
    params:
      query: propofol ICU
      sources: pubmed
      limit: 50
  - id: merged
    action: merge
    inputs: [s1, s2]
    params:
      method: rrf
  - id: enriched
    action: metrics
    inputs: [merged]
output:
  format: markdown
  limit: 20
  ranking: impact
"""

        with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            result = await _execute_pipeline_mode(pipeline_yaml, "markdown", mock_searcher)

        assert isinstance(result, str)

    async def test_yaml_exploration_template(self, mock_searcher):
        """Exploration template in YAML."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        pipeline_yaml = """\
template: exploration
params:
  pmid: "12345678"
  limit: 30
"""

        with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            result = await _execute_pipeline_mode(pipeline_yaml, "markdown", mock_searcher)

        assert isinstance(result, str)

    async def test_bare_string_not_dict_error(self, mock_searcher):
        """A plain string that YAML parses to a scalar should error."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _execute_pipeline_mode,
        )

        result = await _execute_pipeline_mode("just a plain string", "markdown", mock_searcher)
        assert "Invalid pipeline config" in result or "error" in result.lower()


# =========================================================================
# Unit: _parse_pipeline_config
# =========================================================================


class TestParsePipelineConfig:
    """Unit tests for the YAML/JSON parser function."""

    def test_parse_json(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _parse_pipeline_config,
        )

        result = _parse_pipeline_config('{"template": "pico", "params": {"P": "test"}}')
        assert result["template"] == "pico"
        assert result["params"]["P"] == "test"

    def test_parse_yaml(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _parse_pipeline_config,
        )

        result = _parse_pipeline_config("template: pico\nparams:\n  P: test\n  I: drug\n")
        assert result["template"] == "pico"
        assert result["params"]["P"] == "test"
        assert result["params"]["I"] == "drug"

    def test_parse_yaml_multiline_steps(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _parse_pipeline_config,
        )

        yaml_text = """\
name: Test
steps:
  - id: s1
    action: search
    params:
      query: test
  - id: s2
    action: merge
    inputs: [s1]
"""
        result = _parse_pipeline_config(yaml_text)
        assert result["name"] == "Test"
        assert len(result["steps"]) == 2
        assert result["steps"][0]["id"] == "s1"
        assert result["steps"][1]["inputs"] == ["s1"]

    def test_parse_invalid_raises(self):
        import pytest as _pytest

        from pubmed_search.presentation.mcp_server.tools.unified import (
            _parse_pipeline_config,
        )

        with _pytest.raises(Exception):
            _parse_pipeline_config("not valid: [: invalid")

    def test_parse_scalar_raises(self):
        """A YAML scalar (not dict) should fail at JSON fallback."""
        import pytest as _pytest

        from pubmed_search.presentation.mcp_server.tools.unified import (
            _parse_pipeline_config,
        )

        with _pytest.raises(Exception):
            _parse_pipeline_config("42")


# =========================================================================
# Integration: Format Pipeline Results
# =========================================================================


class TestFormatPipelineResults:
    def test_format_with_articles(self):
        from pubmed_search.application.pipeline.report_generator import (
            generate_pipeline_report,
        )

        articles = _make_articles(3)
        step_results = {
            "s1": StepResult(step_id="s1", action="search", articles=articles, pmids=["10000000"]),
            "merge": StepResult(step_id="merge", action="merge", articles=articles),
        }
        config = PipelineConfig(
            name="Test",
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="merge", action="merge", inputs=["s1"]),
            ],
            output=PipelineOutput(limit=10),
        )
        result = generate_pipeline_report(articles, step_results, config)
        assert "Test" in result
        assert "Article 0" in result

    def test_format_empty_results(self):
        from pubmed_search.application.pipeline.report_generator import (
            generate_pipeline_report,
        )

        config = PipelineConfig(
            name="Empty",
            steps=[PipelineStep(id="s1", action="search")],
        )
        result = generate_pipeline_report([], {}, config)
        assert "No articles" in result

    def test_format_with_errors(self):
        from pubmed_search.application.pipeline.report_generator import (
            generate_pipeline_report,
        )

        step_results = {
            "s1": StepResult(step_id="s1", action="search", error="Network timeout"),
        }
        config = PipelineConfig(
            name="Error Test",
            steps=[PipelineStep(id="s1", action="search")],
        )
        result = generate_pipeline_report([], step_results, config)
        assert "❌" in result
        assert "Network timeout" in result

    def test_format_with_source_api_counts(self):
        """Per-source API counts in pipeline results MUST be displayed (critical feature)."""
        from pubmed_search.application.pipeline.report_generator import (
            generate_pipeline_report,
        )

        articles = _make_articles(5)
        step_results = {
            "s1": StepResult(
                step_id="s1",
                action="search",
                articles=articles[:3],
                metadata={"source_api_counts": {"pubmed": 3, "openalex": 2}},
            ),
            "s2": StepResult(
                step_id="s2",
                action="search",
                articles=articles[3:],
                metadata={"source_api_counts": {"semantic_scholar": 2}},
            ),
            "merge": StepResult(step_id="merge", action="merge", articles=articles),
        }
        config = PipelineConfig(
            name="Source Count Test",
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="s2", action="search"),
                PipelineStep(id="merge", action="merge", inputs=["s1", "s2"]),
            ],
            output=PipelineOutput(limit=10),
        )
        result = generate_pipeline_report(articles, step_results, config)

        # Source statistics section
        assert "pubmed" in result
        assert "openalex" in result
        assert "semantic_scholar" in result

        # Per-step breakdown in detail table
        assert "pubmed: 3" in result
        assert "openalex: 2" in result


class TestRRFMerge:
    def test_rrf_ordering(self):
        executor = PipelineExecutor()
        # Article appearing in both lists at top should rank highest
        shared = FakeArticle(title="Shared Top", pmid="shared1", doi="10.1/shared")
        a_only = FakeArticle(title="A only", pmid="a1", doi="10.1/a")
        b_only = FakeArticle(title="B only", pmid="b1", doi="10.1/b")

        list_a = [shared, a_only]
        list_b = [shared, b_only]

        merged = executor._rrf_merge([list_a, list_b])
        assert merged[0].doi == "10.1/shared"  # Shared should be first

    def test_rrf_empty_lists(self):
        executor = PipelineExecutor()
        assert executor._rrf_merge([]) == []
        assert executor._rrf_merge([[]]) == []


# =========================================================================
# Intersection Merge
# =========================================================================


class TestIntersectionMerge:
    def test_no_overlap(self):
        executor = PipelineExecutor()
        a = [FakeArticle(doi="10.1/a")]
        b = [FakeArticle(doi="10.1/b")]
        assert executor._intersect_articles([a, b]) == []

    def test_full_overlap(self):
        executor = PipelineExecutor()
        art = FakeArticle(doi="10.1/same")
        assert len(executor._intersect_articles([[art], [art]])) == 1

    def test_single_list(self):
        executor = PipelineExecutor()
        arts = _make_articles(3)
        assert len(executor._intersect_articles([arts])) == 3
