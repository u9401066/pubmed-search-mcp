"""Frozen BEIR corpus with a shared SQLite FTS5 backend and audited budgets.

The backend reads corpus.jsonl only. It has no access to qrels or query answers.
Numeric transport IDs are synthetic; they are NOT real PubMed identifiers.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class FrozenCorpus:
    """Independent lexical backend shared by basic tools and the repo arm."""

    def __init__(self, corpus_path: Path, audit_path: Path, *, search_budget: int = 6, document_budget: int = 120):
        if search_budget <= 0 or document_budget <= 0:
            raise ValueError("Budgets must be positive")
        self.audit_path = audit_path
        self.search_budget = search_budget
        self.document_budget = document_budget
        self.search_calls = 0
        self.document_exposures = 0
        self.events: list[dict[str, Any]] = []
        self.observed_ids: set[str] = set()
        raw = corpus_path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if not rows or len({row["_id"] for row in rows}) != len(rows):
            raise ValueError("Corpus must contain unique document IDs")
        self.documents: dict[str, dict[str, Any]] = {}
        self.original_ids: dict[str, str] = {}
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE VIRTUAL TABLE papers USING fts5(id UNINDEXED, title, abstract)")
        for index, row in enumerate(sorted(rows, key=lambda row: str(row["_id"]))):
            transport_id = str(80000000 + index)
            original_id = str(row["_id"])
            self.original_ids[transport_id] = original_id
            self.documents[transport_id] = {
                "pmid": transport_id,
                "title": row.get("title", ""),
                "abstract": row.get("text", ""),
                "authors": [],
                "benchmark_id": original_id,
            }
            self.connection.execute(
                "INSERT INTO papers VALUES (?, ?, ?)",
                (transport_id, row.get("title", ""), row.get("text", "")),
            )
        self.save_audit()

    def save_audit(self) -> None:
        self.audit_path.write_text(
            json.dumps(
                {
                    "corpus_sha256": self.sha256,
                    "backend": "sqlite_fts5_bm25_or_terms",
                    "sqlite_version": sqlite3.sqlite_version,
                    "transport_ids": "synthetic_numeric_ids_not_real_pmids",
                    "search_budget": self.search_budget,
                    "document_budget": self.document_budget,
                    "search_calls": self.search_calls,
                    "document_exposures": self.document_exposures,
                    "observed_ids": sorted(self.observed_ids),
                    "id_map": self.original_ids,
                    "events": self.events,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _expose(self, ids: list[str], operation: str, query: str | None = None) -> list[dict[str, Any]]:
        remaining = max(0, self.document_budget - self.document_exposures)
        ids = ids[:remaining]
        self.document_exposures += len(ids)
        self.observed_ids.update(self.original_ids[doc_id] for doc_id in ids)
        self.events.append({"operation": operation, "query": query, "ids": [self.original_ids[i] for i in ids]})
        self.save_audit()
        return [dict(self.documents[doc_id]) for doc_id in ids]

    async def search(self, query: str, limit: int = 10, **_kwargs: Any) -> list[dict[str, Any]]:
        if self.search_calls >= self.search_budget or self.document_exposures >= self.document_budget:
            self.events.append({"operation": "budget_exhausted", "query": query})
            self.save_audit()
            raise ValueError("Frozen-corpus search/document budget exhausted; submit your selection")
        self.search_calls += 1
        # Explicitly a bag-of-words benchmark backend, not PubMed Boolean syntax.
        terms = list(dict.fromkeys(re.findall(r"\b\w+\b", query.lower())))
        expression = " OR ".join('"' + term + '"' for term in terms)
        rows = (
            self.connection.execute(
                "SELECT id FROM papers WHERE papers MATCH ? ORDER BY bm25(papers), id LIMIT ?",
                (expression, min(max(int(limit), 1), 100)),
            ).fetchall()
            if terms
            else []
        )
        return self._expose([row[0] for row in rows], "search", query)

    async def fetch_details(self, pmids: list[str], **_kwargs: Any) -> list[dict[str, Any]]:
        return self._expose([str(pmid) for pmid in pmids if str(pmid) in self.documents], "read")

    def close(self) -> None:
        self.connection.close()
