"""Input normalization helpers for MCP tool entry points.

Design:
    Tool implementations receive heterogeneous agent and user inputs. This
    module centralizes light-weight coercion for common identifiers and scalar
    parameters so individual tool handlers can work with normalized values.

Maintenance:
    Keep these helpers narrow and predictable. Validation with user-facing
    errors belongs in the tool layer; this module should focus on safe parsing
    and compatibility coercion only.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Union

logger = logging.getLogger(__name__)


class InputNormalizer:
    """Agent-friendly input normalizer for MCP tools."""

    PMID_PREFIXES = ["pmid:", "pmid", "pubmed:", "pubmed"]
    PMC_PREFIXES = ["pmc", "pmcid:", "pmcid"]

    @staticmethod
    def normalize_pmids(value: Union[str, list, int, None]) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str) and value.lower().strip() == "last":
            return ["last"]

        if isinstance(value, int):
            return [str(value)]

        if isinstance(value, (list, tuple)):
            result = []
            for item in value:
                result.extend(InputNormalizer.normalize_pmids(item))
            return result

        if isinstance(value, str):
            normalized = re.sub(r"[;|\s]+", ",", value.strip())
            parts = [p.strip() for p in normalized.split(",") if p.strip()]

            result = []
            for part in parts:
                cleaned = part
                for prefix in InputNormalizer.PMID_PREFIXES:
                    if cleaned.lower().startswith(prefix):
                        cleaned = cleaned[len(prefix) :].strip()
                        if cleaned.startswith(":"):
                            cleaned = cleaned[1:].strip()
                        break

                digits = re.sub(r"\D", "", cleaned)
                if digits:
                    result.append(digits)

            return result

        return []

    @staticmethod
    def normalize_pmid_single(value: Union[str, int, None]) -> str | None:
        pmids = InputNormalizer.normalize_pmids(value)
        return pmids[0] if pmids else None

    @staticmethod
    def normalize_pmcid(value: Union[str, None]) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        value = value.strip()
        for prefix in InputNormalizer.PMC_PREFIXES:
            if value.lower().startswith(prefix):
                value = value[len(prefix) :].strip()
                if value.startswith(":"):
                    value = value[1:].strip()
                break

        digits = re.sub(r"\D", "", value)
        return f"PMC{digits}" if digits else None

    @staticmethod
    def normalize_year(value: Union[str, int, None]) -> int | None:
        if value is None:
            return None

        if isinstance(value, int):
            return value if 1900 <= value <= 2100 else None

        if isinstance(value, str):
            match = re.search(r"(19|20)\d{2}", value.strip())
            if match:
                year = int(match.group())
                return year if 1900 <= year <= 2100 else None

        return None

    @staticmethod
    def normalize_limit(
        value: Union[int, str, None],
        default: int = 10,
        min_val: int = 1,
        max_val: int = 100,
    ) -> int:
        if value is None:
            return default

        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                return default

        if isinstance(value, int):
            return max(min_val, min(value, max_val))

        return default

    @staticmethod
    def normalize_bool(value: Union[bool, str, int, None], default: bool = False) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        if isinstance(value, int):
            return bool(value)

        if isinstance(value, str):
            value_lower = value.strip().lower()
            if value_lower in ("true", "yes", "1", "on", "t", "y"):
                return True
            if value_lower in ("false", "no", "0", "off", "f", "n"):
                return False

        return default

    @staticmethod
    def normalize_query(query: Union[str, None]) -> str:
        if not query:
            return ""

        query = query.strip()
        query = query.replace("\u201c", '"').replace("\u201d", '"')
        query = query.replace("\u2018", "'").replace("\u2019", "'")

        for pattern, replacement in [
            (r"\bAdn\b", "AND"),
            (r"\bOr\b", "OR"),
            (r"\bNto\b", "NOT"),
        ]:
            query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

        return query

    @staticmethod
    def normalize_doi(value: Union[str, None]) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        value = value.strip()
        for prefix in [
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
        ]:
            if value.lower().startswith(prefix):
                value = value[len(prefix) :]
                break

        if value.lower().startswith("doi:"):
            value = value[4:].strip()

        if value.startswith("10.") and "/" in value:
            return value

        return None

    @staticmethod
    def normalize_identifier(value: Union[str, int, None]) -> dict[str, str | None]:
        result: dict[str, str | None] = {
            "type": None,
            "value": None,
            "original": str(value) if value is not None else None,
        }

        if value is None:
            return result

        if isinstance(value, int):
            result["type"] = "pmid"
            result["value"] = str(value)
            return result

        if not isinstance(value, str):
            value = str(value)

        value = value.strip()
        if value.startswith("10.") or "doi.org/" in value.lower() or value.lower().startswith("doi:"):
            doi = InputNormalizer.normalize_doi(value)
            if doi:
                result["type"] = "doi"
                result["value"] = doi
                return result

        if value.lower().startswith("pmc") or value.lower().startswith("pmcid"):
            pmcid = InputNormalizer.normalize_pmcid(value)
            if pmcid:
                result["type"] = "pmcid"
                result["value"] = pmcid
                return result

        if value.lower().startswith("pmid"):
            pmid = InputNormalizer.normalize_pmid_single(value)
            if pmid:
                result["type"] = "pmid"
                result["value"] = pmid
                return result

        cleaned = re.sub(r"\D", "", value)
        if cleaned and 6 <= len(cleaned) <= 10:
            result["type"] = "pmid"
            result["value"] = cleaned

        return result


KEY_ALIASES = {
    "year_from": "min_year",
    "from_year": "min_year",
    "start_year": "min_year",
    "year_to": "max_year",
    "to_year": "max_year",
    "end_year": "max_year",
    "max_results": "limit",
    "num_results": "limit",
    "count": "limit",
    "n": "limit",
    "limit_per_level": "limit",
    "format": "output_format",
    "fmt": "output_format",
    "pubmed_id": "pmid",
    "pmc_id": "pmcid",
}


def apply_key_aliases(kwargs: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in kwargs.items():
        standard_key = KEY_ALIASES.get(key.lower(), key)
        if standard_key not in result:
            result[standard_key] = value
        elif key != standard_key:
            logger.debug("Ignoring alias '%s' because '%s' already present", key, standard_key)
    return result


__all__ = ["InputNormalizer", "KEY_ALIASES", "apply_key_aliases"]