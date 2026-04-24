"""Reference-list verification service.

Design goals:
    - Accept plain-text reference lists passed from an MCP client.
    - Reuse existing PubMed evidence paths first: explicit PMID, DOI search,
      ECitMatch, then a conservative title search fallback.
    - Return structured evidence instead of a black-box yes/no verdict.

This is intentionally the first-stage implementation for reference-list
verification only. It does not attempt to extract references from arbitrary
full manuscripts yet.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.shared.article_identity import normalize_article_doi, normalize_article_title

if TYPE_CHECKING:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

ReferenceStatus = Literal["verified", "partial_match", "unresolved", "invalid_input"]
ResolutionMethod = Literal["pmid", "doi_search", "ecitmatch", "title_search"]

_REFERENCE_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s*")
_DOI_RE = re.compile(r"\b(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{5,9})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_FIRST_PAGE_RE = re.compile(r":\s*([A-Za-z]?\d+)")
_VOLUME_RE = re.compile(r";\s*([A-Za-z0-9][A-Za-z0-9 .-]{0,20}?)(?:\(|:|;)" )


@dataclass(slots=True)
class ParsedReference:
    """Structured fields extracted from one reference entry.

    Attributes:
        index: 1-based position in the provided reference list.
        raw_text: Original reference string as received.
        cleaned_text: Whitespace-normalized reference string without numbering.
        first_author: Parsed first author surname chunk.
        year: Four-digit publication year if found.
        journal: Parsed journal name or abbreviation.
        volume: Parsed volume token.
        first_page: Parsed first page token.
        title: Parsed article title candidate.
        doi: Normalized DOI if present.
        pmid: Explicit PMID if present in the reference text.
    """

    index: int
    raw_text: str
    cleaned_text: str
    first_author: str = ""
    year: str = ""
    journal: str = ""
    volume: str = ""
    first_page: str = ""
    title: str = ""
    doi: str = ""
    pmid: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the parsed reference for JSON output."""
        return {
            "index": self.index,
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "first_author": self.first_author,
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "first_page": self.first_page,
            "title": self.title,
            "doi": self.doi,
            "pmid": self.pmid,
        }


