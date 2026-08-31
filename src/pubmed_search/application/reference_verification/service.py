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

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.shared.article_identity import normalize_article_doi, normalize_article_title

if TYPE_CHECKING:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

ReferenceStatus = Literal[
    "verified",
    "partial_match",
    "unresolved",
    "invalid_input",
    "source_unavailable",
    "not_checked",
]
ResolutionMethod = Literal["pmid", "doi_search", "ecitmatch", "title_search"]

MAX_REFERENCE_TEXT_CHARS = 200_000
MAX_REFERENCE_TEXT_BYTES = 400_000
MAX_REFERENCE_CHARS = 4_000
MAX_REFERENCE_BYTES = 8_000
MAX_SOURCE_NAME_CHARS = 255
MAX_SOURCE_NAME_BYTES = 512
MAX_REFERENCES = 200
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0

_REFERENCE_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s*")
_DOI_RE = re.compile(r"\b(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{5,9})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_FIRST_PAGE_RE = re.compile(r":\s*([A-Za-z]?\d+)")
_VOLUME_RE = re.compile(r";\s*([A-Za-z0-9][A-Za-z0-9 .-]{0,20}?)(?:\(|:|;)")
_UNSAFE_SOURCE_NAME_RE = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_UNSAFE_REFERENCE_TEXT_RE = re.compile(r"[\x00\u202a-\u202e\u2066-\u2069]")


class ReferenceVerificationInputError(ValueError):
    """Raised when a reference-verification request exceeds a hard boundary."""


@dataclass(frozen=True, slots=True)
class _ResolutionOutcome:
    """Internal resolution result that preserves upstream availability."""

    article: dict[str, Any] | None
    method: ResolutionMethod | None
    unavailable_sources: tuple[str, ...] = ()


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

    def __init__(
        self,
        searcher: LiteratureSearcher,
        *,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ):
        if not 1 <= max_concurrency <= MAX_REFERENCES:
            raise ReferenceVerificationInputError(f"max_concurrency must be between 1 and {MAX_REFERENCES}")
        if total_timeout_seconds <= 0:
            raise ReferenceVerificationInputError("total_timeout_seconds must be greater than zero")
        self._searcher = searcher
        self._max_concurrency = max_concurrency
        self._total_timeout_seconds = total_timeout_seconds

    def extract_references(self, reference_text: str, *, limit: int = 100) -> list[str]:
        """Split a plain-text reference block into individual entries.

        Args:
            reference_text: Plain text containing one reference list.
            limit: Maximum number of extracted entries to return.

        Returns:
            List of reference entry strings, preserving original order.
        """
        self._validate_limit(limit)
        self._validate_reference_text(reference_text)
        normalized_lines = [line.strip() for line in reference_text.splitlines() if line.strip()]
        if not normalized_lines:
            return []

        has_numbered_entries = any(_REFERENCE_MARKER_RE.match(line) for line in normalized_lines)
        if not has_numbered_entries:
            limited_entries = normalized_lines[:limit]
            self._validate_entries(limited_entries)
            return limited_entries

        entries: list[str] = []
        current: list[str] = []
        for line in normalized_lines:
            if _REFERENCE_MARKER_RE.match(line):
                if current:
                    entries.append(" ".join(current).strip())
                    if len(entries) >= limit:
                        self._validate_entries(entries)
                        return entries
                current = [_REFERENCE_MARKER_RE.sub("", line, count=1).strip()]
                continue
            current.append(line)

        if current and len(entries) < limit:
            entries.append(" ".join(current).strip())

        entries = entries[:limit]
        self._validate_entries(entries)
        return entries

    def parse_reference(self, reference_text: str, *, index: int) -> ParsedReference:
        """Extract minimal verification fields from one reference entry.

        Args:
            reference_text: One reference string.
            index: 1-based position in the input list.

        Returns:
            ParsedReference containing heuristically extracted fields.
        """
        self._validate_reference_entry(reference_text, index=index)
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
        self._validate_request(reference_text, source_name=source_name, limit=limit)
        entries = self._split_references(reference_text)
        if not entries:
            return {
                "success": False,
                "status": "invalid_input",
                "partial": False,
                "mode": "reference_list_verification",
                "source_name": source_name.strip(),
                "reference_count": 0,
                "assessed_count": 0,
                "not_assessed_count": 0,
                "timed_out": False,
                "degraded_sources": [],
                "summary": {
                    "verified": 0,
                    "partial_match": 0,
                    "unresolved": 0,
                    "invalid_input": 0,
                    "source_unavailable": 0,
                    "not_checked": 0,
                },
                "results": [],
                "error": "No reference entries found",
                "hint": "Provide one reference per line or a numbered reference list",
            }

        if len(entries) > limit:
            raise ReferenceVerificationInputError(f"reference_text contains more than max_references ({limit}) entries")
        self._validate_entries(entries)

        parsed_entries = [self.parse_reference(entry, index=i) for i, entry in enumerate(entries, start=1)]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._total_timeout_seconds
        timed_out = False

        try:
            prefetched_citation_pmids = await asyncio.wait_for(
                self._prefetch_citation_matches(parsed_entries),
                timeout=self._remaining_seconds(deadline),
            )
            prefetched_articles = await asyncio.wait_for(
                self._prefetch_articles(
                    {
                        *{parsed.pmid for parsed in parsed_entries if parsed.pmid},
                        *{pmid for pmid in prefetched_citation_pmids.values() if pmid},
                    }
                ),
                timeout=self._remaining_seconds(deadline),
            )
        except asyncio.TimeoutError:
            prefetched_citation_pmids = {}
            prefetched_articles = {}
            timed_out = True

        results_by_index: dict[int, dict[str, Any]] = {}
        tasks: dict[asyncio.Task[dict[str, Any]], ParsedReference] = {}
        if not timed_out:
            semaphore = asyncio.Semaphore(self._max_concurrency)
            for parsed in parsed_entries:
                task = asyncio.create_task(
                    self._verify_with_semaphore(
                        parsed,
                        semaphore=semaphore,
                        prefetched_citation_pmid=prefetched_citation_pmids.get(parsed.index),
                        article_cache=prefetched_articles,
                    )
                )
                tasks[task] = parsed

            try:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=max(0.0, deadline - loop.time()),
                )
            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            timed_out = bool(pending)
            for task in done:
                parsed = tasks[task]
                try:
                    results_by_index[parsed.index] = task.result()
                except Exception:
                    results_by_index[parsed.index] = self._source_unavailable_row(
                        parsed,
                        ("PubMed verification",),
                    )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        for parsed in parsed_entries:
            if parsed.index not in results_by_index:
                results_by_index[parsed.index] = self._not_checked_row(
                    parsed,
                    reason="The reference-list verification time budget was exhausted",
                )

        results = [results_by_index[index] for index in sorted(results_by_index)]
        summary = {
            status: sum(1 for row in results if row["status"] == status)
            for status in (
                "verified",
                "partial_match",
                "unresolved",
                "invalid_input",
                "source_unavailable",
                "not_checked",
            )
        }
        degraded_sources = sorted(
            {
                source
                for row in results
                for item in [*(row.get("source_errors") or []), *(row.get("source_warnings") or [])]
                if isinstance(item, dict)
                for source in [str(item.get("source", ""))]
                if source
            }
        )
        unavailable_count = summary["source_unavailable"] + summary["not_checked"]
        assessed_count = len(results) - unavailable_count
        is_partial = bool(unavailable_count or degraded_sources)
        report_status = "ok"
        if assessed_count == 0:
            report_status = "timeout" if summary["not_checked"] else "source_unavailable"
        elif is_partial:
            report_status = "partial"
        review_workflow = self._build_review_workflow(results)
        return {
            "success": assessed_count > 0,
            "status": report_status,
            "partial": is_partial,
            "mode": "reference_list_verification",
            "source_name": source_name.strip(),
            "reference_count": len(results),
            "assessed_count": assessed_count,
            "not_assessed_count": unavailable_count,
            "timed_out": timed_out,
            "degraded_sources": degraded_sources,
            "summary": summary,
            "results": results,
            "review_workflow": review_workflow,
            "next_steps": [
                "Review partial_match rows for field-level mismatches",
                "Retry source_unavailable and not_checked rows before treating them as unresolved",
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
        self._validate_reference_entry(reference_text, index=index)
        parsed = self.parse_reference(reference_text, index=index)
        try:
            return await asyncio.wait_for(
                self._verify_parsed_reference(parsed),
                timeout=self._total_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return self._not_checked_row(
                parsed,
                reason="The reference verification time budget was exhausted",
            )

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
                "review_required": False,
                "review_strategy": {"retry_queries": [], "review_checklist": []},
            }

        outcome = await self._resolve_reference(
            parsed,
            prefetched_citation_pmid=prefetched_citation_pmid,
            article_cache=article_cache,
        )
        if outcome.article is None and outcome.unavailable_sources:
            return self._source_unavailable_row(parsed, outcome.unavailable_sources)

        article = outcome.article
        method = outcome.method
        comparison = self._build_comparison(parsed, article)
        matched_fields = [field for field, matched in comparison.items() if matched is True]
        mismatched_fields = [field for field, matched in comparison.items() if matched is False]
        status = self._determine_status(parsed, article, comparison)

        notes = self._build_notes(parsed, article, method, status, matched_fields, mismatched_fields)
        review_required = status in {"partial_match", "unresolved"}
        review_strategy = self._build_retry_strategy(parsed, method=method, status=status)
        result: dict[str, Any] = {
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
        if outcome.unavailable_sources:
            result["source_warnings"] = [
                {"source": source, "error": "upstream source unavailable"} for source in outcome.unavailable_sources
            ]
        return result

    async def _verify_with_semaphore(
        self,
        parsed: ParsedReference,
        *,
        semaphore: asyncio.Semaphore,
        prefetched_citation_pmid: str | None,
        article_cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Run one reference under the list-level concurrency cap."""
        async with semaphore:
            return await self._verify_parsed_reference(
                parsed,
                prefetched_citation_pmid=prefetched_citation_pmid,
                article_cache=article_cache,
            )

    def _source_unavailable_row(
        self,
        parsed: ParsedReference,
        sources: tuple[str, ...],
    ) -> dict[str, Any]:
        """Build a row that cannot be adjudicated because evidence sources failed."""
        unique_sources = tuple(dict.fromkeys(source for source in sources if source))
        return {
            "index": parsed.index,
            "status": "source_unavailable",
            "resolution_method": None,
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": None,
            "comparison": {},
            "matched_fields": [],
            "mismatched_fields": [],
            "notes": [
                "Verification could not be completed because an upstream evidence source was unavailable",
                "Retry this row before classifying it as unresolved",
            ],
            "source_errors": [{"source": source, "error": "upstream source unavailable"} for source in unique_sources],
            "review_required": True,
            "review_strategy": self._build_retry_strategy(
                parsed,
                method=None,
                status="source_unavailable",
            ),
        }

    def _not_checked_row(self, parsed: ParsedReference, *, reason: str) -> dict[str, Any]:
        """Build a deterministic row for work cancelled by the total time budget."""
        return {
            "index": parsed.index,
            "status": "not_checked",
            "resolution_method": None,
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": None,
            "comparison": {},
            "matched_fields": [],
            "mismatched_fields": [],
            "notes": [reason, "Retry this row before classifying it as unresolved"],
            "review_required": True,
            "review_strategy": self._build_retry_strategy(
                parsed,
                method=None,
                status="not_checked",
            ),
        }

    @staticmethod
    def _remaining_seconds(deadline: float) -> float:
        """Return the remaining positive operation budget for ``asyncio.wait_for``."""
        return max(0.0, deadline - asyncio.get_running_loop().time())

    def _validate_request(self, reference_text: str, *, source_name: str, limit: int) -> None:
        """Validate all list-level boundaries before parsing or network access."""
        self._validate_limit(limit)
        self._validate_reference_text(reference_text)
        if not isinstance(source_name, str):
            raise ReferenceVerificationInputError("source_name must be a string")
        if len(source_name) > MAX_SOURCE_NAME_CHARS:
            raise ReferenceVerificationInputError(f"source_name must not exceed {MAX_SOURCE_NAME_CHARS} characters")
        if len(source_name.encode("utf-8")) > MAX_SOURCE_NAME_BYTES:
            raise ReferenceVerificationInputError(f"source_name must not exceed {MAX_SOURCE_NAME_BYTES} UTF-8 bytes")
        if _UNSAFE_SOURCE_NAME_RE.search(source_name):
            raise ReferenceVerificationInputError(
                "source_name must be a single-line label without control or bidi override characters"
            )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Reject invalid or over-large reference-count limits."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_REFERENCES:
            raise ReferenceVerificationInputError(f"max_references must be an integer between 1 and {MAX_REFERENCES}")

    @staticmethod
    def _validate_reference_text(reference_text: str) -> None:
        """Enforce bounded, unambiguous text input before splitting."""
        if not isinstance(reference_text, str):
            raise ReferenceVerificationInputError("reference_text must be a string")
        if len(reference_text) > MAX_REFERENCE_TEXT_CHARS:
            raise ReferenceVerificationInputError(
                f"reference_text must not exceed {MAX_REFERENCE_TEXT_CHARS} characters"
            )
        if len(reference_text.encode("utf-8")) > MAX_REFERENCE_TEXT_BYTES:
            raise ReferenceVerificationInputError(
                f"reference_text must not exceed {MAX_REFERENCE_TEXT_BYTES} UTF-8 bytes"
            )
        if _UNSAFE_REFERENCE_TEXT_RE.search(reference_text):
            raise ReferenceVerificationInputError("reference_text contains forbidden NUL or bidi override characters")

    def _validate_entries(self, entries: list[str]) -> None:
        """Validate each extracted reference before parsing or upstream calls."""
        for index, entry in enumerate(entries, start=1):
            self._validate_reference_entry(entry, index=index)

    @staticmethod
    def _validate_reference_entry(reference_text: str, *, index: int) -> None:
        """Enforce per-reference size and index boundaries."""
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= MAX_REFERENCES:
            raise ReferenceVerificationInputError(f"reference index must be an integer between 1 and {MAX_REFERENCES}")
        if not isinstance(reference_text, str):
            raise ReferenceVerificationInputError(f"reference entry {index} must be a string")
        if len(reference_text) > MAX_REFERENCE_CHARS:
            raise ReferenceVerificationInputError(
                f"reference entry {index} must not exceed {MAX_REFERENCE_CHARS} characters"
            )
        if len(reference_text.encode("utf-8")) > MAX_REFERENCE_BYTES:
            raise ReferenceVerificationInputError(
                f"reference entry {index} must not exceed {MAX_REFERENCE_BYTES} UTF-8 bytes"
            )

    @staticmethod
    def _split_references(reference_text: str) -> list[str]:
        """Split every entry without silently truncating the caller's input."""
        normalized_lines = [line.strip() for line in reference_text.splitlines() if line.strip()]
        if not normalized_lines:
            return []
        if not any(_REFERENCE_MARKER_RE.match(line) for line in normalized_lines):
            return normalized_lines

        entries: list[str] = []
        current: list[str] = []
        for line in normalized_lines:
            if _REFERENCE_MARKER_RE.match(line):
                if current:
                    entries.append(" ".join(current).strip())
                current = [_REFERENCE_MARKER_RE.sub("", line, count=1).strip()]
            else:
                current.append(line)
        if current:
            entries.append(" ".join(current).strip())
        return entries

    @staticmethod
    def _validated_search_items(page: object) -> list[dict[str, Any]]:
        """Return article items from the sole typed PubMed page contract."""
        if not isinstance(page, SourceSearchPage) or page.source != "pubmed":
            raise TypeError("PubMed search returned an invalid page")
        if page.total is not None and (
            not isinstance(page.total, int) or isinstance(page.total, bool) or page.total < len(page.items)
        ):
            raise RuntimeError("PubMed search returned an invalid total")
        if any(not isinstance(item, dict) for item in page.items):
            raise RuntimeError("PubMed search returned an invalid article collection")
        results = [dict(item) for item in page.items]
        if any(not str(item.get("pmid") or "").strip() for item in results):
            raise RuntimeError("PubMed search returned an invalid article row")
        return results

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

        if status in {"source_unavailable", "not_checked"}:
            return "high"
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

        if status == "source_unavailable":
            return "An upstream PubMed evidence source was unavailable; retry before adjudication"
        if status == "not_checked":
            return "This reference was not checked before the operation time budget expired"
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
        if status not in {"partial_match", "unresolved", "source_unavailable", "not_checked"}:
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
            review_checklist.insert(
                1, "Title-search candidates are weak evidence; prefer DOI/PMID or citation metadata"
            )

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
    ) -> _ResolutionOutcome:
        """Resolve one parsed reference to the best PubMed article candidate."""
        unavailable_sources: list[str] = []
        if parsed.pmid:
            try:
                article = await self._fetch_article_by_pmid(parsed.pmid, article_cache=article_cache)
            except Exception:
                unavailable_sources.append("PubMed article details")
                article = None
            if article:
                return _ResolutionOutcome(article, "pmid", tuple(unavailable_sources))

        if parsed.doi:
            try:
                article = await self._resolve_by_doi(parsed)
            except Exception:
                unavailable_sources.append("PubMed DOI search")
                article = None
            if article:
                return _ResolutionOutcome(article, "doi_search", tuple(unavailable_sources))

        if parsed.journal and parsed.year:
            try:
                article = await self._resolve_by_citation(
                    parsed,
                    prefetched_pmid=prefetched_citation_pmid,
                    article_cache=article_cache,
                )
            except Exception:
                unavailable_sources.append("NCBI ECitMatch")
                article = None
            if article:
                return _ResolutionOutcome(article, "ecitmatch", tuple(unavailable_sources))

        if parsed.title:
            try:
                article = await self._resolve_by_title(parsed)
            except Exception:
                unavailable_sources.append("PubMed title search")
                article = None
            if article:
                return _ResolutionOutcome(article, "title_search", tuple(unavailable_sources))

        return _ResolutionOutcome(None, None, tuple(unavailable_sources))

    async def _resolve_by_doi(self, parsed: ParsedReference) -> dict[str, Any] | None:
        """Resolve by DOI using PubMed search results and exact DOI filtering."""
        page = await self._searcher.search_page(f'"{parsed.doi}"[AID]', limit=3)
        results = self._validated_search_items(page)
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
        page = await self._searcher.search_page(
            f'"{safe_title}"[Title]',
            limit=5,
            min_year=min_year,
            max_year=max_year,
        )
        results = self._validated_search_items(page)
        return self._choose_best_candidate(parsed, results)

    async def _fetch_article_by_pmid(
        self,
        pmid: str,
        *,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one PubMed article and reject malformed source payloads."""
        if article_cache and pmid in article_cache:
            return article_cache[pmid]

        details = await self._searcher.fetch_details([pmid])
        if not isinstance(details, list):
            raise TypeError("PubMed article details returned an invalid response")
        if not details:
            return None
        article = details[0]
        if not isinstance(article, dict):
            raise TypeError("PubMed article details returned an invalid response")
        if str(article.get("pmid") or "").strip() != pmid:
            raise RuntimeError("PubMed article details returned an invalid article row")
        return article

    async def _prefetch_citation_matches(self, parsed_entries: list[ParsedReference]) -> dict[int, str]:
        """Batch-resolve citation-like references via the ECitMatch workflow."""
        if not hasattr(self._searcher, "verify_references"):
            return {}

        ecitmatch_candidates = [
            parsed for parsed in parsed_entries if not parsed.pmid and not parsed.doi and parsed.journal and parsed.year
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
            if not isinstance(article, dict):
                continue
            pmid = str(article.get("pmid", "") or "")
            if pmid:
                cache[pmid] = article
        return cache

    def _choose_best_candidate(
        self, parsed: ParsedReference, candidates: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Choose the highest-scoring candidate from a small PubMed result set."""
        scored: list[tuple[int, dict[str, Any]]] = []
        for article in candidates:
            if not isinstance(article, dict) or not str(article.get("pmid") or "").strip():
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
            comparisons["volume"] = self._normalize_text(parsed.volume) == self._normalize_text(
                article.get("volume", "")
            )
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
