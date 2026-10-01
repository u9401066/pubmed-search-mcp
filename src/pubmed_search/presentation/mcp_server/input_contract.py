"""Shared MCP transport schemas, normalization and safe validation errors.

This boundary only handles representations. Domain meaning stays in value
objects; application services never need to understand encoded MCP arguments.
"""

from __future__ import annotations

import copy
import json
import math
import re
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import ValidationError

MAX_ENCODED_CONTAINER_CHARS = 1_000_000
MAX_INPUT_DEPTH = 32
MAX_ERROR_DETAILS = 20
INTEGER_TEXT_PATTERN = r"^[ \t\r\n]*-?(?:0|[1-9][0-9]*)[ \t\r\n]*$"
MAX_INTEGER_TEXT_CHARS = 32
NUMBER_TEXT_PATTERN = r"^[ \t\r\n]*-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[ \t\r\n]*$"
MAX_NUMBER_TEXT_CHARS = 64
_ASCII_WHITESPACE = " \t\r\n"
normalization_events: ContextVar[list[dict[str, str]] | None] = ContextVar("input_normalizations", default=None)


def pointer(path: tuple[str | int, ...]) -> str:
    """RFC 6901 pointer, using only declared field names and array indexes."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)


def record_normalization(path: tuple[str | int, ...], rule: str) -> None:
    events = normalization_events.get()
    event = {"path": pointer(path), "rule": rule}
    if events is not None and event not in events and len(events) < MAX_ERROR_DETAILS:
        events.append(event)


class InputNormalizationError(ValueError):
    """A safe, static message with a schema-owned location."""

    def __init__(self, message: str, *, code: str = "invalid_json", path: tuple[str | int, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class InvalidToolArgumentsError(ValueError):
    """Raised exclusively by argument validation, before the tool can run."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("Invalid tool arguments")
        self.errors = errors


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputNormalizationError("JSON objects must not contain duplicate keys", code="duplicate_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> Any:
    raise InputNormalizationError("JSON must not contain NaN or Infinity")


def decode_container(value: str, *, max_chars: int = MAX_ENCODED_CONTAINER_CHARS) -> Any:
    """Decode at most one JSON layer; never interpret Python/YAML literals."""
    if len(value) > max_chars:
        raise InputNormalizationError("Encoded JSON container exceeds the input size limit", code="input_too_large")
    value = unwrap_json_fence(value)
    if not value.lstrip().startswith(("[", "{")):
        return value
    try:
        return json.loads(value, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, InputNormalizationError):
            raise
        raise InputNormalizationError("Expected a valid JSON array or object with double-quoted strings") from None


def unwrap_json_fence(value: str) -> str:
    match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*)\r?\n```\s*", value, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else value


def _choice_pattern(choices: list[str]) -> str:
    def spelling(choice: str) -> str:
        return "".join(
            f"[{char.lower()}{char.upper()}]" if char.isascii() and char.isalpha() else re.escape(char)
            for char in choice
        )

    return r"^[ \t\r\n]*(?:" + "|".join(spelling(choice) for choice in choices) + r")[ \t\r\n]*$"


def _normalize_choice(value: Any, choices: list[Any]) -> Any:
    if not isinstance(value, str):
        return value
    matches = [
        choice for choice in choices if isinstance(choice, str) and re.fullmatch(_choice_pattern([choice]), value)
    ]
    return matches[0] if len(matches) == 1 else value


def schema_branches(schema: dict[str, Any], root: dict[str, Any]) -> list[dict[str, Any]]:
    if "$ref" in schema:
        schema = root.get("$defs", {}).get(schema["$ref"].removeprefix("#/$defs/"), {})
    branches = schema.get("anyOf", schema.get("oneOf"))
    if branches:
        return [resolved for branch in branches for resolved in schema_branches(branch, root)]
    return [schema]


def _input_kind(schema: dict[str, Any]) -> str | None:
    if "x-pubmed-input" in schema:
        return str(schema["x-pubmed-input"])
    kinds = {_input_kind(branch) for branch in schema.get("anyOf", [])} - {None}
    return kinds.pop() if len(kinds) == 1 else None


def _object_branch(branches: list[dict[str, Any]], value: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        branch
        for branch in branches
        if branch.get("type") == "object"
        and all(
            value.get(name) == prop["const"] for name, prop in branch.get("properties", {}).items() if "const" in prop
        )
    ]
    return candidates[0] if len(candidates) == 1 else {}


def _normalize_value(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: tuple[str | int, ...],
    depth: int,
    failures: list[InputNormalizationError] | None = None,
) -> Any:
    def child(item: Any, field: dict[str, Any], key: str | int) -> Any:
        try:
            return _normalize_value(item, field, root, (*path, key), depth + 1, failures)
        except InputNormalizationError as exc:
            if failures is None:
                raise
            failures.append(exc)
            return item

    if depth > MAX_INPUT_DEPTH:
        raise InputNormalizationError(
            "Tool arguments exceed the maximum nesting depth", code="input_too_deep", path=path
        )
    # Shared field validators own identifier/batch formats, including JSON
    # arrays. Do not partially normalize them using a generic container rule.
    if schema.get("x-pubmed-input"):
        return value
    branches = schema_branches(schema, root)
    types = {branch.get("type") for branch in branches}
    choices = [
        choice for branch in branches for choice in branch.get("enum", [branch["const"]] if "const" in branch else [])
    ]
    # A free-text alternative already accepts the literal input. Do not alter
    # its meaning just because another branch happens to be an enum.
    accepts_text = any(branch.get("type") == "string" and not {"enum", "const"} & branch.keys() for branch in branches)
    corrected = value if accepts_text else _normalize_choice(value, choices)
    if corrected != value:
        record_normalization(path, "enum_spelling")
        value = corrected
    if isinstance(value, str) and types & {"array", "object"} and "string" not in types:
        try:
            decoded = decode_container(value)
        except InputNormalizationError as exc:
            raise InputNormalizationError(str(exc), code=exc.code, path=path) from None
        if isinstance(decoded, (list, dict)):
            value = decoded
            record_normalization(path, "json_container")
    if (
        isinstance(value, str)
        and "integer" in types
        and "string" not in types
        and len(value) <= MAX_INTEGER_TEXT_CHARS
        and re.fullmatch(INTEGER_TEXT_PATTERN, value)
    ):
        value = int(value)
        record_normalization(path, "decimal_integer")
    if (
        isinstance(value, str)
        and "boolean" in types
        and "string" not in types
        and re.fullmatch(_choice_pattern(["true", "false"]), value)
    ):
        value = value.strip(_ASCII_WHITESPACE).lower() == "true"
        record_normalization(path, "boolean_literal")
    if (
        isinstance(value, str)
        and "number" in types
        and "string" not in types
        and len(value) <= MAX_NUMBER_TEXT_CHARS
        and re.fullmatch(NUMBER_TEXT_PATTERN, value)
    ):
        value = float(value)
        record_normalization(path, "decimal_number")
    if isinstance(value, float) and "number" in types and not math.isfinite(value):
        raise InputNormalizationError("Use a finite JSON number", code="non_finite_number", path=path)
    if isinstance(value, dict):
        value = value.copy()
        tag_names = {
            name for branch in branches for name, prop in branch.get("properties", {}).items() if "const" in prop
        }
        for name in tag_names & value.keys():
            choices = [
                branch["properties"][name]["const"]
                for branch in branches
                if "const" in branch.get("properties", {}).get(name, {})
            ]
            corrected = _normalize_choice(value[name], list(dict.fromkeys(choices)))
            if corrected != value[name]:
                value[name] = corrected
                record_normalization((*path, name), "enum_spelling")
        properties = _object_branch(branches, value).get("properties", {})
        return {
            name: child(item, properties[name], name) if name in properties else item for name, item in value.items()
        }
    if isinstance(value, list):
        candidates = [branch for branch in branches if branch.get("type") == "array"]
        if len(candidates) == 1:
            branch = candidates[0]
            if len(value) > branch.get("maxItems", 10_000):
                raise InputNormalizationError("Array exceeds the field's item limit", code="too_many_items", path=path)
            return [child(item, branch.get("items", {}), index) for index, item in enumerate(value)]
    return value


def normalize_tool_arguments(
    arguments: dict[str, Any], schema: dict[str, Any], failures: list[InputNormalizationError] | None = None
) -> dict[str, Any]:
    return _normalize_value(arguments, schema, schema, (), 0, failures)


def record_field_normalizations(
    before: Any, after: Any, node: dict[str, Any], root: dict[str, Any], path: tuple[str | int, ...] = ()
) -> None:
    kind = _input_kind(node)
    if kind:
        if before != after:
            record_normalization(path, "identifier_batch" if kind == "pmid_batch" else "identifier")
        return
    branches = schema_branches(node, root)
    if isinstance(before, dict) and isinstance(after, dict):
        properties = _object_branch(branches, after).get("properties", {})
        for name in before.keys() & after.keys() & properties.keys():
            record_field_normalizations(before[name], after[name], properties[name], root, (*path, name))
    elif isinstance(before, list) and isinstance(after, list):
        arrays = [branch for branch in branches if branch.get("type") == "array"]
        if len(arrays) == 1:
            for index, (raw, normalized) in enumerate(zip(before, after, strict=False)):
                record_field_normalizations(raw, normalized, arrays[0].get("items", {}), root, (*path, index))


def accepted_input_schema(canonical: dict[str, Any]) -> dict[str, Any]:
    """Compile transport alternatives from exactly the schema used to normalize.

    Root arguments remain a JSON object. Definitions describe native objects;
    references at field positions also accept one encoded object layer.
    """
    root = copy.deepcopy(canonical)

    def visit(node: dict[str, Any], *, field: bool = True, allow_choices: bool = True) -> dict[str, Any]:
        if node.get("x-pubmed-input"):
            return copy.deepcopy(node)
        result = copy.deepcopy(node)
        for key in ("properties", "$defs"):
            if key in node:
                result[key] = {name: visit(child, field=key != "$defs") for name, child in node[key].items()}
        if "items" in node:
            result["items"] = visit(node["items"])
        for key in ("anyOf", "oneOf"):
            if key in node:
                # Add transport alternatives once at this field, not again to
                # each branch (which would break oneOf discriminator semantics).
                branches = schema_branches(node, root)
                free_text = any(
                    branch.get("type") == "string" and not {"enum", "const"} & branch.keys() for branch in branches
                )
                result[key] = [
                    visit(child, field=False, allow_choices=allow_choices and not free_text) for child in node[key]
                ]
        # Literal discriminators also expose the same spelling normalization.
        choices = node.get("enum", [node["const"]] if "const" in node else [])
        if (
            allow_choices
            and choices
            and all(isinstance(choice, str) for choice in choices)
            and len({choice.lower() for choice in choices}) == len(choices)
        ):
            annotations: dict[str, Any] = {
                key: result[key] for key in ("title", "description", "default") if key in result
            }
            return {**annotations, "anyOf": [result, {"type": "string", "pattern": _choice_pattern(choices)}]}
        if not field:
            return result
        types = {branch.get("type") for branch in schema_branches(node, root)}
        if "string" in types:
            return result  # string/container unions are intentionally ambiguous
        alternatives: list[dict[str, Any]] = []
        if types & {"array", "object"}:
            alternatives.append(
                {
                    "type": "string",
                    "maxLength": MAX_ENCODED_CONTAINER_CHARS,
                    "contentMediaType": "application/json",
                    "contentSchema": copy.deepcopy(result),
                    "description": "One JSON-encoded container; the decoded value must satisfy contentSchema.",
                }
            )
            alternatives.append(
                {
                    "type": "string",
                    "maxLength": MAX_ENCODED_CONTAINER_CHARS,
                    "pattern": r"^\s*```(?:[jJ][sS][oO][nN])?[ \t]*\r?\n[\s\S]*\r?\n```\s*$",
                    "x-pubmed-encoding": "fenced-json",
                    "x-pubmed-decodedSchema": copy.deepcopy(result),
                    "description": "One JSON code fence; after removing the fence, decode JSON and validate against x-pubmed-decodedSchema.",
                }
            )
        if "integer" in types:
            alternatives.append(
                {
                    "type": "string",
                    "pattern": INTEGER_TEXT_PATTERN,
                    "maxLength": MAX_INTEGER_TEXT_CHARS,
                    "description": "ASCII decimal integer; the integer branch's bounds apply after conversion.",
                }
            )
        if "boolean" in types:
            alternatives.append(
                {
                    "type": "string",
                    "pattern": _choice_pattern(["true", "false"]),
                    "description": "Explicit true/false text, ignoring ASCII case and surrounding whitespace.",
                }
            )
        if "number" in types:
            alternatives.append(
                {
                    "type": "string",
                    "pattern": NUMBER_TEXT_PATTERN,
                    "maxLength": MAX_NUMBER_TEXT_CHARS,
                    "description": "Finite decimal number; the numeric branch's bounds apply after conversion.",
                }
            )
        if not alternatives:
            return result
        annotations = {key: result[key] for key in ("title", "description", "default") if key in result}
        if "anyOf" in result:
            return {**result, "anyOf": [*result["anyOf"], *alternatives]}
        return {**annotations, "anyOf": [result, *alternatives]}

    return visit(root, field=False)


def _field_location(
    root: dict[str, Any], location: tuple[str | int, ...]
) -> tuple[tuple[str | int, ...], dict[str, Any]]:
    """Remove Pydantic union labels and never reveal arbitrary unknown keys."""
    node = root
    path: tuple[str | int, ...] = ()
    for part in location:
        branches = schema_branches(node, root)
        if isinstance(part, int):
            arrays = [branch for branch in branches if branch.get("type") == "array"]
            if arrays:
                path = (*path, part)
                node = arrays[0].get("items", {})
            continue
        matches = [branch["properties"][part] for branch in branches if part in branch.get("properties", {})]
        if matches:
            node = matches[0]
            path = (*path, part)
            continue
        tagged = [
            branch
            for branch in branches
            if any(prop.get("const") == part for prop in branch.get("properties", {}).values())
        ]
        if tagged:
            node = tagged[0]
    return path, node


def expected_constraints(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Bounded, schema-owned hints, never validation context or rejected input."""
    constraints = (
        "type",
        "format",
        "enum",
        "const",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "examples",
    )
    branches = schema_branches(schema, root)
    summaries = [{key: branch[key] for key in constraints if key in branch} for branch in branches]
    if len(summaries) == 1:
        result = summaries[0]
        if branches[0].get("properties"):
            result["allowed_fields"] = list(branches[0]["properties"])
        return result
    return {"anyOf": summaries}


def _discriminator(schema: dict[str, Any]) -> dict[str, Any]:
    if "discriminator" in schema:
        return schema["discriminator"]
    for branch in schema.get("anyOf", []):
        if "discriminator" in branch:
            return branch["discriminator"]
    return {}


_ERROR_HINTS = {
    "missing": ("missing_field", "Add the required field."),
    "extra_forbidden": ("unknown_field", "Remove unknown fields; use only allowed_fields."),
    "string_type": ("invalid_type", "expected a string"),
    "int_type": ("invalid_type", "expected a JSON integer or ASCII decimal integer string"),
    "float_type": ("invalid_type", "expected a finite JSON number or decimal number string"),
    "bool_type": ("invalid_type", "expected JSON true or false, or explicit true/false text"),
    "list_type": ("invalid_type", "Use an array or a JSON array string."),
    "model_type": ("invalid_type", "Use an object or a JSON object string."),
    "union_tag_invalid": ("invalid_discriminator", "Use one of the discriminator choices."),
    "union_tag_not_found": ("missing_discriminator", "Add the discriminator field."),
    "literal_error": ("invalid_choice", "Use exactly one of the published choices."),
    "greater_than_equal": ("out_of_range", "Use a value within the published bounds."),
    "less_than_equal": ("out_of_range", "Use a value within the published bounds."),
    "too_long": ("too_many_items", "Reduce the number of items to the published maximum."),
    "too_short": ("too_few_items", "Provide at least the published minimum number of items."),
}


def validation_issues(error: ValidationError | InputNormalizationError, schema: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(error, InputNormalizationError):
        _, node = _field_location(schema, error.path)
        return [
            {
                "code": error.code,
                "path": pointer(error.path),
                "message": str(error),
                "expected": expected_constraints(node, schema),
            }
        ]
    issues: list[dict[str, Any]] = []
    for issue in error.errors(include_url=False, include_context=True, include_input=False):
        location = issue["loc"][:-1] if issue["type"] == "extra_forbidden" else issue["loc"]
        path, node = _field_location(schema, location)
        code, message = _ERROR_HINTS.get(
            issue["type"], ("invalid_value", "Use the field's published format and bounds.")
        )
        expected = expected_constraints(node, schema)
        if issue["type"] == "extra_forbidden":
            expected["allowed_fields"] = sorted(
                {name for branch in schema_branches(node, schema) for name in branch.get("properties", {})}
            )
        discriminator = _discriminator(node)
        if issue["type"].startswith("union_tag_") and discriminator:
            path = (*path, discriminator["propertyName"])
            expected = {"type": "string", "enum": list(discriminator["mapping"])}
        kind = _input_kind(node)
        if issue["type"] == "value_error" and kind:
            code = "invalid_identifier" if kind != "pmid_batch" else "invalid_identifier_batch"
            message = "Use a complete identifier in an accepted format; every batch item must be valid."
        # Pydantic wraps ValueError raised by typed validators. Recover only
        # our own static transport diagnostic, never arbitrary context/message
        # values from provider, application or third-party validators.
        transport_error = issue.get("ctx", {}).get("error")
        if isinstance(transport_error, InputNormalizationError):
            code, message = transport_error.code, str(transport_error)
        detail = {"code": code, "path": pointer(path), "message": message, "expected": expected}
        if detail not in issues:
            issues.append(detail)
    return issues


def invalid_arguments_result(errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "invalid_input",
        "executed": False,
        "errors": errors[:MAX_ERROR_DETAILS],
        "error_count": len(errors),
        "truncated": len(errors) > MAX_ERROR_DETAILS,
        "recovery": {
            "action": "correct_arguments",
            "retry_unchanged": False,
            "instruction": "Correct the reported fields using expected constraints, then call the same tool.",
        },
    }