class ReferenceVerificationService:
    """Verify reference-list entries against PubMed evidence.

    The service uses existing infrastructure already present in the repository:
    explicit PMID lookup, DOI-based PubMed search, ECitMatch, and a narrow title
    search fallback. Results are returned with field-level evidence rather than
    a binary pass/fail only.

    Args:
        searcher: Existing LiteratureSearcher instance.
    """

    def __init__(self, searcher: LiteratureSearcher):
        self._searcher = searcher

    def extract_references(self, reference_text: str, *, limit: int = 100) -> list[str]:
        """Split a plain-text reference block into individual entries.

        Args:
            reference_text: Plain text containing one reference list.
            limit: Maximum number of extracted entries to return.

        Returns:
            List of reference entry strings, preserving original order.
        """
        if limit <= 0:
            return []

        normalized_lines = [line.strip() for line in reference_text.splitlines() if line.strip()]
        if not normalized_lines:
            return []

        has_numbered_entries = any(_REFERENCE_MARKER_RE.match(line) for line in normalized_lines)
        if not has_numbered_entries:
            return normalized_lines[:limit]

        entries: list[str] = []
        current: list[str] = []
        for line in normalized_lines:
            if _REFERENCE_MARKER_RE.match(line):
                if current:
                    entries.append(" ".join(current).strip())
                    if len(entries) >= limit:
                        return entries
                current = [_REFERENCE_MARKER_RE.sub("", line, count=1).strip()]
                continue
            current.append(line)

        if current and len(entries) < limit:
            entries.append(" ".join(current).strip())

        return entries[:limit]

    def parse_reference(self, reference_text: str, *, index: int) -> ParsedReference:
        """Extract minimal verification fields from one reference entry.

        Args:
            reference_text: One reference string.
            index: 1-based position in the input list.

        Returns:
            ParsedReference containing heuristically extracted fields.
        """
        cleaned = self._clean_reference_text(reference_text)
        doi_match = _DOI_RE.search(cleaned)
        pmid_match = _PMID_RE.search(cleaned)
        year_match = _YEAR_RE.search(cleaned)

        doi = normalize_article_doi(doi_match.group(1)) if doi_match else ""
        pmid = pmid_match.group(1) if pmid_match else ""
        year = year_match.group(0) if year_match else ""

        pre_year = cleaned.split(year, 1)[0] if year else cleaned
        segments = [segment.strip(" .;") for segment in pre_year.split(".") if segment.strip(" .;")]
        authors_segment = segments[0] if segments else ""
        journal = segments[-1] if len(segments) >= 2 else ""
        title = ". ".join(segments[1:-1]) if len(segments) >= 3 else ""

        after_year = cleaned.split(year, 1)[1] if year else ""
        volume = self._extract_volume(after_year)
        first_page = self._extract_first_page(after_year)

        return ParsedReference(
            index=index,
            raw_text=reference_text,
            cleaned_text=cleaned,
            first_author=self._extract_first_author(authors_segment),
            year=year,
            journal=journal,
            volume=volume,
            first_page=first_page,
            title=title,
            doi=doi,
            pmid=pmid,
        )

    async def verify_reference_list(
        self,
        reference_text: str,
        *,
        source_name: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Verify a plain-text reference list.

        Args:
            reference_text: Plain text where each line or numbered block is one
                reference entry.
            source_name: Optional label such as a filename for reporting.
            limit: Maximum references to process in one call.

        Returns:
            Structured verification report with per-reference evidence.
        """
        entries = self.extract_references(reference_text, limit=limit)
        if not entries:
            return {
                "success": False,
                "source_name": source_name,
                "reference_count": 0,
                "error": "No reference entries found",
                "hint": "Provide one reference per line or a numbered reference list",
            }

        parsed_entries = [self.parse_reference(entry, index=i) for i, entry in enumerate(entries, start=1)]
        prefetched_citation_pmids = await self._prefetch_citation_matches(parsed_entries)
        prefetched_articles = await self._prefetch_articles(
            {
                *{parsed.pmid for parsed in parsed_entries if parsed.pmid},
                *{pmid for pmid in prefetched_citation_pmids.values() if pmid},
            }
        )
        results = list(
            await asyncio.gather(
                *[
                    self._verify_parsed_reference(
                        parsed,
                        prefetched_citation_pmid=prefetched_citation_pmids.get(parsed.index),
                        article_cache=prefetched_articles,
                    )
                    for parsed in parsed_entries
                ]
            )
        )
        summary = {
            "verified": sum(1 for row in results if row["status"] == "verified"),
            "partial_match": sum(1 for row in results if row["status"] == "partial_match"),
            "unresolved": sum(1 for row in results if row["status"] == "unresolved"),
            "invalid_input": sum(1 for row in results if row["status"] == "invalid_input"),
        }
        review_workflow = self._build_review_workflow(results)
        return {
            "success": True,
            "mode": "reference_list_verification",
            "source_name": source_name,
            "reference_count": len(results),
            "summary": summary,
            "results": results,
            "review_workflow": review_workflow,
            "next_steps": [
                "Review partial_match rows for field-level mismatches",
                "Review unresolved rows for non-PubMed citations or parser misses",
                "Use PMID/DOI evidence before title-only matches when making editorial decisions",
            ],
        }

    async def verify_reference(self, reference_text: str, *, index: int) -> dict[str, Any]:
        """Verify one parsed reference entry against PubMed evidence.

        Args:
            reference_text: One reference string.
            index: 1-based position in the input list.

        Returns:
            Structured row describing parsed fields, evidence, and match status.
        """
        parsed = self.parse_reference(reference_text, index=index)
        return await self._verify_parsed_reference(parsed)

    async def _verify_parsed_reference(
        self,
        parsed: ParsedReference,
        *,
        prefetched_citation_pmid: str | None = None,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Verify one parsed reference, optionally reusing batch-prefetched data."""
        if not parsed.cleaned_text:
            return {
                "index": parsed.index,
                "status": "invalid_input",
                "resolution_method": None,
                "input_reference": parsed.raw_text,
                "parsed_reference": parsed.to_dict(),
                "matched_article": None,
                "comparison": {},
                "matched_fields": [],
                "mismatched_fields": [],
                "notes": ["Reference entry is empty after normalization"],
            }

        article, method = await self._resolve_reference(
            parsed,
            prefetched_citation_pmid=prefetched_citation_pmid,
            article_cache=article_cache,
        )
        comparison = self._build_comparison(parsed, article)
        matched_fields = [field for field, matched in comparison.items() if matched is True]
        mismatched_fields = [field for field, matched in comparison.items() if matched is False]
        status = self._determine_status(parsed, article, comparison)

        notes = self._build_notes(parsed, article, method, status, matched_fields, mismatched_fields)
        review_required = status in {"partial_match", "unresolved"}
        review_strategy = self._build_retry_strategy(parsed, method=method, status=status)
        return {
            "index": parsed.index,
            "status": status,
            "resolution_method": method,
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": self._serialize_article(article),
            "comparison": comparison,
            "matched_fields": matched_fields,
            "mismatched_fields": mismatched_fields,
            "notes": notes,
            "review_required": review_required,
            "review_strategy": review_strategy,
        }

    def _build_review_workflow(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a manual-review queue for partial and unresolved references."""
        queue = [
            {
                "index": row.get("index"),
                "status": row.get("status"),
                "resolution_method": row.get("resolution_method"),
                "review_priority": self._review_priority(row),
                "review_reason": self._review_reason(row),
                "retry_queries": row.get("review_strategy", {}).get("retry_queries", []),
                "review_checklist": row.get("review_strategy", {}).get("review_checklist", []),
            }
            for row in results
            if row.get("review_required")
        ]

        queue.sort(
            key=lambda item: (
                self._priority_rank(item.get("review_priority", "low")),
                int(item.get("index") or 0),
            )
        )

        return {
            "requires_manual_review": bool(queue),
            "review_count": len(queue),
            "reviewed_count": 0,
            "review_queue": queue,
            "suggested_actions": [
                "Use retry_queries to run targeted re-search before manual acceptance/rejection",
                "Mark each queue item as accepted/rejected with a reviewer note in your client workflow",
                "Prioritize high-risk entries first, then process medium and low-risk entries",
            ],
        }

    @staticmethod
    def _priority_rank(priority: str) -> int:
        """Map review priority labels to sortable ranks."""
        ranks = {"high": 0, "medium": 1, "low": 2}
        return ranks.get(priority, 2)

    def _review_priority(self, row: dict[str, Any]) -> Literal["high", "medium", "low"]:
        """Assign manual-review priority for queue ordering."""
        status = str(row.get("status", ""))
        parsed = row.get("parsed_reference", {}) or {}
        comparison = row.get("comparison", {}) or {}

        if status == "unresolved" and (parsed.get("doi") or parsed.get("pmid")):
            return "high"
        if status == "unresolved" and parsed.get("title"):
            return "medium"
        if status == "partial_match" and any(
            comparison.get(field) is False for field in ("doi", "pmid", "year", "journal")
        ):
            return "high"
        if status == "partial_match":
            return "medium"
        return "low"

    def _review_reason(self, row: dict[str, Any]) -> str:
        """Generate a concise reason for manual review."""
        status = str(row.get("status", ""))
        parsed = row.get("parsed_reference", {}) or {}
        mismatched_fields = row.get("mismatched_fields", []) or []

        if status == "unresolved":
            if parsed.get("doi"):
                return "DOI present but unresolved; verify DOI transcription and index coverage"
            if parsed.get("title"):
                return "Title-only resolution failed; inspect title normalization and source journal metadata"
            return "Insufficient structured fields; manually inspect author/journal/year extraction"
        if mismatched_fields:
            return f"Candidate found but mismatched fields: {', '.join(mismatched_fields)}"
        return "Manual review requested"

    def _build_retry_strategy(
        self,
        parsed: ParsedReference,
        *,
        method: ResolutionMethod | None,
        status: ReferenceStatus,
    ) -> dict[str, Any]:
        """Build deterministic re-search guidance for manual review workflows."""
        if status not in {"partial_match", "unresolved"}:
            return {"retry_queries": [], "review_checklist": []}

        retry_queries: list[dict[str, str]] = []
        if parsed.pmid:
            retry_queries.append(
                {
                    "label": "pmid_direct",
                    "query": f'"{parsed.pmid}"[PMID]',
                    "purpose": "Verify the explicitly provided PMID",
                }
            )
        if parsed.doi:
            retry_queries.append(
                {
                    "label": "doi_aid",
                    "query": f'"{parsed.doi}"[AID]',
                    "purpose": "DOI-anchored recheck in PubMed",
                }
            )
            retry_queries.append(
                {
                    "label": "doi_all_fields",
                    "query": f'"{parsed.doi}"[All Fields]',
                    "purpose": "Fallback DOI match when AID indexing is incomplete",
                }
            )
        if parsed.title:
            safe_title = re.sub(r"\s+", " ", parsed.title.replace('"', " ")).strip()
            retry_queries.append(
                {
                    "label": "title_exact",
                    "query": f'"{safe_title}"[Title]',
                    "purpose": "Exact-title recheck",
                }
            )
            if parsed.year:
                retry_queries.append(
                    {
                        "label": "title_year",
                        "query": f'"{safe_title}"[Title] AND "{parsed.year}"[Date - Publication]',
                        "purpose": "Narrow title search with publication year",
                    }
                )
        if parsed.journal and parsed.year:
            journal_norm = re.sub(r"\s+", " ", parsed.journal).strip()
            retry_queries.append(
                {
                    "label": "journal_year_author",
                    "query": self._build_journal_year_author_query(parsed, journal_norm),
                    "purpose": "Metadata-driven fallback for noisy titles",
                }
            )

        review_checklist = [
            "Confirm author surname, journal abbreviation, and year were parsed correctly",
            "Run retry queries in order until one yields a convincing candidate",
            "Accept only when DOI/PMID matches or when year+journal plus one field (page/author/volume) agree",
            "Document acceptance/rejection rationale for each unresolved reference",
        ]
        if method == "title_search":
            review_checklist.insert(1, "Title-search candidates are weak evidence; prefer DOI/PMID or citation metadata")

        return {
            "retry_queries": retry_queries,
            "review_checklist": review_checklist,
        }

    def _build_journal_year_author_query(self, parsed: ParsedReference, journal_norm: str) -> str:
        """Build a compact metadata fallback query for manual retries."""
        clauses = [f'"{journal_norm}"[Journal]', f'"{parsed.year}"[Date - Publication]']
        if parsed.first_author:
            clauses.append(f'"{parsed.first_author}"[Author]')
        if parsed.volume:
            clauses.append(f'"{parsed.volume}"[All Fields]')
        if parsed.first_page:
            clauses.append(f'"{parsed.first_page}"[All Fields]')
        return " AND ".join(clauses)

    async def _resolve_reference(
        self,
        parsed: ParsedReference,
        *,
        prefetched_citation_pmid: str | None = None,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, ResolutionMethod | None]:
        """Resolve one parsed reference to the best PubMed article candidate."""
        if parsed.pmid:
            article = await self._fetch_article_by_pmid(parsed.pmid, article_cache=article_cache)
            if article:
                return article, "pmid"

        if parsed.doi:
            article = await self._resolve_by_doi(parsed)
            if article:
                return article, "doi_search"

        if parsed.journal and parsed.year:
            article = await self._resolve_by_citation(
                parsed,
                prefetched_pmid=prefetched_citation_pmid,
                article_cache=article_cache,
            )
            if article:
                return article, "ecitmatch"

        if parsed.title:
            article = await self._resolve_by_title(parsed)
            if article:
                return article, "title_search"

        return None, None

    async def _resolve_by_doi(self, parsed: ParsedReference) -> dict[str, Any] | None:
        """Resolve by DOI using PubMed search results and exact DOI filtering."""
        try:
            results = await self._searcher.search(f'"{parsed.doi}"[AID]', limit=3)
        except Exception:
            return None
        return self._choose_best_candidate(parsed, results)

    async def _resolve_by_citation(
        self,
        parsed: ParsedReference,
        *,
        prefetched_pmid: str | None = None,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve by ECitMatch using existing Entrez utility support."""
        pmid = prefetched_pmid
        if not pmid:
            pmid = await self._searcher.find_by_citation(
                journal=parsed.journal,
                year=parsed.year,
                volume=parsed.volume,
                first_page=parsed.first_page,
                author=parsed.first_author,
                title=parsed.title,
            )
        if not pmid:
            return None
        return await self._fetch_article_by_pmid(pmid, article_cache=article_cache)

    async def _resolve_by_title(self, parsed: ParsedReference) -> dict[str, Any] | None:
        """Resolve by a conservative exact-title PubMed search fallback."""
        safe_title = re.sub(r"\s+", " ", parsed.title.replace('"', " ")).strip()
        title_query = normalize_article_title(safe_title)
        if len(title_query) < 8:
            return None

        min_year = int(parsed.year) if parsed.year.isdigit() else None
        max_year = int(parsed.year) if parsed.year.isdigit() else None
        try:
            results = await self._searcher.search(
                f'"{safe_title}"[Title]',
                limit=5,
                min_year=min_year,
                max_year=max_year,
            )
        except Exception:
            return None
        return self._choose_best_candidate(parsed, results)

    async def _fetch_article_by_pmid(
        self,
        pmid: str,
        *,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one PubMed article and discard malformed or error payloads."""
        if article_cache and pmid in article_cache:
            return article_cache[pmid]

        details = await self._searcher.fetch_details([pmid])
        if not details:
            return None
        article = details[0]
        if not isinstance(article, dict) or article.get("error"):
            return None
        return article

    async def _prefetch_citation_matches(self, parsed_entries: list[ParsedReference]) -> dict[int, str]:
        """Batch-resolve citation-like references via the ECitMatch workflow."""
        if not hasattr(self._searcher, "verify_references"):
            return {}

        ecitmatch_candidates = [
            parsed
            for parsed in parsed_entries
            if not parsed.pmid and not parsed.doi and parsed.journal and parsed.year
        ]
        if not ecitmatch_candidates:
            return {}

        payload = [
            {
                "journal": parsed.journal,
                "year": parsed.year,
                "volume": parsed.volume,
                "first_page": parsed.first_page,
                "author": parsed.first_author,
                "title": parsed.title,
            }
            for parsed in ecitmatch_candidates
        ]
        try:
            matches = await self._searcher.verify_references(payload)
        except Exception:
            return {}

        prefetched: dict[int, str] = {}
        for parsed, match in zip(ecitmatch_candidates, matches, strict=False):
            if not isinstance(match, dict):
                continue
            pmid = str(match.get("pmid", "") or "")
            verified = match.get("verified")
            if pmid and (verified is True or verified == "True"):
                prefetched[parsed.index] = pmid
        return prefetched

    async def _prefetch_articles(self, pmids: set[str]) -> dict[str, dict[str, Any]]:
        """Warm a PMID->article cache for references already resolved upstream."""
        clean_pmids = sorted({pmid for pmid in pmids if pmid})
        if not clean_pmids:
            return {}

        try:
            details = await self._searcher.fetch_details(clean_pmids)
        except Exception:
            return {}

        cache: dict[str, dict[str, Any]] = {}
        for article in details:
            if not isinstance(article, dict) or article.get("error"):
                continue
            pmid = str(article.get("pmid", "") or "")
            if pmid:
                cache[pmid] = article
        return cache

    def _choose_best_candidate(self, parsed: ParsedReference, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Choose the highest-scoring candidate from a small PubMed result set."""
        scored: list[tuple[int, dict[str, Any]]] = []
        for article in candidates:
            if not isinstance(article, dict) or article.get("error"):
                continue
            score = self._score_candidate(parsed, article)
            if score > 0:
                scored.append((score, article))

        if not scored:
            return None

        scored.sort(key=lambda row: row[0], reverse=True)
        return scored[0][1]

    def _score_candidate(self, parsed: ParsedReference, article: dict[str, Any]) -> int:
        """Score one candidate article against parsed reference fields."""
        comparison = self._build_comparison(parsed, article)
        score = 0
        weights = {
            "pmid": 100,
            "doi": 100,
            "year": 35,
            "journal": 30,
            "volume": 20,
            "first_page": 20,
            "first_author": 15,
            "title": 10,
        }
        for field, matched in comparison.items():
            if matched is True:
                score += weights.get(field, 0)
        return score

    def _build_comparison(self, parsed: ParsedReference, article: dict[str, Any] | None) -> dict[str, bool | None]:
        """Build field-level comparison evidence for a candidate article."""
        if article is None:
            return {
                "pmid": None if not parsed.pmid else False,
                "doi": None if not parsed.doi else False,
                "year": None if not parsed.year else False,
                "journal": None if not parsed.journal else False,
                "volume": None if not parsed.volume else False,
                "first_page": None if not parsed.first_page else False,
                "first_author": None if not parsed.first_author else False,
                "title": None if not parsed.title else False,
            }

        comparisons: dict[str, bool | None] = {
            "pmid": None,
            "doi": None,
            "year": None,
            "journal": None,
            "volume": None,
            "first_page": None,
            "first_author": None,
            "title": None,
        }

        if parsed.pmid:
            comparisons["pmid"] = parsed.pmid == str(article.get("pmid", ""))
        if parsed.doi:
            comparisons["doi"] = parsed.doi == normalize_article_doi(article.get("doi", ""))
        if parsed.year:
            comparisons["year"] = parsed.year == str(article.get("year", ""))
        if parsed.journal:
            journal_candidates = [article.get("journal", ""), article.get("journal_abbrev", "")]
            normalized_journal = self._normalize_text(parsed.journal)
            comparisons["journal"] = any(
                normalized_journal
                and self._normalize_text(candidate)
                and (
                    normalized_journal == self._normalize_text(candidate)
                    or normalized_journal in self._normalize_text(candidate)
                    or self._normalize_text(candidate) in normalized_journal
                )
                for candidate in journal_candidates
            )
        if parsed.volume:
            comparisons["volume"] = self._normalize_text(parsed.volume) == self._normalize_text(article.get("volume", ""))
        if parsed.first_page:
            comparisons["first_page"] = self._normalize_text(parsed.first_page) == self._normalize_text(
                self._extract_first_page(str(article.get("pages", "")))
            )
        if parsed.first_author:
            comparisons["first_author"] = self._normalize_text(parsed.first_author) == self._normalize_text(
                self._extract_article_first_author(article)
            )
        if parsed.title:
            normalized_title = normalize_article_title(parsed.title)
            comparisons["title"] = normalized_title == normalize_article_title(article.get("title", ""))

        return comparisons

    def _determine_status(
        self,
        parsed: ParsedReference,
        article: dict[str, Any] | None,
        comparison: dict[str, bool | None],
    ) -> ReferenceStatus:
        """Determine the overall verification status from field-level evidence."""
        if not parsed.cleaned_text:
            return "invalid_input"
        if article is None:
            return "unresolved"

        if comparison.get("doi") is True:
            return "verified"

        comparable_truths = [matched for matched in comparison.values() if matched is not None]
        mismatches = [field for field, matched in comparison.items() if matched is False]
        matched_fields = [field for field, matched in comparison.items() if matched is True]

        if comparison.get("pmid") is True and not mismatches:
            return "verified"

        if (
            comparison.get("year") is True
            and comparison.get("journal") is True
            and (
                comparison.get("first_page") is True
                or comparison.get("first_author") is True
                or comparison.get("volume") is True
            )
        ):
            return "verified"

        if matched_fields and comparable_truths:
            return "partial_match"

        return "unresolved"

    def _build_notes(
        self,
        parsed: ParsedReference,
        article: dict[str, Any] | None,
        method: ResolutionMethod | None,
        status: ReferenceStatus,
        matched_fields: list[str],
        mismatched_fields: list[str],
    ) -> list[str]:
        """Build concise evidence notes for one verification row."""
        notes: list[str] = []
        if method:
            notes.append(f"Resolved via {method}")
        if article is None:
            if parsed.doi:
                notes.append("No PubMed candidate resolved from the provided DOI")
            elif parsed.journal and parsed.year:
                notes.append("ECitMatch did not resolve this citation")
            else:
                notes.append("Insufficient structured metadata for PubMed resolution")
            return notes

        if status == "verified":
            notes.append("PubMed evidence supports this reference")
        elif status == "partial_match":
            notes.append("A close PubMed candidate was found, but some provided fields disagree")
        else:
            notes.append("A PubMed candidate was found, but evidence is too weak to verify")

        if matched_fields:
            notes.append(f"Matched fields: {', '.join(matched_fields)}")
        if mismatched_fields:
            notes.append(f"Mismatched fields: {', '.join(mismatched_fields)}")
        return notes

    def _serialize_article(self, article: dict[str, Any] | None) -> dict[str, Any] | None:
        """Return the article subset used for user-facing evidence reporting."""
        if article is None:
            return None
        return {
            "pmid": article.get("pmid", ""),
            "doi": article.get("doi", ""),
            "title": article.get("title", ""),
            "journal": article.get("journal", ""),
            "journal_abbrev": article.get("journal_abbrev", ""),
            "year": article.get("year", ""),
            "volume": article.get("volume", ""),
            "pages": article.get("pages", ""),
            "first_author": self._extract_article_first_author(article),
        }

    @staticmethod
    def _clean_reference_text(reference_text: str) -> str:
        """Normalize whitespace and remove leading numbering markers."""
        cleaned = _REFERENCE_MARKER_RE.sub("", reference_text.strip(), count=1)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        """Normalize free-text bibliographic fields for comparison."""
        if not value:
            return ""
        normalized = value.lower()
        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = re.sub(r"\b(et|al)\b", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def _extract_first_author(authors_segment: str) -> str:
        """Extract the first author surname chunk from the author segment."""
        if not authors_segment:
            return ""
        leading = authors_segment.split(",", 1)[0].strip()
        tokens = re.sub(r"[^A-Za-z\s-]", " ", leading).split()
        while tokens and len(tokens[-1]) == 1:
            tokens.pop()
        return " ".join(tokens).strip()

    @staticmethod
    def _extract_volume(after_year: str) -> str:
        """Extract a conservative volume token from the post-year citation tail."""
        if not after_year:
            return ""
        match = _VOLUME_RE.search(after_year)
        if not match:
            return ""
        return match.group(1).strip(" .;")

    @staticmethod
    def _extract_first_page(text: str) -> str:
        """Extract the first page token from a pages string or citation tail."""
        if not text:
            return ""
        match = _FIRST_PAGE_RE.search(text)
        if match:
            return match.group(1)

        fallback = re.search(r"\b([A-Za-z]?\d+)(?:[-–]\d+)?\b", text)
        return fallback.group(1) if fallback else ""

    @staticmethod
    def _extract_article_first_author(article: dict[str, Any]) -> str:
        """Extract the first author surname from a fetched article payload."""
        authors_full = article.get("authors_full") or []
        if authors_full and isinstance(authors_full[0], dict):
            last_name = authors_full[0].get("last_name")
            if isinstance(last_name, str) and last_name:
                return last_name

        authors = article.get("authors") or []
        if authors:
            return str(authors[0]).split(" ", 1)[0]
        return ""
