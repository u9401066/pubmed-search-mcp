"""Offline workflow smoke with real provider HTTP, JSON/XML parsers and storage.

The loopback fixture serves synthetic provider-shaped responses. Only endpoint
addresses are redirected; no search, parser, cache or application result is mocked.
This is not evidence of availability or latency of a live literature provider.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest
from Bio import Entrez
from mcp.client import Client

from pubmed_search.infrastructure.sources import europe_pmc
from pubmed_search.presentation.mcp_server import create_server
from tests.fixtures.release_support import smoke_env
from tests.test_all_tools_mcp_acceptance import _json_document, _result_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

ARTICLE = {
    "id": "12345678",
    "source": "MED",
    "pmid": "12345678",
    "pmcid": "PMC7096777",
    "doi": "10.1000/smoke",
    "title": "Offline smoke: aspirin & stroke – β",
    "authorString": "Smith J",
    "journalTitle": "Smoke Journal",
    "pubYear": "2024",
    "isOpenAccess": "Y",
    "inEPMC": "Y",
    "inPMC": "Y",
    "hasPDF": "Y",
    "abstractText": "Synthetic abstract, not research evidence.",
}
XML = b"""<article><front><article-meta><title-group>
<article-title>Offline smoke: aspirin &amp; stroke &#x2013; &#x3b2;</article-title></title-group>
<abstract><p>Synthetic abstract, not research evidence.</p></abstract></article-meta></front>
<body><sec><title>Methods</title><p>Synthetic body with <italic>inline</italic> markup.</p></sec>
<sec><title>Results</title><p>A separate result section.</p></sec></body></article>"""

PUBMED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE PubmedArticleSet SYSTEM "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_190101.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM">
<PMID Version="1">12345678</PMID><Article PubModel="Print">
<Journal><ISSN IssnType="Print">1234-5678</ISSN><JournalIssue CitedMedium="Print">
<PubDate><Year>2024</Year></PubDate></JournalIssue><Title>Smoke Journal</Title></Journal>
<ArticleTitle>Offline smoke: aspirin &amp; stroke &#x2013; &#x3b2;</ArticleTitle>
<Abstract><AbstractText>Synthetic abstract, not research evidence.</AbstractText></Abstract>
<AuthorList><Author ValidYN="Y"><LastName>Smith</LastName><ForeName>John</ForeName><Initials>J</Initials></Author></AuthorList>
<Language>eng</Language><PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="pubmed">12345678</ArticleId><ArticleId IdType="doi">10.1000/smoke</ArticleId>
<ArticleId IdType="pmc">PMC7096777</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


@pytest.fixture
def provider_http(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {
        "requests": [],
        "status": 200,
        "search": {"hitCount": 1, "resultList": {"result": [ARTICLE]}},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, message: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            state["requests"].append((parsed.path, parse_qs(parsed.query)))
            if parsed.path == "/search":
                body, status, content_type = json.dumps(state["search"]).encode(), state["status"], "application/json"
            elif parsed.path == "/PMC7096777/fullTextXML":
                body, status, content_type = XML, 200, "application/xml"
            elif parsed.path == "/efetch.fcgi":
                body, status, content_type = PUBMED_XML, 200, "application/xml"
            else:
                body, status, content_type = b"unexpected request", 404, "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(europe_pmc, "EPMC_SEARCH_URL", f"{base_url}/search")
    monkeypatch.setattr(europe_pmc, "EPMC_API_BASE", base_url)
    build_request = Entrez._build_request

    def local_request(cgi, *args, **kwargs):
        # Redirect only the network address; preserve Biopython request encoding,
        # rate control, XML/DTD parsing and the production article parser.
        return build_request(f"{base_url}/{urlsplit(cgi).path.rsplit('/', 1)[-1]}", *args, **kwargs)

    monkeypatch.setattr(Entrez, "_build_request", local_request)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.fixture
def production_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in list(os.environ):
        if key.startswith(("PUBMED_", "NCBI_", "OPENURL_")) or key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)
    for key, value in smoke_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    return create_server(email="workflow-smoke@example.com", data_dir=str(tmp_path / "data"))


async def test_search_prefetch_read_export_and_session_over_real_provider_http(
    provider_http, production_server, tmp_path
):
    async with Client(production_server) as client:
        search = await client.call_tool(
            "unified_search",
            {
                "query": "aspirin stroke",
                "sources": "europe_pmc",
                "limit": "1",
                "output_format": "json",
                "options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
                "fulltext": "prefetch",
            },
        )
        assert not search.is_error, _result_text(search)
        payload = _json_document(_result_text(search))
        assert payload["articles"][0]["identifiers"]["pmid"] == ARTICLE["pmid"]
        assert payload["source_counts"][0]["returned"] == 1
        read = payload["enrichment"]["fulltext_prefetch"]["articles"][0]["read_request"]
        fulltext = await client.call_tool(read["tool"], read["arguments"])
        assert not fulltext.is_error, _result_text(fulltext)
        document = _json_document(_result_text(fulltext))
        assert document["fulltext_available"] is True
        assert document["title"] == ARTICLE["title"]
        assert document["content_sections"][0]["title"] == "Methods"
        assert "Synthetic body with inline markup." in document["content_sections"][0]["content"]
        assert "Synthetic abstract" not in document["content_sections"][0]["content"]
        repeated = await client.call_tool(read["tool"], {**read["arguments"], "sections": "Results"})
        assert "A separate result section." in _result_text(repeated)
        exported = await client.call_tool(
            "save_literature_notes",
            {
                "pmids": '["12345678"]',
                "output_dir": str(tmp_path / "notes"),
                "note_format": "wiki",
                "include_csl_json": True,
                "create_index": False,
            },
        )
        assert not exported.is_error, _result_text(exported)
        note = (tmp_path / "notes" / "12345678.md").read_text(encoding="utf-8")
        assert ARTICLE["title"] in note
        assert ARTICLE["abstractText"] in note
        citations = json.loads((tmp_path / "notes" / "references.csl.json").read_text(encoding="utf-8"))
        assert citations[0]["PMID"] == ARTICLE["pmid"]
        assert citations[0]["DOI"] == ARTICLE["doi"]
        cached = await client.call_tool("read_session", {"request": {"action": "article", "pmid": "12345678"}})
        assert not cached.is_error, _result_text(cached)
        assert ARTICLE["title"] in _result_text(cached)
    counts = Counter(path for path, _ in provider_http["requests"])
    assert counts == {"/search": 1, "/PMC7096777/fullTextXML": 1, "/efetch.fcgi": 1}, (
        "Prefetch/read/export duplicated upstream I/O"
    )
    params = provider_http["requests"][0][1]
    assert params["query"] == ["aspirin stroke"]
    assert params["pageSize"] == ["1"]


@pytest.mark.parametrize("failure", ["malformed", "unauthorized"])
async def test_provider_failure_is_not_reported_as_successful_empty_search(provider_http, production_server, failure):
    provider_http["search"] = {"error": "synthetic provider failure"}
    provider_http["status"] = 401 if failure == "unauthorized" else 200
    async with Client(production_server) as client:
        result = await client.call_tool(
            "unified_search",
            {
                "query": "aspirin",
                "sources": "europe_pmc",
                "limit": 1,
                "output_format": "json",
                "options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
            },
        )
        payload = _json_document(_result_text(result))
        assert payload["source_errors"], payload
        assert payload["articles"] == []
        assert payload["search_status"]["state"] == "failed"
        assert payload["search_status"]["failed_sources"] == ["europe_pmc"]
    assert len(provider_http["requests"]) == 1
