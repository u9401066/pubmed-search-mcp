"""Conservative local query materials when provider intelligence is unavailable."""

from __future__ import annotations

import re
from typing import Any


def build_fallback_query_materials(
    topic: str,
    *,
    strategy: str,
    include_suggestions: bool,
    fallback_reason: str,
) -> dict[str, Any]:
    """Offer unverified candidates for a validated topic without rewriting Boolean syntax."""
    queries: list[dict[str, Any]] = []
    if include_suggestions:
        if re.search(r'[()[\]"]|\b(?:AND|OR|NOT)\b', topic, re.IGNORECASE):
            queries.append({"id": "q_original", "query": topic, "purpose": "Original query, unverified", "priority": 1})
        else:
            queries.extend(
                [
                    {
                        "id": "q1_title",
                        "query": f"({topic})[Title]",
                        "purpose": "Title terms, not exact title identity",
                        "priority": 1,
                    },
                    {
                        "id": "q2_tiab",
                        "query": f"({topic})[Title/Abstract]",
                        "purpose": "Title or abstract",
                        "priority": 2,
                    },
                ]
            )
            words = topic.lower().split()
            if len(words) > 1:
                queries.append(
                    {
                        "id": "q3_and",
                        "query": "(" + " AND ".join(words) + ")",
                        "purpose": "All keywords required",
                        "priority": 2,
                    }
                )
            queries.append(
                {
                    "id": "q4_mesh",
                    "query": f"({topic})[MeSH Terms]",
                    "purpose": "Unverified MeSH candidate",
                    "priority": 2,
                }
            )
    return {
        "status": "partial",
        "generation_mode": "basic_fallback",
        "fallback_reason": fallback_reason,
        "topic": topic,
        "strategy": strategy,
        "spelling": None,
        "mesh_terms": [],
        "queries_count": len(queries),
        "suggested_queries": queries,
        "instruction": "Review the query materials, then execute unified_search; local query analysis cannot verify NCBI translation",
        "warnings": [
            "MeSH lookup and PubMed translation analysis were not available; suggested queries are unverified."
        ],
        "note": "Using explicit fallback generator (MeSH lookup unavailable)",
    }
