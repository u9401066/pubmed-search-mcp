"""Shared typed biomedical inputs for every MCP tool.

Value objects own identifier meaning. These annotations describe accepted
transport representations and validate them before application execution.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, PlainValidator, TypeAdapter, WithJsonSchema

from pubmed_search.domain.value_objects import (
    MAX_IDENTIFIER_CHARS,
    MAX_PMID_BATCH_CHARS,
    MAX_PMIDS_PER_REQUEST,
    IdentifierValidationError,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    normalize_pmid_batch,
)
from pubmed_search.domain.value_objects.ncbi_identifiers import normalize_ncbi_identifier
from pubmed_search.presentation.mcp_server.input_contract import (
    InputNormalizationError,
    decode_container,
    unwrap_json_fence,
)


def _identifier(value: Any, kind: Literal["pmid", "pmcid", "doi", "ncbi"]) -> str:
    if not isinstance(value, str) or len(value) > MAX_IDENTIFIER_CHARS:
        raise ValueError("Identifiers require a bounded string")
    if kind != "ncbi":
        value = value.strip()
        if value.startswith("`") and value.endswith("`") and value.count("`") == 2:
            value = value[1:-1]
    parsers = {
        "pmid": normalize_pmid,
        "pmcid": normalize_pmcid,
        "doi": normalize_doi,
        "ncbi": normalize_ncbi_identifier,
    }
    return parsers[kind](value)


def _identifier_schema(kind: str, examples: list[str]) -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": MAX_IDENTIFIER_CHARS,
        "format": f"pubmed-{kind}",
        "x-pubmed-input": kind,
        "examples": examples,
        "description": "Complete identifier string; optional identifier prefix, official article URL, or inline backticks. "
        "No numbers, foreign hosts, URL queries/fragments or partial identifiers.",
    }


PMIDText = Annotated[
    str,
    BeforeValidator(lambda value: _identifier(value, "pmid")),
    WithJsonSchema(
        _identifier_schema("pmid", ["33053718", "PMID:33053718", "https://pubmed.ncbi.nlm.nih.gov/33053718/"])
    ),
]
PMCIDText = Annotated[
    str,
    BeforeValidator(lambda value: _identifier(value, "pmcid")),
    WithJsonSchema(_identifier_schema("pmcid", ["PMC12345", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"])),
]
DOIText = Annotated[
    str,
    BeforeValidator(lambda value: _identifier(value, "doi")),
    WithJsonSchema(
        _identifier_schema("doi", ["10.1000/example", "doi:10.1000/example", "https://doi.org/10.1000/example"])
    ),
]
NcbiIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=20, pattern=r"^[1-9][0-9]{0,19}$"),
    BeforeValidator(lambda value: _identifier(value, "ncbi")),
]


def _batch_item(value: Any) -> str:
    if isinstance(value, str) and value.strip().casefold() == "last":
        return "last"
    return _identifier(value, "pmid")


PMIDBatchItem = Annotated[
    str,
    BeforeValidator(_batch_item),
    WithJsonSchema(
        {
            **_identifier_schema("pmid", ["33053718"]),
            "description": "One PMID string, or last as the sole batch item for tools supporting session reuse.",
        }
    ),
]
PMIDBatchText = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=MAX_PMID_BATCH_CHARS,
        description="Complete PMID(s): delimited text, JSON string array, or Markdown list; optional JSON code fence. last only where supported.",
        json_schema_extra={
            "format": "pubmed-pmid-batch",
            "examples": ["33053718,36170657", '["33053718","36170657"]', "- 33053718\n- 36170657"],
        },
    ),
]
PMIDList = Annotated[list[PMIDBatchItem], Field(min_length=1, max_length=MAX_PMIDS_PER_REQUEST)]
ExplicitPMIDList = Annotated[list[PMIDText], Field(min_length=1, max_length=MAX_PMIDS_PER_REQUEST)]
_PMID_LIST_ADAPTER = TypeAdapter(PMIDList)
_MARKDOWN_ITEM = re.compile(r"(?:[-*+][ \t]+|[1-9][0-9]*[.)][ \t]+)(.+)")


def _split_pmids(value: object) -> object:
    if not isinstance(value, str):
        return value
    if len(value) > MAX_PMID_BATCH_CHARS:
        raise InputNormalizationError("PMID batch exceeds the input size limit", code="input_too_large")
    value = decode_container(value, max_chars=MAX_PMID_BATCH_CHARS)
    if not isinstance(value, str):
        return value
    text = unwrap_json_fence(value).strip()
    if not text:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    if any(_MARKDOWN_ITEM.fullmatch(line.strip()) for line in lines):
        matches = [_MARKDOWN_ITEM.fullmatch(line.strip()) for line in lines]
        if not all(matches):
            raise IdentifierValidationError("Every Markdown line must contain exactly one PMID list item")
        return [match.group(1) for match in matches if match is not None]
    # A URL denotes one identifier, or one identifier per line. Delimiters in
    # arbitrary URLs must not be reinterpreted as evidence identifiers.
    if "://" in text:
        return re.split(r"[,;|，；、\n]\s*", text)
    if text.casefold() == "last":
        return [text]
    # The domain parser validates the complete delimiter grammar. Preserve
    # per-item locations for ordinary comma/newline lists, including invalid
    # entries, instead of dropping or repairing them.
    try:
        return normalize_pmid_batch(text, allow_last=False)
    except IdentifierValidationError:
        if re.search(r"[,;|，；、\n]", text):
            return re.split(r"[,;|，；、\n]\s*", text)
        return [text]


def _validate_batch(value: object) -> list[str]:
    items = _PMID_LIST_ADAPTER.validate_python(_split_pmids(value), strict=True)
    if "last" in items and len(items) != 1:
        raise IdentifierValidationError("last cannot be combined with explicit PMIDs")
    return list(dict.fromkeys(items))


def _validate_explicit_batch(value: object) -> list[str]:
    result = _validate_batch(value)
    if "last" in result:
        raise IdentifierValidationError("This tool requires explicit PMIDs")
    return result


PMIDBatchInput = Annotated[
    str | list[str],
    PlainValidator(_validate_batch, json_schema_input_type=PMIDBatchText | PMIDList),
    Field(json_schema_extra={"x-pubmed-input": "pmid_batch"}),
]
ExplicitPMIDBatchInput = Annotated[
    str | list[str],
    PlainValidator(_validate_explicit_batch, json_schema_input_type=PMIDBatchText | ExplicitPMIDList),
    Field(json_schema_extra={"x-pubmed-input": "pmid_batch", "description": "Explicit PMIDs; last is not supported."}),
]


class InputNormalizer:
    """Compatibility helpers for direct Python calls and canonical wrappers."""

    @staticmethod
    def normalize_pmids(value: object, *, allow_last: bool = True) -> list[str]:
        from pydantic import ValidationError

        if not isinstance(value, (str, list)):
            raise IdentifierValidationError("pmids must be PMID text or a string array")
        try:
            result = _validate_batch(value)
        except ValidationError as exc:
            if any(issue["type"] == "too_long" for issue in exc.errors()):
                raise IdentifierValidationError(f"PMID batch exceeds {MAX_PMIDS_PER_REQUEST} values") from None
            raise IdentifierValidationError(
                "Provide complete PMID strings using positive ASCII digits or official URLs"
            ) from None
        except InputNormalizationError as exc:
            raise IdentifierValidationError(str(exc)) from None
        if not allow_last and "last" in result:
            raise IdentifierValidationError("last is not a PMID")
        return result

    @staticmethod
    def normalize_pmid_single(value: str | None) -> str | None:
        """Return one canonical PMID without accepting alternate input types."""
        if not isinstance(value, str):
            return None
        try:
            return _identifier(value, "pmid")
        except ValueError:
            return None

    @staticmethod
    def normalize_query(query: str) -> str:
        """Normalize typography and surrounding whitespace in free-form text."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")

        query = query.strip()
        return query.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")

    @staticmethod
    def normalize_doi(value: str | None) -> str | None:
        """Return a canonical DOI, including canonical DOI URL/prefix parsing."""
        if not isinstance(value, str):
            return None
        try:
            return _identifier(value, "doi")
        except ValueError:
            return None


__all__ = [
    "DOIText",
    "ExplicitPMIDBatchInput",
    "InputNormalizer",
    "NcbiIdentifier",
    "PMCIDText",
    "PMIDBatchInput",
    "PMIDText",
]
