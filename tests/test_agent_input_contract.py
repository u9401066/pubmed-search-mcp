"""Agent contract: automatic repair first, precise one-retry errors second."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Literal

import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError

from pubmed_search.domain.value_objects import IdentifierValidationError, normalize_pmid, parse_article_identifier
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.input_contract import InvalidToolArgumentsError
from pubmed_search.presentation.mcp_server.session_tools import SessionReadRequest  # noqa: TC001 - runtime MCP schema
from pubmed_search.presentation.mcp_server.tool_contracts import PubMedMCPServer
from pubmed_search.presentation.mcp_server.tools.article_source import ArticleSource  # noqa: TC001 - runtime MCP schema
from pubmed_search.presentation.mcp_server.tools.tool_input import DOIText, PMCIDText, PMIDBatchInput, PMIDText


def _reject_private_context(value):
    raise ValueError("secret-context")


PrivateValidatedText = Annotated[str, BeforeValidator(_reject_private_context)]


@pytest.mark.parametrize(
    ("annotation", "value", "expected"),
    [
        (PMIDText, " PMID: 33053718 ", "33053718"),
        (PMIDText, "`33053718`", "33053718"),
        (PMIDText, "https://pubmed.ncbi.nlm.nih.gov/33053718/", "33053718"),
        (PMCIDText, "pmcid: pmc12345", "PMC12345"),
        (PMCIDText, "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/", "PMC12345"),
        (PMCIDText, "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/", "PMC12345"),
        (DOIText, "`https://doi.org/10.1000/EXAMPLE`", "10.1000/example"),
        (PMIDBatchInput, "- `33053718`\n- PMID:36170657", ["33053718", "36170657"]),
        (PMIDBatchInput, "1. 33053718\n2) 36170657", ["33053718", "36170657"]),
        (PMIDBatchInput, '```json\n["33053718", "36170657"]\n```', ["33053718", "36170657"]),
        (PMIDBatchInput, "https://pubmed.ncbi.nlm.nih.gov/33053718/, PMID:36170657", ["33053718", "36170657"]),
    ],
)
def test_shared_identifier_formats_match_their_published_schema(annotation, value, expected):
    adapter = TypeAdapter(annotation)
    Draft202012Validator(adapter.json_schema()).validate(value)
    assert adapter.validate_python(value, strict=True) == expected


@pytest.mark.parametrize(
    "value",
    [
        "123PMID:456",
        "PMID:PMID:123",
        "０１２３",
        "0123",
        "1e3",
        123,
        True,
        "https://evil.example/123",
        "https://pubmed.ncbi.nlm.nih.gov.evil.example/123/",
        "https://pubmed.ncbi.nlm.nih.gov@evil.example/123/",
        "https://user:password@pubmed.ncbi.nlm.nih.gov/123/",
        "https://pubmed.ncbi.nlm.nih.gov:443/123/",
        "https://pubmed.ncbi.nlm.nih.gov/123/?",
        "https://pubmed.ncbi.nlm.nih.gov/123/#",
        "https://pubmed.ncbi.nlm.nih.gov/?term=123",
        "https://pubmed.ncbi.nlm.nih.gov/%31%32%33/",
        "https://pubmed.ncbi.nlm.nih.gov/123/456/",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
        "`123` extra",
    ],
)
def test_identifiers_never_extract_digits_or_fetch_arbitrary_urls(value):
    with pytest.raises(ValidationError):
        TypeAdapter(PMIDText).validate_python(value, strict=True)


def test_domain_identifier_prefix_only_matches_the_start():
    with pytest.raises(IdentifierValidationError):
        normalize_pmid("123PMID:456")
    assert parse_article_identifier("https://pubmed.ncbi.nlm.nih.gov/123/").kind == "pmid"
    assert parse_article_identifier("https://pmc.ncbi.nlm.nih.gov/articles/PMC123/").kind == "pmcid"


@pytest.fixture
def echo_server(tmp_path):
    server = PubMedMCPServer("input-contract")
    executions = []

    @server.tool(name="fetch_article_details")
    async def echo(
        pmids: PMIDBatchInput,
        source: ArticleSource | None = None,
        request: SessionReadRequest | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        score: Annotated[float, Field(ge=0, le=100)] = 1.0,
        enabled: bool = True,
        output_format: Literal["json", "markdown"] = "json",
    ) -> str:
        result = {
            "pmids": pmids,
            "source": source.model_dump() if source else None,
            "request": request.model_dump() if request else None,
            "limit": limit,
            "score": score,
            "enabled": enabled,
            "output_format": output_format,
        }
        executions.append(result)
        (tmp_path / "executed.json").write_text(json.dumps(result))
        await asyncio.sleep(0)
        return json.dumps(result)

    return server, executions


@pytest.mark.asyncio
async def test_one_call_automatically_corrects_all_unambiguous_representations(echo_server):
    server, executions = echo_server
    arguments = {
        "pmids": "- `33053718`\n- PMID:36170657\n- 33053718",
        "source": '```json\n{"kind":" PMID ","value":"https://pubmed.ncbi.nlm.nih.gov/33053718/"}\n```',
        "request": '{"action":" SUMMARY ","include_history":" FALSE ","history_limit":" 2 "}',
        "limit": " 12 ",
        "score": " 1.25 ",
        "enabled": " False ",
        "output_format": " JSON ",
    }
    async with Client(server) as client:
        schema = (await client.list_tools()).tools[0].input_schema
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(arguments)
        result = await client.call_tool("fetch_article_details", arguments)
    assert not result.is_error
    assert len(executions) == 1
    payload = json.loads(result.content[0].text)
    assert payload == {
        "pmids": ["33053718", "36170657"],
        "source": {"kind": "pmid", "value": "33053718"},
        "request": {"action": "summary", "include_history": False, "history_limit": 2},
        "limit": 12,
        "score": 1.25,
        "enabled": False,
        "output_format": "json",
    }
    rules = {event["rule"] for event in result.meta["pubmed-search"]["normalizations"]}
    assert {
        "identifier_batch",
        "json_container",
        "decimal_integer",
        "decimal_number",
        "boolean_literal",
        "enum_spelling",
    } <= rules


@pytest.mark.asyncio
async def test_all_bad_fields_are_reported_and_one_corrected_retry_succeeds(echo_server, tmp_path, caplog):
    server, executions = echo_server
    args = {
        "pmids": ["33053718", "secret-value"],
        "limit": "101",
        "enabled": "yes",
        "source": {"kind": "pmid", "value": "secret-id"},
        "output_format": "xml",
    }
    async with Client(server) as client:
        rejected = await client.call_tool("fetch_article_details", args)
        assert rejected.is_error
        assert not executions
        assert not (tmp_path / "executed.json").exists()
        failure = rejected.structured_content
        assert failure["status"] == "invalid_input"
        assert failure["executed"] is False
        assert failure["error_count"] == 5
        assert {item["path"] for item in failure["errors"]} == {
            "/pmids/1",
            "/limit",
            "/enabled",
            "/source/value",
            "/output_format",
        }
        assert "secret-" not in json.dumps(failure) + rejected.content[0].text + caplog.text
        repairs = {
            "/pmids/1": "36170657",
            "/limit": 100,
            "/enabled": False,
            "/source/value": "33053718",
            "/output_format": "json",
        }
        for issue in failure["errors"]:
            assert issue["expected"]
            parts = issue["path"].split("/")[1:]
            target = args
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            key = int(parts[-1]) if isinstance(target, list) else parts[-1]
            target[key] = repairs[issue["path"]]
        accepted = await client.call_tool("fetch_article_details", args)
        assert not accepted.is_error
        assert len(executions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "path"),
    [
        ("limit", True, "/limit"),
        ("limit", 1.5, "/limit"),
        ("limit", "1e1", "/limit"),
        ("limit", "１", "/limit"),
        ("enabled", 1, "/enabled"),
        ("enabled", "0", "/enabled"),
        ("score", "NaN", "/score"),
        ("pmids", ["33053718", None], "/pmids/1"),
        ("pmids", "- 33053718\nprose 36170657", "/pmids"),
        ("source", '{"kind":"pmid","kind":"doi","value":"123"}', "/source"),
        ("request", {"action": "secret-tag"}, "/request/action"),
        ("request", {"action": "article"}, "/request/pmid"),
        ("request", {"action": "summary", "secret-key": "secret-value"}, "/request"),
        ("request", {"action": "artifact", "locator": {"kind": "artifact_id", "value": []}}, "/request/locator/value"),
    ],
)
async def test_ambiguous_or_invalid_values_fail_before_execution(echo_server, field, value, path):
    server, executions = echo_server
    async with Client(server) as client:
        result = await client.call_tool("fetch_article_details", {"pmids": ["33053718"], field: value})
    assert result.is_error
    assert not executions
    assert result.structured_content["errors"][0]["path"] == path
    assert "secret-" not in json.dumps(result.structured_content)


@pytest.mark.asyncio
async def test_execution_validation_error_does_not_claim_no_execution():
    server = PubMedMCPServer("execution-error")

    @server.tool(name="analyze_search_query")
    def fail_inside_tool(query: str) -> str:
        TypeAdapter(int).validate_python("secret-value", strict=True)
        return query

    async with Client(server) as client:
        result = await client.call_tool("analyze_search_query", {"query": "cancer"})
    assert result.is_error
    assert result.structured_content is None
    assert "secret-value" not in result.content[0].text


@pytest.mark.asyncio
async def test_normalization_metadata_is_isolated_between_concurrent_requests(echo_server):
    server, _ = echo_server
    async with Client(server) as client:
        corrected, canonical = await asyncio.gather(
            client.call_tool("fetch_article_details", {"pmids": ["33053718"], "limit": " 5 "}),
            client.call_tool("fetch_article_details", {"pmids": ["36170657"], "limit": 6}),
        )
    assert corrected.meta["pubmed-search"]["normalizations"] == [{"path": "/limit", "rule": "decimal_integer"}]
    assert "pubmed-search" not in (canonical.meta or {})


@pytest.mark.asyncio
async def test_malformed_containers_do_not_hide_other_repairable_fields(echo_server):
    server, executions = echo_server
    async with Client(server) as client:
        result = await client.call_tool(
            "fetch_article_details",
            {
                "pmids": ["bad"],
                "source": '{"kind":',
                "request": '{"action":',
                "limit": 101,
            },
        )
    assert not executions
    errors = result.structured_content["errors"]
    assert {item["path"] for item in errors} == {"/pmids/0", "/source", "/request", "/limit"}
    assert {item["code"] for item in errors if item["path"] in {"/source", "/request"}} == {"invalid_json"}


@pytest.mark.asyncio
async def test_error_details_are_bounded_without_losing_total_count(echo_server):
    server, executions = echo_server
    async with Client(server) as client:
        result = await client.call_tool("fetch_article_details", {"pmids": ["secret-value"] * 25})
    assert not executions
    assert result.structured_content["error_count"] == 25
    assert len(result.structured_content["errors"]) == 20
    assert result.structured_content["truncated"] is True
    assert "secret-value" not in result.content[0].text


@pytest.mark.asyncio
async def test_false_text_does_not_enable_a_write_option(tmp_path):
    server = PubMedMCPServer("write-flag")
    path = tmp_path / "existing.txt"
    path.write_text("original")

    @server.tool(name="save_literature_notes")
    def write_note(overwrite: bool = False) -> str:
        if overwrite:
            path.write_text("replaced")
        return "ok"

    async with Client(server) as client:
        result = await client.call_tool("save_literature_notes", {"overwrite": " FALSE "})
    assert not result.is_error
    assert path.read_text() == "original"


def test_size_depth_and_free_text_union_contracts():
    from pubmed_search.presentation.mcp_server.input_contract import (
        InputNormalizationError,
        accepted_input_schema,
        normalize_tool_arguments,
    )

    ambiguous = {"type": "object", "properties": {"value": {"anyOf": [{"type": "string"}, {"type": "array"}]}}}
    raw = {"value": '["123"]'}
    assert normalize_tool_arguments(raw, ambiguous) == raw
    Draft202012Validator(accepted_input_schema(ambiguous)).validate(raw)
    node = {"type": "integer"}
    value = 1
    for _ in range(35):
        node = {"type": "object", "properties": {"child": node}}
        value = {"child": value}
    with pytest.raises(InputNormalizationError, match="maximum nesting depth"):
        normalize_tool_arguments(value, node)


@pytest.mark.parametrize("value", [["123"] * 1001, ",".join(["123"] * 1001)])
def test_batch_size_limit_precedes_deduplication_in_typed_contract(value):
    with pytest.raises(ValidationError):
        TypeAdapter(PMIDBatchInput).validate_python(value)


def test_every_actual_pmid_field_reuses_the_same_validator():
    server = create_server()
    cases = {
        "find_related_articles": {"pmid": "PMID:33053718"},
        "find_citing_articles": {"pmid": "PMID:33053718"},
        "get_article_references": {"pmid": "PMID:33053718"},
        "build_citation_tree": {"pmid": "PMID:33053718"},
        "test_institutional_access": {"pmid": "PMID:33053718"},
        "read_session": {"request": {"action": "article", "pmid": "PMID:33053718"}},
        "get_fulltext": {"source": {"kind": "pmid", "value": "PMID:33053718"}},
        "get_article_figures": {"source": {"kind": "pmid", "value": "PMID:33053718"}},
        "get_text_mined_terms": {"source": {"kind": "pmid", "value": "PMID:33053718"}},
        "get_institutional_link": {"source": {"kind": "pmid", "value": "PMID:33053718"}},
        "diagnose_institutional_access": {"source": {"kind": "pmid", "value": "PMID:33053718"}},
    }
    for name, arguments in cases.items():
        tool = server._tool_manager.get_tool(name)
        Draft202012Validator(tool.parameters).validate(arguments)
        validated = tool.fn_metadata.validate_arguments(arguments)
        if "pmid" in validated:
            assert validated["pmid"] == "33053718"
        elif "source" in validated:
            assert validated["source"].value == "33053718"
        else:
            assert validated["request"].pmid == "33053718"
        invalid = json.loads(json.dumps(arguments).replace("PMID:33053718", "123PMID:456"))
        with pytest.raises(InvalidToolArgumentsError):
            tool.fn_metadata.validate_arguments(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "code"),
    [
        ('["123",]', "invalid_json"),
        ('{"secret-key":1,"secret-key":2}', "duplicate_key"),
        ('["123", NaN]', "invalid_json"),
        ('["123"]' + " " * 100_000, "input_too_large"),
    ],
)
async def test_batch_transport_errors_keep_their_precise_code(echo_server, value, code):
    server, executions = echo_server
    async with Client(server) as client:
        rejected = await client.call_tool("fetch_article_details", {"pmids": value})
        assert not executions
        issue = rejected.structured_content["errors"][0]
        assert issue["path"] == "/pmids"
        assert issue["code"] == code
        assert "secret-key" not in json.dumps(rejected.structured_content)
        repaired = await client.call_tool("fetch_article_details", {"pmids": '["123"]'})
        assert not repaired.is_error
        assert len(executions) == 1


@pytest.mark.asyncio
async def test_union_normalization_matches_schema_without_rewriting_free_text():
    server = PubMedMCPServer("union-contract")

    @server.tool(name="analyze_search_query")
    def echo(query: Literal["json"] | str, limit: int | float) -> str:  # noqa: PYI051, PYI041 - exercise schema unions
        return json.dumps({"query": query, "limit": limit})

    async with Client(server) as client:
        schema = (await client.list_tools()).tools[0].input_schema
        for number, expected in [(" 1.5 ", 1.5), (" 2 ", 2)]:
            arguments = {"query": " JSON ", "limit": number}
            Draft202012Validator(schema).validate(arguments)
            result = await client.call_tool("analyze_search_query", arguments)
            assert not result.is_error
            assert json.loads(result.content[0].text) == {"query": " JSON ", "limit": expected}

    bounded = PubMedMCPServer("bounded-text-union")

    @bounded.tool(name="analyze_search_query")
    def bounded_echo(query: Literal["json"] | Annotated[str, Field(max_length=5)]) -> str:
        return query

    async with Client(bounded) as client:
        schema = (await client.list_tools()).tools[0].input_schema
        assert not Draft202012Validator(schema).is_valid({"query": " JSON "})
        assert (await client.call_tool("analyze_search_query", {"query": " JSON "})).is_error


@pytest.mark.asyncio
async def test_third_party_validation_context_is_not_exposed():
    server = PubMedMCPServer("private-validation-context")

    @server.tool(name="analyze_search_query")
    def echo(query: PrivateValidatedText) -> str:
        return query

    async with Client(server) as client:
        rejected = await client.call_tool("analyze_search_query", {"query": "secret-input"})
    assert rejected.is_error
    assert "secret-" not in rejected.content[0].text + json.dumps(rejected.structured_content)
