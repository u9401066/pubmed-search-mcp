"""Protocol-level schema regressions for fulltext, annotations, and figures."""

from __future__ import annotations

import pytest
from mcp.client import Client

from pubmed_search.presentation.mcp_server import create_server


@pytest.mark.asyncio
async def test_article_tools_expose_required_discriminated_source_contracts():
    async with Client(create_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    expected_kinds = {
        "get_fulltext": {"pmid", "pmcid", "doi"},
        "get_text_mined_terms": {"pmid", "pmcid"},
        "get_article_figures": {"pmid", "pmcid"},
    }
    legacy_fields = {"identifier", "pmid", "pmcid", "doi"}

    for tool_name, kinds in expected_kinds.items():
        schema = tools[tool_name].input_schema
        properties = schema["properties"]
        source = properties["source"]

        assert schema["additionalProperties"] is False
        assert schema["required"] == ["source"]
        assert legacy_fields.isdisjoint(properties)
        assert source["discriminator"]["propertyName"] == "kind"
        assert set(source["discriminator"]["mapping"]) == kinds
        assert len(source["oneOf"]) == len(kinds)

        definitions = schema["$defs"]
        for definition in definitions.values():
            assert definition["additionalProperties"] is False
            assert definition["required"] == ["kind", "value"]
            assert definition["properties"]["value"]["type"] == "string"

    fulltext = tools["get_fulltext"].input_schema
    assert fulltext["$defs"]["PMIDSource"]["properties"]["value"] == {
        "maxLength": 20,
        "pattern": "^[1-9][0-9]{0,19}$",
        "title": "Value",
        "type": "string",
    }
    assert fulltext["$defs"]["PMCIDSource"]["properties"]["value"] == {
        "maxLength": 23,
        "pattern": "^PMC[1-9][0-9]{0,19}$",
        "title": "Value",
        "type": "string",
    }
    assert fulltext["$defs"]["DOISource"]["properties"]["value"]["maxLength"] == 512
    assert fulltext["$defs"]["DOISource"]["properties"]["value"]["pattern"] == (r"^10\.[0-9]{4,9}/")

    fulltext_properties = fulltext["properties"]
    sections = next(branch for branch in fulltext_properties["sections"]["anyOf"] if branch.get("type") == "string")
    assert sections["maxLength"] == 500
    assert fulltext_properties["output_format"]["enum"] == ["markdown", "json", "toon"]

    semantic_schema = tools["get_text_mined_terms"].input_schema["properties"]["semantic_type"]
    semantic_values = next(branch["enum"] for branch in semantic_schema["anyOf"] if "enum" in branch)
    assert set(semantic_values) == {
        "GENE_PROTEIN",
        "DISEASE",
        "CHEMICAL",
        "ORGANISM",
        "GO_TERM",
        "EFO",
    }
