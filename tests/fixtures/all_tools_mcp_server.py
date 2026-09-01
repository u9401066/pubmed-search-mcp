"""Deterministic MCP server fixture for the complete public tool surface.

Only external-provider boundaries are replaced. MCP registration, validation,
application services, persistence, artifacts, and scheduling remain real.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.domain.entities.figure import ArticleFigure, ArticleFiguresResult
from pubmed_search.infrastructure.sources import unified_broker
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.server import build_asgi_app
from pubmed_search.shared.source_contracts import SourceAdapterResult

PRIMARY_PMID = "12345678"
PIPELINE_PMID = "42424242"


def _require_fixture(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(f"Acceptance fixture contract mismatch: {message}")


def _article(pmid: str) -> dict[str, Any]:
    special: dict[str, dict[str, Any]] = {
        "111": {
            "title": "Root Paper",
            "year": "2024",
            "journal": "Nature",
            "authors": ["Smith J"],
        },
        "222": {
            "title": "Forward Citation Paper",
            "year": "2025",
            "journal": "Science",
            "authors": ["Jones A"],
        },
        "333": {
            "title": "Foundational Reference Paper",
            "year": "2018",
            "journal": "Cell",
            "authors": ["Lee K"],
        },
        "23456789": {
            "title": "Related Paper",
            "year": "2023",
            "journal": "Related Medicine",
            "authors": ["Related R"],
        },
        "34567890": {
            "title": "Citing Paper 2",
            "year": "2025",
            "journal": "Citation Medicine",
            "authors": ["Citing C"],
        },
        "45678901": {
            "title": "Reference Paper 2",
            "year": "2010",
            "journal": "Foundation Medicine",
            "authors": ["Reference R"],
        },
        PRIMARY_PMID: {
            "title": "Example title",
            "year": "2024",
            "journal": "New England Journal of Medicine",
            "journal_abbrev": "N Engl J Med",
            "authors": ["Smith John"],
            "authors_full": [{"last_name": "Smith", "fore_name": "John"}],
            "volume": "390",
            "issue": "1",
            "pages": "12-18",
            "doi": "10.1056/NEJMoa2400001",
        },
        PIPELINE_PMID: {
            "title": "Deterministic Acceptance Article",
            "year": "2026",
            "journal": "MCP Medicine",
            "authors": ["Ada Agent"],
            "doi": "10.1000/offline-acceptance",
        },
    }
    chronicle_rows = {
        "50000001": (
            "Foundational receptor mechanism",
            "1998",
            "Molecular Medicine",
            "Receptor signaling established the mechanistic foundation.",
            ["Mechanistic Pathways", "Receptors", "Signal Transduction"],
        ),
        "50000002": (
            "First randomized efficacy trial",
            "2005",
            "Clinical Trials",
            "A randomized controlled trial established clinical efficacy.",
            ["Mechanistic Pathways", "Randomized Controlled Trials", "Therapeutics"],
        ),
        "50000003": (
            'Multicenter "implementation" study\n%%{init: {"theme": "dark"}}%% \u202e ```',
            "2012",
            "Implementation Science",
            "A multicenter cohort translated the intervention into practice.",
            ["Implementation Science", "Cohort Studies"],
        ),
        "50000004": (
            "Predictive biomarker discovery",
            "2019",
            "Translational Biomarkers",
            "A biomarker study identified response-associated molecular markers.",
            ["Precision Therapeutics", "Biomarkers", "Genomics"],
        ),
        "50000005": (
            "Precision treatment update",
            "2025",
            "Precision Medicine",
            "A precision strategy updated treatment selection using biomarkers.",
            ["Precision Therapeutics", "Precision Medicine", "Treatment Selection"],
        ),
        "60000001": (
            "Comparator mechanism study",
            "2001",
            "Comparator Biology",
            "A comparator pathway was characterized.",
            ["Molecular Mechanisms"],
        ),
        "60000002": (
            "Comparator clinical trial",
            "2020",
            "Comparator Trials",
            "A comparator randomized trial reported clinical outcomes.",
            ["Randomized Controlled Trials"],
        ),
    }
    if pmid in chronicle_rows:
        title, year, journal, abstract, mesh_terms = chronicle_rows[pmid]
        special[pmid] = {
            "title": title,
            "year": year,
            "journal": journal,
            "authors": [f"Author {pmid[-2:]}"],
            "doi": f"10.1000/chronicle.{pmid}",
            "abstract": abstract,
            "mesh_terms": mesh_terms,
            "keywords": [term.lower() for term in mesh_terms],
            "publication_types": ["Journal Article"],
        }

    row = {
        "pmid": pmid,
        "title": f"Deterministic article {pmid}",
        "authors": ["Ada Agent"],
        "authors_full": [{"last_name": "Agent", "fore_name": "Ada"}],
        "journal": "MCP Medicine",
        "journal_abbrev": "MCP Med",
        "year": "2024",
        "month": "Jan",
        "day": "15",
        "volume": "1",
        "issue": "1",
        "pages": "1-10",
        "doi": f"10.1000/mcp.{pmid}",
        "pmc_id": "PMC7096777",
        "abstract": "Deterministic biomedical evidence for MCP acceptance testing.",
        "keywords": ["acceptance", "evidence"],
        "mesh_terms": ["Evidence-Based Medicine", "Research Design"],
        "publication_types": ["Journal Article"],
    }
    row.update(special.get(pmid, {}))
    return row


class DeterministicSearcher:
    """Provider double implementing the LiteratureSearcher capability surface."""

    def __init__(self) -> None:
        self._chronicle_calls = 0
        self._citation_metric_calls = 0

    async def search_page(self, query: str, limit: int = 5, **kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        _require_fixture(
            query in {"Offline Chronicle", "Offline Comparator", "offline pipeline"},
            f"unexpected literature query {query!r}",
        )
        _require_fixture(1 <= limit <= 100, f"unexpected literature limit {limit!r}")
        _require_fixture(
            set(kwargs) <= {"min_year", "max_year"},
            f"unexpected literature filters {sorted(kwargs)!r}",
        )
        if query == "Offline Chronicle":
            _require_fixture(limit == 15, f"Chronicle max_events was not forwarded exactly: {limit!r}")
            _require_fixture(not kwargs, f"Chronicle added unexpected filters: {kwargs!r}")
            self._chronicle_calls += 1
            count = 3 if self._chronicle_calls == 1 else 5
            pmids = [f"5000000{index}" for index in range(1, count + 1)]
        elif query == "Offline Comparator":
            _require_fixture(limit == 90, f"comparator default max_events was not forwarded: {limit!r}")
            _require_fixture(not kwargs, f"comparator added unexpected filters: {kwargs!r}")
            pmids = ["60000001", "60000002"]
        else:
            _require_fixture(limit == 1, f"pipeline limit was not forwarded exactly: {limit!r}")
            _require_fixture(not kwargs, f"pipeline added unexpected search filters: {kwargs!r}")
            pmids = [PIPELINE_PMID]
        items = [_article(pmid) for pmid in pmids[:limit]]
        return SourceSearchPage(
            source="pubmed",
            items=items,
            total=len(pmids),
            query=query,
            mode="relevance",
            metadata={
                "physical_query": query,
                "query_executed": True,
                "retrieval_mode": "deterministic_acceptance",
            },
        )

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        known_pmids = {PRIMARY_PMID, PIPELINE_PMID, "111"}
        _require_fixture(bool(pmids) and set(pmids) <= known_pmids, f"unexpected detail PMIDs {pmids!r}")
        return [_article(str(pmid)) for pmid in pmids]

    async def get_related_articles(self, pmid: str, limit: int) -> list[dict[str, Any]]:
        _require_fixture(pmid == PRIMARY_PMID, f"related PMID was not forwarded exactly: {pmid!r}")
        _require_fixture(limit == 1, f"related limit was not forwarded exactly: {limit!r}")
        return [_article("23456789")][:limit]

    async def get_citing_articles(self, pmid: str, limit: int) -> list[dict[str, Any]]:
        _require_fixture(pmid in {PRIMARY_PMID, "111"}, f"unexpected citing PMID {pmid!r}")
        if pmid == "111":
            _require_fixture(limit == 2, f"citation-tree citing limit was not forwarded: {limit!r}")
            return [_article("222")][:limit]
        _require_fixture(limit == 1, f"direct citing limit was not forwarded exactly: {limit!r}")
        return [_article("34567890")][:limit]

    async def get_article_references(self, pmid: str, limit: int) -> list[dict[str, Any]]:
        _require_fixture(pmid in {PRIMARY_PMID, "111"}, f"unexpected reference PMID {pmid!r}")
        if pmid == "111":
            _require_fixture(limit == 2, f"citation-tree reference limit was not forwarded: {limit!r}")
            return [_article("333")][:limit]
        _require_fixture(limit == 1, f"direct reference limit was not forwarded exactly: {limit!r}")
        return [_article("45678901")][:limit]

    async def get_citation_metrics(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        expected_batches = [
            [PRIMARY_PMID],
            ["50000001", "50000002", "50000003"],
            ["50000001", "50000002", "50000003", "50000004", "50000005"],
            ["60000001", "60000002"],
        ]
        _require_fixture(
            self._citation_metric_calls < len(expected_batches),
            f"unexpected extra citation-metrics call {pmids!r}",
        )
        expected = expected_batches[self._citation_metric_calls]
        self._citation_metric_calls += 1
        _require_fixture(pmids == expected, f"citation-metrics batch was not forwarded exactly: {pmids!r}")
        return {
            pmid: {
                "pmid": pmid,
                "title": _article(pmid)["title"],
                "year": int(_article(pmid)["year"]),
                "journal": _article(pmid)["journal"],
                "citation_count": 100,
                "relative_citation_ratio": 5.5,
                "nih_percentile": 95.0,
                "citations_per_year": 25.0,
                "apt": 0.8,
            }
            for pmid in pmids
        }

    async def verify_references(self, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _require_fixture(
            references
            == [
                {
                    "journal": "N Engl J Med",
                    "year": "2024",
                    "volume": "390",
                    "first_page": "12",
                    "author": "Smith",
                    "title": "Example title",
                }
            ],
            f"ECitMatch payload was not forwarded exactly: {references!r}",
        )
        return [{"verified": True, "pmid": PRIMARY_PMID} for _ in references]


class DeterministicStrategyGenerator:
    async def generate_strategies(self, **kwargs: Any) -> dict[str, Any]:
        expected = {
            "topic": "remimazolam",
            "strategy": "comprehensive",
            "use_mesh": True,
            "check_spelling": True,
            "include_suggestions": True,
            "analyze_queries": True,
        }
        _require_fixture(kwargs == expected, f"strategy arguments were not forwarded exactly: {kwargs!r}")
        topic = str(kwargs["topic"])
        return {
            "status": "success",
            "topic": topic,
            "corrected_topic": topic,
            "mesh_terms": [{"preferred": "Remimazolam"}],
            "all_synonyms": ["remimazolam", "CNS 7056"],
            "suggested_queries": [{"id": "q1", "query": "remimazolam[Title/Abstract]"}],
        }


class DeterministicEuropePMCClient:
    async def get_fulltext_xml(self, pmcid: str) -> str:
        _require_fixture(pmcid == "PMC7096777", f"unexpected fulltext PMCID {pmcid!r}")
        return "<article/>"

    def parse_fulltext_xml(self, xml: str) -> dict[str, Any]:
        _require_fixture(xml == "<article/>", "fulltext parser received unexpected XML")
        return {
            "title": "Offline Fulltext",
            "abstract": "Offline abstract",
            "sections": [{"title": "Introduction", "content": "Deterministic content."}],
            "references": [{"title": "Acceptance reference"}],
        }

    async def get_text_mined_terms(
        self,
        source: str,
        article_id: str,
        semantic_type: str | None,
    ) -> list[dict[str, Any]]:
        _require_fixture(source == "PMC", f"unexpected text-mining source {source!r}")
        _require_fixture(article_id == "7096777", f"unexpected text-mining ID {article_id!r}")
        _require_fixture(semantic_type == "GENE_PROTEIN", f"unexpected semantic type {semantic_type!r}")
        return [{"semantic_type": "GENE_PROTEIN", "term": "BRCA1", "count": 1}]


class DeterministicFigureClient:
    async def get_article_figures(self, **kwargs: Any) -> ArticleFiguresResult:
        _require_fixture(kwargs.get("pmcid") == "PMC12086443", f"unexpected figure source {kwargs!r}")
        _require_fixture(kwargs.get("include_subfigures") is False, "include_subfigures was not forwarded")
        _require_fixture(kwargs.get("include_tables") is False, "include_tables was not forwarded")
        return ArticleFiguresResult(
            pmcid=str(kwargs.get("pmcid") or "PMC12086443"),
            pmid=kwargs.get("pmid"),
            article_title="Offline Figures",
            total_figures=1,
            figures=[
                ArticleFigure(
                    figure_id="fig1",
                    label="Figure 1",
                    caption_text="Acceptance figure",
                    image_url="https://example.test/fig1.png",
                )
            ],
            pdf_links=[
                {
                    "source": "PubMed Central",
                    "url": "https://example.test/article.pdf",
                    "type": "pdf",
                }
            ],
            source="europepmc",
        )


class DeterministicNCBIExtendedClient:
    async def search_gene(self, **kwargs: Any) -> list[dict[str, str]]:
        _require_fixture(kwargs == {"query": "BRCA1", "organism": "human", "limit": 1}, "gene search args")
        return [{"gene_id": "672", "symbol": "BRCA1", "name": "BRCA1 DNA repair"}]

    async def get_gene(self, gene_id: str) -> dict[str, str]:
        _require_fixture(gene_id == "672", f"unexpected gene ID {gene_id!r}")
        return {"gene_id": gene_id, "symbol": "BRCA1", "name": "BRCA1 DNA repair"}

    async def get_gene_pubmed_links(self, gene_id: str, *, limit: int) -> list[str]:
        _require_fixture(gene_id == "672" and limit == 2, "gene-literature args")
        return [PRIMARY_PMID, "23456789"][:limit]

    async def search_compound(self, **kwargs: Any) -> list[dict[str, str]]:
        _require_fixture(kwargs == {"query": "aspirin", "limit": 1}, "compound search args")
        return [{"cid": "2244", "name": "Aspirin"}]

    async def get_compound(self, cid: str) -> dict[str, str]:
        _require_fixture(cid == "2244", f"unexpected compound CID {cid!r}")
        return {"cid": cid, "name": "Aspirin"}

    async def get_compound_pubmed_links(self, cid: str, *, limit: int) -> list[str]:
        _require_fixture(cid == "2244" and limit == 2, "compound-literature args")
        return [PRIMARY_PMID, "34567890"][:limit]

    async def search_clinvar(self, **kwargs: Any) -> list[dict[str, str]]:
        _require_fixture(kwargs == {"query": "BRCA1", "limit": 1}, "ClinVar search args")
        return [{"variant_id": "1", "gene": "BRCA1", "significance": "Pathogenic"}]


async def _deterministic_pubmed_search(
    searcher: Any,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    _require_fixture(isinstance(searcher, DeterministicSearcher), "unified searcher ownership")
    _require_fixture(query == "offline acceptance", f"unexpected unified query {query!r}")
    _require_fixture(limit == 1, f"unexpected unified limit {limit!r}")
    _require_fixture(min_year is None and max_year is None, "unexpected unified year bounds")
    _require_fixture(advanced_filters == {}, f"unexpected unified filters {advanced_filters!r}")
    article = UnifiedArticle(
        title="Deterministic Acceptance Article",
        primary_source="pubmed",
        pmid=PIPELINE_PMID,
        doi="10.1000/offline-acceptance",
        year=2026,
    )
    return SourceAdapterResult(
        source="pubmed",
        operation="search",
        items=[article],
        total_count=1,
        metadata={
            "total_available": 1,
            "physical_query": "offline acceptance",
            "query_executed": True,
        },
    )


async def _deterministic_openi_request(self: object, url: str) -> dict[str, Any]:
    _require_fixture(self.__class__.__name__ == "OpenIClient", "Open-i client instance missing")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    _require_fixture(parsed.scheme == "https", f"unexpected Open-i scheme {parsed.scheme!r}")
    _require_fixture(parsed.hostname == "openi.nlm.nih.gov", f"unexpected Open-i host {parsed.hostname!r}")
    _require_fixture(parsed.path == "/api/search", f"unexpected Open-i path {parsed.path!r}")
    _require_fixture(query.get("query") == ["chest pneumonia"], f"unexpected Open-i query {query!r}")
    _require_fixture(query.get("it") == ["x"], "Open-i image_type was not forwarded")
    _require_fixture(query.get("coll") == ["cxr"], "Open-i collection was not forwarded")
    _require_fixture(query.get("favor") == ["d"], "Open-i sort order was not forwarded")
    _require_fixture(query.get("m") == ["1"] and query.get("n") == ["2"], "Open-i page bounds")
    return {
        "total": 42,
        "list": [
            {
                "uid": "openi-001",
                "pmid": PRIMARY_PMID,
                "pmcid": "PMC1234567",
                "title": "Chest X-ray findings in pneumonia patients",
                "journal_title": "Radiology",
                "authors": "Smith J, Doe A",
                "imgLarge": "/imgs/large/12345.png",
                "imgThumb": "/imgs/thumb/12345.png",
                "image": {"caption": "Chest X-ray showing bilateral infiltrates"},
                "MeSH": {"major": ["Pneumonia", "Radiography, Thoracic"], "minor": []},
            },
            {
                "uid": "openi-002",
                "pmid": "87654321",
                "title": "Normal chest anatomy",
                "journal_title": "Journal of Anatomy",
                "authors": "Lee K",
                "imgLarge": "/imgs/large/67890.png",
                "imgThumb": "/imgs/thumb/67890.png",
                "image": {"caption": "Normal Chest X-ray"},
                "MeSH": {"major": ["Thorax"], "minor": []},
            },
        ],
    }


async def _deterministic_resolver_test(url: str, timeout: int = 10) -> dict[str, Any]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    _require_fixture(parsed.scheme == "https", f"unexpected resolver scheme {parsed.scheme!r}")
    _require_fixture(parsed.hostname == "resolver.ebscohost.com", f"unexpected resolver host {parsed.hostname!r}")
    _require_fixture(parsed.path == "/openurl", f"unexpected resolver path {parsed.path!r}")
    _require_fixture(query.get("pmid") == [PIPELINE_PMID], f"resolver lost the PMID: {query!r}")
    _require_fixture(
        query.get("rft_id") == [f"info:pmid/{PIPELINE_PMID}"],
        f"resolver lost the PMID identity: {query!r}",
    )
    _require_fixture(
        query.get("rft.atitle") == ["Test Article for OpenURL Verification"],
        f"resolver lost the article title: {query!r}",
    )
    _require_fixture(timeout == 10, f"unexpected resolver timeout {timeout!r}")
    return {"reachable": True, "status_code": 200, "error": None, "response_time_ms": 1}


async def _deterministic_access_diagnosis(**kwargs: Any) -> Any:
    from pubmed_search.infrastructure.sources.institutional_fetch import AccessDiagnosis, ProbeResult

    _require_fixture(kwargs.get("pmid") is None, f"unexpected diagnosis PMID {kwargs!r}")
    _require_fixture(kwargs.get("doi") == "10.1000/offline-acceptance", f"unexpected diagnosis DOI {kwargs!r}")
    _require_fixture(kwargs.get("try_direct") is True, "direct diagnosis flag was not forwarded")
    _require_fixture(kwargs.get("try_ezproxy") is False, "EZproxy diagnosis flag was not forwarded")

    return AccessDiagnosis(
        pmid=kwargs.get("pmid"),
        doi=kwargs.get("doi"),
        summary="Fulltext reachable via direct path.",
        probes=[
            ProbeResult(
                path="direct",
                attempted=True,
                success=True,
                final_url="https://publisher.example/article",
                status_code=200,
                content_class="fulltext_html",
                content_length=4096,
                duration_ms=1,
                advice="Publisher served deterministic fulltext.",
            )
        ],
        openurl="https://resolver.example/openurl",
        recommended_path="direct",
    )


def _install_deterministic_dependencies() -> None:
    import pubmed_search.container as container_module
    import pubmed_search.infrastructure.sources as source_package
    from pubmed_search.infrastructure.sources import figure_client, institutional_fetch
    from pubmed_search.infrastructure.sources.openi import OpenIClient
    from pubmed_search.presentation.mcp_server.tools import europe_pmc, openurl

    searcher = DeterministicSearcher()
    strategy_generator = DeterministicStrategyGenerator()
    europe_pmc_client = DeterministicEuropePMCClient()
    figure_provider = DeterministicFigureClient()
    extended_client = DeterministicNCBIExtendedClient()
    europe_pmc_module: Any = europe_pmc
    figure_client_module: Any = figure_client
    source_package_module: Any = source_package
    openi_client_type: Any = OpenIClient
    openurl_module: Any = openurl
    institutional_fetch_module: Any = institutional_fetch

    container_module._create_searcher = lambda email, api_key: searcher
    container_module._create_strategy_generator = lambda email, api_key: strategy_generator
    unified_broker._search_pubmed_adapter = _deterministic_pubmed_search
    europe_pmc_module.get_europe_pmc_client = lambda api_key=None: europe_pmc_client
    figure_client_module.get_figure_client = lambda: figure_provider
    source_package_module.get_ncbi_extended_client = lambda email=None, api_key=None: extended_client
    openi_client_type._make_request = _deterministic_openi_request
    openurl_module._test_resolver_url = _deterministic_resolver_test
    institutional_fetch_module.diagnose_access = _deterministic_access_diagnosis


def _is_local_address(host: object) -> bool:
    if host is None:
        return True
    value = host.decode() if isinstance(host, bytes) else str(host)
    if value.lower().rstrip(".") in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _block_external_network() -> None:
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def record_attempt(message: str) -> None:
        sentinel = os.environ.get("MCP_ACCEPTANCE_NETWORK_SENTINEL")
        if sentinel:
            path = Path(sentinel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(message, encoding="utf-8")

    def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_local_address(host):
            return original_getaddrinfo(host, port, *args, **kwargs)
        record_attempt(f"external DNS resolution: {host!r}")
        raise RuntimeError(f"Acceptance fixture attempted external DNS resolution for {host!r}")

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if not isinstance(address, tuple) or not address or _is_local_address(address[0]):
            return original_connect(sock, address)
        record_attempt(f"external socket connect: {address!r}")
        raise RuntimeError(f"Acceptance fixture attempted external socket connection to {address!r}")

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        if not isinstance(address, tuple) or not address or _is_local_address(address[0]):
            return original_connect_ex(sock, address)
        record_attempt(f"external socket connect_ex: {address!r}")
        raise RuntimeError(f"Acceptance fixture attempted external socket connection to {address!r}")

    socket_module: Any = socket
    socket_type: Any = socket.socket
    socket_module.getaddrinfo = guarded_getaddrinfo
    socket_type.connect = guarded_connect
    socket_type.connect_ex = guarded_connect_ex
    armed_marker = os.environ.get("MCP_ACCEPTANCE_NETWORK_GUARD_MARKER")
    if armed_marker:
        marker_path = Path(armed_marker)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("dns-connect-connect_ex-guard-armed", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = _parser().parse_args()
    _install_deterministic_dependencies()
    _block_external_network()

    data_dir = os.environ["PUBMED_DATA_DIR"]
    workspace_dir = os.environ.get("PUBMED_WORKSPACE_DIR") or data_dir
    server = create_server(
        email="offline-acceptance@example.com",
        data_dir=data_dir,
        workspace_dir=workspace_dir,
        mode="local",
    )
    if args.transport == "stdio":
        server.run()
        return

    import uvicorn

    app = build_asgi_app(server, "streamable-http", host=args.host)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
