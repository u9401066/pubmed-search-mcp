"""
Copilot Studio Compatible MCP Tools — 為何需要這個額外包裝層？

========================================================================
背景：Copilot Studio 的 OpenAPI Schema 限制
========================================================================

Microsoft Copilot Studio 在匯入 MCP 工具時，會將工具的 JSON Schema
轉換為 OpenAPI 格式。然而 Copilot Studio 的 schema parser 有以下
**已知限制**（截至 2025 年底）：

1. **anyOf / oneOf 不支援**
   - Python `Optional[int]` → JSON Schema `anyOf: [{type: int}, {type: null}]`
   - Copilot Studio 遇到 anyOf 會**截斷整個工具 schema**，導致工具無法使用
   - 解法：所有參數改用單一型別，用哨兵值取代 None（如 `min_year: int = 0`）

2. **exclusiveMinimum 必須是 boolean**
   - JSON Schema Draft 4 用 boolean，Draft 6+ 用 number
   - Copilot Studio 只接受 Draft 4 的 boolean 形式
   - Pydantic v2 / FastMCP 預設產生 Draft 6+ 格式 → 衝突

3. **$ref 參照型別不支援**
   - 巢狀 Pydantic model 會產生 $ref → 無法解析

========================================================================
設計決策
========================================================================

- 本模組**刻意重新定義**一組精簡版工具，而非直接重用 tools/ 下的完整版
- 參數全部使用 primitive types（str, int, bool），不用 Optional/Union
- 內部呼叫與完整版相同的 searcher/client 方法，邏輯完全一致
- 透過 InputNormalizer 將哨兵值（0, ""）轉回 None
- 工具數量較少（12 個 vs 完整版 40 個），只暴露 Copilot Studio 最常用的功能

========================================================================
何時使用
========================================================================

- `register_copilot_compatible_tools()` 僅在 Copilot Studio 模式啟用時呼叫
- 一般 MCP client（Claude, Cursor 等）使用 tools/ 下的完整版工具
- 參見 run_copilot.py 和 server.py 中的啟用邏輯

參考：
- https://learn.microsoft.com/en-us/microsoft-copilot-studio/agent-extend-action-mcp
- https://github.com/anthropics/mcp/issues (schema compatibility discussions)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from .tools._common import (
    InputNormalizer,
    ResponseFormatter,
    _cache_results,
    format_search_results,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (eliminate repetitive PMID-tool boilerplate)
# ---------------------------------------------------------------------------


async def _pmid_search(
    searcher: LiteratureSearcher,
    pmid: str,
    method_name: str,
    tool_name: str,
    limit: int,
    max_limit: int,
    cache_prefix: str,
    no_results_label: str,
) -> str:
    """Common pattern: validate PMID → call searcher method → cache & format."""
    clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
    if not clean_pmid:
        return ResponseFormatter.error("Invalid PMID", suggestion="Use numeric PMID", tool_name=tool_name)

    limit = InputNormalizer.normalize_limit(limit, default=limit, max_val=max_limit)

    try:
        method: Callable[..., Coroutine[Any, Any, list]] = getattr(searcher, method_name)
        results = await method(clean_pmid, max_results=limit)

        if not results:
            return f"No {no_results_label} found for PMID {clean_pmid}"

        _cache_results(results, f"{cache_prefix}:{clean_pmid}")
        return format_search_results(results)

    except Exception as e:
        logger.exception(f"{tool_name} failed: {e}")
        return ResponseFormatter.error(e, tool_name=tool_name)


async def _ncbi_extended_search(
    method_name: str,
    tool_name: str,
    query: str,
    limit: int,
    max_limit: int,
    no_results_label: str,
    **extra_kwargs: Any,
) -> str:
    """Common pattern: NCBIExtendedClient search → JSON output."""
    limit = InputNormalizer.normalize_limit(limit, default=limit, max_val=max_limit)

    try:
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            get_ncbi_extended_client,
        )

        client = get_ncbi_extended_client()
        method = getattr(client, method_name)
        results = await method(query=query, limit=limit, **extra_kwargs)

        if not results:
            return f"No {no_results_label} found for '{query}'"

        return json.dumps(results, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.exception(f"{tool_name} failed: {e}")
        return ResponseFormatter.error(e, tool_name=tool_name)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_copilot_compatible_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register Copilot Studio compatible tools (simplified schemas)."""

    # ========================================================================
    # Core Search
    # ========================================================================

    @mcp.tool()
    async def search_pubmed(
        query: str,
        limit: int = 10,
        min_year: int = 0,
        max_year: int = 0,
    ) -> str:
        """Search PubMed for scientific literature.

        Args:
            query: Search query (keywords, MeSH terms, etc.)
            limit: Maximum results (1-100, default 10)
            min_year: Minimum publication year (0 = no filter)
            max_year: Maximum publication year (0 = no filter)
        """
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
        try:
            results = await searcher.search(
                query=query,
                limit=limit,
                min_year=min_year if min_year > 1900 else None,
                max_year=max_year if max_year > 1900 else None,
            )
            if not results:
                return ResponseFormatter.no_results(query=query)
            _cache_results(results, query)
            return format_search_results(results)
        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_pubmed")

    @mcp.tool()
    async def get_article(pmid: str) -> str:
        """Get detailed information about a specific article by PMID.

        Args:
            pmid: PubMed ID (e.g., "12345678" or "PMID:12345678")
        """
        clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not clean_pmid:
            return ResponseFormatter.error(
                "Invalid PMID format",
                suggestion="Use numeric PMID like '12345678'",
                example='get_article(pmid="12345678")',
                tool_name="get_article",
            )
        try:
            results = await searcher.fetch_details([clean_pmid])
            if not results:
                return f"Article with PMID {clean_pmid} not found."

            a = results[0]
            parts = [
                f"## {a.get('title', 'No title')}",
                "",
                f"**PMID**: {a.get('pmid', '')}",
            ]
            if a.get("doi"):
                parts.append(f"**DOI**: {a['doi']}")
            if a.get("pmc_id"):
                parts.append(f"**PMC**: {a['pmc_id']}")
            parts.append("")

            authors = a.get("authors", [])
            if authors:
                s = ", ".join(authors[:5])
                if len(authors) > 5:
                    s += f" et al. ({len(authors)} authors)"
                parts.append(f"**Authors**: {s}")
            if a.get("journal"):
                parts.append(f"**Journal**: {a['journal']} ({a.get('year', '')})")
            if a.get("abstract"):
                parts.append(f"\n**Abstract**:\n{a['abstract']}")
            return "\n".join(parts)
        except Exception as e:
            logger.exception(f"Failed to get article: {e}")
            return ResponseFormatter.error(e, tool_name="get_article")

    # -- PMID-based exploration tools (share _pmid_search helper) -----------

    @mcp.tool()
    async def find_related(pmid: str, limit: int = 10) -> str:
        """Find articles related to a given article.

        Args:
            pmid: PubMed ID of the reference article
            limit: Maximum related articles (1-50, default 10)
        """
        return await _pmid_search(
            searcher,
            pmid,
            "find_related_articles",
            "find_related",
            limit,
            50,
            "related",
            "related articles",
        )

    @mcp.tool()
    async def find_citations(pmid: str, limit: int = 20) -> str:
        """Find articles that cite a given article.

        Args:
            pmid: PubMed ID of the cited article
            limit: Maximum citing articles (1-100, default 20)
        """
        return await _pmid_search(
            searcher,
            pmid,
            "find_citing_articles",
            "find_citations",
            limit,
            100,
            "citations",
            "citing articles",
        )

    @mcp.tool()
    async def get_references(pmid: str, limit: int = 20) -> str:
        """Get the reference list of an article.

        Args:
            pmid: PubMed ID of the article
            limit: Maximum references (1-100, default 20)
        """
        return await _pmid_search(
            searcher,
            pmid,
            "get_article_references",
            "get_references",
            limit,
            100,
            "references",
            "references",
        )

    # ========================================================================
    # PICO and Query Generation
    # ========================================================================

    @mcp.tool()
    def analyze_clinical_question(question: str) -> str:
        """Parse a clinical question into PICO elements (Population, Intervention, Comparison, Outcome).

        Args:
            question: Clinical question in natural language
        """
        try:
            return json.dumps(
                {
                    "question": question,
                    "note": "Use parse_pico MCP tool for full PICO analysis",
                    "suggestion": f'parse_pico(description="{question}")',
                },
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception(f"PICO analysis failed: {e}")
            return ResponseFormatter.error(e, tool_name="analyze_clinical_question")

    @mcp.tool()
    async def expand_search_terms(topic: str) -> str:
        """Expand a search topic with MeSH terms and synonyms.

        Args:
            topic: Search topic or keyword
        """
        from .tools._common import get_strategy_generator

        strategy_gen = get_strategy_generator()
        if strategy_gen:
            try:
                result = await strategy_gen.generate_strategies(
                    topic=topic,
                    strategy="comprehensive",
                    use_mesh=True,
                    check_spelling=True,
                    include_suggestions=True,
                )
                return json.dumps(result, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Strategy generator failed: {e}")

        return f"Search suggestions for '{topic}':\n1. ({topic})[Title/Abstract]\n2. ({topic})[MeSH Terms]"

    # ========================================================================
    # Full Text and Export
    # ========================================================================

    @mcp.tool()
    async def get_fulltext(pmcid: str, sections: str = "") -> str:
        """Get full text of an article from Europe PMC.

        Args:
            pmcid: PMC ID (e.g., "PMC7096777" or "7096777")
            sections: Comma-separated section names (empty = all).
                     Options: introduction, methods, results, discussion, conclusion
        """
        clean_pmcid = InputNormalizer.normalize_pmcid(pmcid)
        if not clean_pmcid:
            return ResponseFormatter.error(
                "Invalid PMC ID",
                suggestion="Use format like 'PMC7096777' or '7096777'",
                tool_name="get_fulltext",
            )
        try:
            from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient

            client = EuropePMCClient()
            xml_content = await client.get_fulltext_xml(clean_pmcid)
            if not xml_content:
                return f"Full text not available for {clean_pmcid}"

            parsed = client.parse_fulltext_xml(xml_content)
            if "error" in parsed:
                return f"Full text XML retrieved but parsing failed: {parsed['error']}"

            section_filter = [s.strip().lower() for s in sections.split(",") if s.strip()] if sections else []
            output = [f"## Full Text: {clean_pmcid}"]
            if parsed.get("abstract"):
                output.append(f"\n### Abstract\n{parsed['abstract']}")
            for sec in parsed.get("sections", []):
                title = sec.get("title", "Section")
                if section_filter and title.lower() not in section_filter:
                    continue
                output.append(f"\n### {title}")
                output.append(sec.get("content", ""))
            return "\n".join(output)
        except Exception as e:
            logger.exception(f"Get fulltext failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_fulltext")

    @mcp.tool()
    async def export_citations(
        pmids: str,
        format: Literal["ris", "bibtex", "csv"] = "ris",
    ) -> str:
        """Export citations in various formats.

        Args:
            pmids: Comma-separated PMIDs or "last" for last search results
            format: Export format (ris, bibtex, csv)
        """
        from .tools._common import get_last_search_pmids

        if pmids.lower().strip() == "last":
            pmid_list = get_last_search_pmids()
            if not pmid_list:
                return ResponseFormatter.error(
                    "No previous search results",
                    suggestion="Run a search first, then use 'last'",
                    tool_name="export_citations",
                )
        else:
            pmid_list = InputNormalizer.normalize_pmids(pmids)

        if not pmid_list:
            return ResponseFormatter.error(
                "No valid PMIDs provided",
                suggestion="Use comma-separated PMIDs like '12345678,87654321'",
                tool_name="export_citations",
            )
        try:
            from pubmed_search.application.export.formats import (
                export_bibtex,
                export_csv,
                export_ris,
            )

            articles = await searcher.fetch_details(pmid_list[:50])
            if not articles:
                return "No articles found for the provided PMIDs"

            if format == "bibtex":
                content = export_bibtex(articles)
            elif format == "csv":
                content = export_csv(articles)
            else:
                content = export_ris(articles)
            return f"## Exported {len(articles)} citations ({format.upper()})\n\n```\n{content}\n```"
        except Exception as e:
            logger.exception(f"Export failed: {e}")
            return ResponseFormatter.error(e, tool_name="export_citations")

    # ========================================================================
    # Gene and Compound Research (share _ncbi_extended_search helper)
    # ========================================================================

    @mcp.tool()
    async def search_gene(query: str, organism: str = "human", limit: int = 10) -> str:
        """Search NCBI Gene database.

        Args:
            query: Gene name or symbol (e.g., "BRCA1", "p53")
            organism: Organism filter (default "human")
            limit: Maximum results (1-50, default 10)
        """
        return await _ncbi_extended_search(
            "search_gene",
            "search_gene",
            query,
            limit,
            50,
            "genes",
            organism=organism or "human",
        )

    @mcp.tool()
    async def search_compound(query: str, limit: int = 10) -> str:
        """Search PubChem for chemical compounds.

        Args:
            query: Compound name (e.g., "aspirin", "propofol")
            limit: Maximum results (1-50, default 10)
        """
        return await _ncbi_extended_search(
            "search_compound",
            "search_compound",
            query,
            limit,
            50,
            "compounds",
        )


COPILOT_TOOL_COUNT = 12
