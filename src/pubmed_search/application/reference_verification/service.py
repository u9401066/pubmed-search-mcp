"""Reference-list verification service.

Design goals:
    - Accept plain-text reference lists passed from an MCP client.
    - Reuse existing PubMed evidence paths first: explicit PMID, DOI search,
      ECitMatch, then year-tolerant title and author/journal/locator searches.
    - Return structured evidence instead of a black-box yes/no verdict,
      including field-level corrections when a real record was mis-cited.

This is intentionally the first-stage implementation for reference-list
verification only. It does not attempt to extract references from arbitrary
full manuscripts yet.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.services.publication_integrity import STATUS_CORRECTED, assess_integrity
from pubmed_search.shared.article_identity import normalize_article_doi
from pubmed_search.shared.bounded_tasks import BoundedTaskSupervisor

from .matching import (
    AMBIGUITY_SCORE_MARGIN,
    MIN_CORROBORATING_FIELDS,
    IdentityEvidence,
    article_first_author,
    build_comparison,
    build_corrections,
    correction_blocker,
    identity_evidence,
    score_candidate,
    search_candidate_rejection,
)
from .parsing import REFERENCE_MARKER_RE, ParsedReference, fold_ascii, parse_reference_text
from .queries import metadata_query, safe_phrase, title_word_query

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

ReferenceStatus = Literal[
    "verified",
    "partial_match",
    "unresolved",
    "invalid_input",
    "source_unavailable",
    "not_checked",
]
ResolutionMethod = Literal["pmid", "doi_search", "ecitmatch", "title_search", "metadata_search"]

MAX_REFERENCE_TEXT_CHARS = 200_000
MAX_REFERENCE_TEXT_BYTES = 400_000
MAX_REFERENCE_CHARS = 4_000
MAX_REFERENCE_BYTES = 8_000
MAX_SOURCE_NAME_CHARS = 255
MAX_SOURCE_NAME_BYTES = 512
MAX_REFERENCES = 200
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0
SEARCH_CANDIDATE_LIMIT = 10
MAX_ALTERNATIVE_NOTES = 3
_T = TypeVar("_T")

_UNSAFE_SOURCE_NAME_RE = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_UNSAFE_REFERENCE_TEXT_RE = re.compile(r"[\x00\u202a-\u202e\u2066-\u2069]")
_ECITMATCH_UNSAFE_RE = re.compile(r"[|\r\n\t]")

_STRATEGY_LABELS: dict[str, str] = {
    "pmid": "explicit PMID lookup",
    "doi_search": "DOI search",
    "ecitmatch": "NCBI citation match (ECitMatch)",
    "title_search": "title-word search without a year restriction",
    "metadata_search": "first-author + journal + volume/first-page search without a year restriction",
}
_STRATEGY_REQUIREMENTS: dict[str, str] = {
    "ecitmatch": "needs a journal and year",
    "title_search": "needs a parsed title with at least two distinctive words",
    "metadata_search": "needs a first author, journal, and volume or first page",
}
# What each strategy matched by construction, in correction-withholding notes.
_LOOKUP_KEY_LABELS: dict[str, str] = {
    "pmid": "cited PMID",
    "doi_search": "cited DOI",
    "ecitmatch": "journal and year matched by ECitMatch",
    "title_search": "title words it was found by",
    "metadata_search": "first author, journal and volume/first page it was found by",
}


class ReferenceVerificationInputError(ValueError):
    """Raised when a reference-verification request exceeds a hard boundary."""


@dataclass(frozen=True, slots=True)
class _SearchSelection:
    """Best accepted year-tolerant search hit plus context for review notes."""

    article: dict[str, Any] | None = None
    alternatives: tuple[dict[str, Any], ...] = ()
    ambiguous: bool = False
    rejected_article: dict[str, Any] | None = None
    rejected_reason: str = ""


@dataclass(frozen=True, slots=True)
class _IdentifierCheck:
    """A cited PMID/DOI whose PubMed record the other cited fields do not corroborate.

    The identifier is only the lookup key, so its own match proves nothing
    about the citation. When no other cited field agrees, the identifier is
    probably wrong (a typo or a fabricated reference).
    """

    method: Literal["pmid", "doi_search"]
    article: dict[str, Any]
    evidence: IdentityEvidence

    @property
    def field(self) -> Literal["pmid", "doi"]:
        """Cited identifier field that was looked up."""
        return "pmid" if self.method == "pmid" else "doi"

    @property
    def probably_wrong(self) -> bool:
        """Whether every other comparable cited field contradicts the record."""
        return not self.evidence.agreeing


@dataclass(frozen=True, slots=True)
class _ResolutionOutcome:
    """Internal resolution result that preserves upstream availability."""

    article: dict[str, Any] | None
    method: ResolutionMethod | None
    unavailable_sources: tuple[str, ...] = ()
    attempted: tuple[ResolutionMethod, ...] = ()
    skipped: tuple[ResolutionMethod, ...] = ()
    selection: _SearchSelection | None = None
    identifier_check: _IdentifierCheck | None = None


class ReferenceVerificationService:
    """Verify reference-list entries against PubMed evidence.

    The service uses existing infrastructure already present in the repository:
    explicit PMID lookup, DOI-based PubMed search, ECitMatch, then title and
    first-author/journal/locator searches that do not pin the cited year, so a
    real but mis-cited record can be found and its differing fields reported as
    corrections. Results are returned with field-level evidence rather than a
    binary pass/fail only.

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
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or not 1 <= max_concurrency <= MAX_REFERENCES
        ):
            raise ReferenceVerificationInputError(f"max_concurrency must be between 1 and {MAX_REFERENCES}")
        if (
            isinstance(total_timeout_seconds, bool)
            or not isinstance(total_timeout_seconds, (int, float))
            or not math.isfinite(total_timeout_seconds)
            or total_timeout_seconds <= 0
        ):
            raise ReferenceVerificationInputError("total_timeout_seconds must be finite and greater than zero")
        self._searcher = searcher
        self._max_concurrency = max_concurrency
        self._total_timeout_seconds = total_timeout_seconds
        self._task_supervisor = BoundedTaskSupervisor(max_pending=MAX_REFERENCES * 2)

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
        entries = self._split_references(reference_text)[:limit]
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
        return parse_reference_text(reference_text, index=index)

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
            prefetched_citation_pmids = await self._await_owned(
                self._prefetch_citation_matches(parsed_entries),
                timeout=self._remaining_seconds(deadline),
            )
            prefetched_articles = await self._await_owned(
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
        tasks: dict[asyncio.Future[Any], ParsedReference] = {}
        if not timed_out:
            semaphore = asyncio.Semaphore(self._max_concurrency)
            for parsed in parsed_entries:
                task = self._task_supervisor.schedule(
                    self._verify_with_semaphore(
                        parsed,
                        semaphore=semaphore,
                        prefetched_citation_pmid=prefetched_citation_pmids.get(parsed.index),
                        article_cache=prefetched_articles,
                    )
                )
                if task is None:
                    results_by_index[parsed.index] = self._not_checked_row(
                        parsed, reason="Verification task capacity was exhausted"
                    )
                else:
                    tasks[task] = parsed

            try:
                done, pending = (
                    await asyncio.wait(tasks, timeout=max(0.0, deadline - loop.time())) if tasks else (set(), set())
                )
                timed_out = bool(pending)
                for task in done:
                    parsed = tasks[task]
                    if task.cancelled():
                        results_by_index[parsed.index] = self._source_unavailable_row(parsed, ("PubMed verification",))
                        continue
                    try:
                        results_by_index[parsed.index] = task.result()
                    except Exception:
                        results_by_index[parsed.index] = self._source_unavailable_row(parsed, ("PubMed verification",))
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                # The shared supervisor retains and reaps cancellation-resistant work.
                await asyncio.sleep(0)

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
        integrity_alerts = [
            {
                "index": row["index"],
                "pmid": (row.get("matched_article") or {}).get("pmid", ""),
                "status": row["integrity"]["status"],
                "notices": row["integrity"]["notices"],
            }
            for row in results
            if isinstance(row.get("integrity"), dict)
            and (row["integrity"].get("caution") or row["integrity"].get("status") == STATUS_CORRECTED)
        ]
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
            "integrity_alerts": integrity_alerts,
            "results": results,
            "review_workflow": review_workflow,
            "next_steps": [
                "Report integrity_alerts (retractions, expressions of concern, errata) to the user first",
                "Review partial_match rows for field-level mismatches",
                "Apply a row's corrections only after confirming matched_article is the intended work",
                "Retry source_unavailable and not_checked rows before treating them as unresolved",
                "Review unresolved rows for non-PubMed citations or parser misses before calling them fabricated",
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
            return await self._await_owned(
                self._verify_parsed_reference(parsed),
                timeout=self._total_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return self._not_checked_row(
                parsed,
                reason="The reference verification time budget was exhausted",
            )

    async def _await_owned(self, awaitable: Awaitable[_T], *, timeout: float) -> _T:
        """Bound the response deadline while retaining unfinished provider work."""
        task = self._task_supervisor.schedule(awaitable)
        if task is None:
            raise asyncio.TimeoutError("Verification task capacity was exhausted")
        try:
            done, _pending = await asyncio.wait({task}, timeout=max(0.0, timeout))
            if not done:
                raise asyncio.TimeoutError
            return cast("_T", task.result())
        finally:
            if not task.done():
                task.cancel()
                await asyncio.sleep(0)

    async def _verify_parsed_reference(
        self,
        parsed: ParsedReference,
        *,
        prefetched_citation_pmid: str | None = None,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Verify one parsed reference, optionally reusing batch-prefetched data.

        ``prefetched_citation_pmid`` is ``None`` when the batch ECitMatch did not
        cover this row, ``""`` when it ran without a match, or the matched PMID.
        """
        if not parsed.cleaned_text:
            return {
                "index": parsed.index,
                "status": "invalid_input",
                "resolution_method": None,
                "attempted_strategies": [],
                "input_reference": parsed.raw_text,
                "parsed_reference": parsed.to_dict(),
                "matched_article": None,
                "comparison": {},
                "matched_fields": [],
                "mismatched_fields": [],
                "corrections": [],
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
            row = self._source_unavailable_row(parsed, outcome.unavailable_sources, attempted=outcome.attempted)
            if outcome.identifier_check is not None:
                row["notes"].insert(0, self._identifier_note(parsed, outcome))
                row["identifier_assessment"] = self._identifier_assessment(parsed, outcome)
            return row

        article = outcome.article
        method = outcome.method
        comparison = build_comparison(parsed, article)
        matched_fields = [field for field, matched in comparison.items() if matched is True]
        mismatched_fields = [field for field, matched in comparison.items() if matched is False]
        status = self._determine_status(parsed, article, comparison)
        corrections, withheld_reason = self._corrections_for(parsed, outcome, comparison, status)

        notes = self._build_notes(
            parsed,
            outcome,
            status,
            matched_fields,
            mismatched_fields,
            corrections=corrections,
            withheld_reason=withheld_reason,
        )
        review_required = status in {"partial_match", "unresolved"}
        review_strategy = self._build_retry_strategy(parsed, method=method, status=status)
        result: dict[str, Any] = {
            "index": parsed.index,
            "status": status,
            "resolution_method": method,
            "attempted_strategies": list(outcome.attempted),
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": self._serialize_article(article),
            "comparison": comparison,
            "matched_fields": matched_fields,
            "mismatched_fields": mismatched_fields,
            "corrections": corrections,
            "notes": notes,
            "review_required": review_required,
            "review_strategy": review_strategy,
        }
        if withheld_reason:
            result["corrections_withheld_reason"] = withheld_reason
        integrity = assess_integrity([("pubmed", article or {})])
        result["integrity"] = integrity.to_dict()
        if integrity.caution:
            notes.insert(
                0,
                f"Cited work is flagged {integrity.status.replace('_', ' ')} in PubMed; "
                "do not cite it as valid evidence without disclosing the notice",
            )
        elif integrity.is_notice:
            notes.insert(0, "Matched record is a published notice (erratum or retraction), not the original article")
        if outcome.identifier_check is not None:
            result["identifier_assessment"] = self._identifier_assessment(parsed, outcome)
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
        *,
        attempted: tuple[ResolutionMethod, ...] = (),
    ) -> dict[str, Any]:
        """Build a row that cannot be adjudicated because evidence sources failed."""
        unique_sources = tuple(dict.fromkeys(source for source in sources if source))
        return {
            "index": parsed.index,
            "status": "source_unavailable",
            "resolution_method": None,
            "attempted_strategies": list(attempted),
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": None,
            "comparison": {},
            "matched_fields": [],
            "mismatched_fields": [],
            "corrections": [],
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
            "attempted_strategies": [],
            "input_reference": parsed.raw_text,
            "parsed_reference": parsed.to_dict(),
            "matched_article": None,
            "comparison": {},
            "matched_fields": [],
            "mismatched_fields": [],
            "corrections": [],
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
        if _UNSAFE_REFERENCE_TEXT_RE.search(reference_text):
            raise ReferenceVerificationInputError(
                f"reference entry {index} contains forbidden NUL or bidi override characters"
            )
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
        if not any(REFERENCE_MARKER_RE.match(line) for line in normalized_lines):
            return normalized_lines

        entries: list[str] = []
        current: list[str] = []
        for line in normalized_lines:
            if REFERENCE_MARKER_RE.match(line):
                if current:
                    entries.append(" ".join(current).strip())
                current = [REFERENCE_MARKER_RE.sub("", line, count=1).strip()]
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
        assessment = row.get("identifier_assessment") or {}
        if status == "unresolved" and assessment.get("assessment") == "probably_wrong":
            label = str(assessment.get("field", "")).upper()
            return (
                f"Cited {label} {assessment.get('cited', '')} is probably wrong: its PubMed record disagrees with "
                "every other comparable cited field and no other strategy found the cited work"
            )
        if status == "unresolved":
            if parsed.get("doi"):
                return "DOI present but unresolved; verify DOI transcription and index coverage"
            if parsed.get("title"):
                return (
                    "No PubMed record found by citation match, year-tolerant title search, or "
                    "author/journal/locator search; check non-PubMed indexes and parsed fields"
                )
            return "Insufficient structured fields; manually inspect author/journal/year extraction"
        corrections = row.get("corrections") or []
        pmid = (row.get("matched_article") or {}).get("pmid", "")
        if corrections:
            changes = ", ".join(f"{item['field']} ({item['cited']} -> {item['pubmed']})" for item in corrections)
            return f"Cited fields differ from PubMed PMID {pmid}: {changes}"
        if withheld_reason := row.get("corrections_withheld_reason"):
            return f"PubMed PMID {pmid} is a candidate, but no corrections are proposed: {withheld_reason}"
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
            safe_title = safe_phrase(parsed.title)
            retry_queries.append(
                {
                    "label": "title_exact",
                    "query": f'"{safe_title}"[Title]',
                    "purpose": "Exact-title recheck",
                }
            )
            title_words = title_word_query(parsed.title)
            if title_words:
                retry_queries.append(
                    {
                        "label": "title_words",
                        "query": title_words,
                        "purpose": "Year-tolerant title-word search (stopwords removed, spelling variants OR-ed)",
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
        locator_query = metadata_query(parsed)
        if locator_query:
            retry_queries.append(
                {
                    "label": "author_journal_locator",
                    "query": locator_query,
                    "purpose": "Year-tolerant first-author + journal + volume/first-page lookup",
                }
            )

        review_checklist = [
            "Confirm author surname, journal abbreviation, and year were parsed correctly",
            "Run retry queries in order until one yields a convincing candidate",
            "Accept only when at least two cited fields besides the DOI/PMID agree with its record, or when "
            "year+journal plus one field (page/author/volume) agree",
            "Document acceptance/rejection rationale for each unresolved reference",
        ]
        if method in {"title_search", "metadata_search"}:
            review_checklist.insert(
                1,
                "Search candidates found without the cited year are weaker evidence; confirm the record "
                "is the intended work before applying corrections",
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
        """Resolve one parsed reference to the best PubMed article candidate.

        Order: explicit PMID, exact DOI, ECitMatch, then two searches that do
        not pin the cited year (title words; first author + journal + volume or
        first page). A wrong year is the most common citation error, so the
        year-tolerant searches let a real but mis-cited record be found and
        reported with field-level corrections instead of looking fabricated.

        A cited PMID/DOI is only a lookup key. When the record it resolves to
        conflicts with the other cited fields and fewer than two of them agree,
        resolution continues; a later record replaces it only when that record
        is itself anchored strongly enough to correct the citation. Otherwise
        the identifier record is kept for review (one agreeing field) or the
        row is unresolved with the identifier reported as probably wrong (no
        agreeing field).
        """
        unavailable_sources: list[str] = []
        attempted: list[ResolutionMethod] = []
        skipped: list[ResolutionMethod] = []
        identifier_check: _IdentifierCheck | None = None

        def outcome(
            article: dict[str, Any] | None,
            method: ResolutionMethod | None,
            selection: _SearchSelection | None = None,
        ) -> _ResolutionOutcome:
            return _ResolutionOutcome(
                article,
                method,
                tuple(unavailable_sources),
                attempted=tuple(attempted),
                skipped=tuple(skipped),
                selection=selection,
                identifier_check=identifier_check,
            )

        def accepts(article: dict[str, Any], method: ResolutionMethod) -> bool:
            """Whether a later hit may stand in for an uncorroborated identifier record."""
            if identifier_check is None:
                return True
            if str(article.get("pmid") or "") == str(identifier_check.article.get("pmid") or ""):
                return False
            comparison = build_comparison(parsed, article)
            evidence = identity_evidence(parsed, article, comparison, method=method)
            return correction_blocker(parsed, article, comparison, evidence=evidence) is None

        identifier_lookups: list[tuple[Literal["pmid", "doi_search"], str]] = []
        if parsed.pmid:
            identifier_lookups.append(("pmid", "PubMed article details"))
        if parsed.doi:
            identifier_lookups.append(("doi_search", "PubMed DOI search"))
        for identifier_method, source_label in identifier_lookups:
            attempted.append(identifier_method)
            try:
                if identifier_method == "pmid":
                    article = await self._fetch_article_by_pmid(parsed.pmid, article_cache=article_cache)
                else:
                    article = await self._resolve_by_doi(parsed)
            except Exception:
                unavailable_sources.append(source_label)
                article = None
            if not article or not accepts(article, identifier_method):
                continue
            check = self._uncorroborated_identifier(parsed, article, identifier_method)
            if check is None:
                return outcome(article, identifier_method)
            identifier_check = identifier_check or check

        if parsed.journal and parsed.year:
            attempted.append("ecitmatch")
            try:
                article = await self._resolve_by_citation(
                    parsed,
                    prefetched_pmid=prefetched_citation_pmid,
                    article_cache=article_cache,
                )
            except Exception:
                unavailable_sources.append("NCBI ECitMatch")
                article = None
            if article and accepts(article, "ecitmatch"):
                return outcome(article, "ecitmatch")
        else:
            skipped.append("ecitmatch")

        found_by: dict[str, ResolutionMethod] = {}
        candidates: list[dict[str, Any]] = []
        selection = _SearchSelection()
        searches: tuple[tuple[ResolutionMethod, str | None, str], ...] = (
            ("title_search", title_word_query(parsed.title) if parsed.title else None, "PubMed title search"),
            ("metadata_search", metadata_query(parsed), "PubMed metadata search"),
        )
        for method, query, source_label in searches:
            if query is None:
                skipped.append(method)
                continue
            attempted.append(method)
            try:
                items = await self._search_candidates(query)
            except Exception:
                unavailable_sources.append(source_label)
                continue
            for item in items:
                pmid = str(item.get("pmid") or "").strip()
                if pmid not in found_by:
                    found_by[pmid] = method
                    candidates.append(item)
            selection = self._select_search_candidate(parsed, candidates)
            if selection.article is not None:
                chosen_pmid = str(selection.article.get("pmid") or "").strip()
                chosen_method = found_by.get(chosen_pmid, method)
                if accepts(selection.article, chosen_method):
                    return outcome(selection.article, chosen_method, selection)

        if identifier_check is not None and not identifier_check.probably_wrong:
            return outcome(identifier_check.article, identifier_check.method)
        return outcome(None, None, selection)

    @staticmethod
    def _uncorroborated_identifier(
        parsed: ParsedReference,
        article: dict[str, Any],
        method: Literal["pmid", "doi_search"],
    ) -> _IdentifierCheck | None:
        """Flag an identifier record that conflicts with the citation and is not corroborated."""
        evidence = identity_evidence(parsed, article, build_comparison(parsed, article), method=method)
        if evidence.corroborated or not evidence.conflicting:
            return None
        return _IdentifierCheck(method, article, evidence)

    async def _resolve_by_doi(self, parsed: ParsedReference) -> dict[str, Any] | None:
        """Resolve by DOI using PubMed search results and exact DOI filtering."""
        page = await self._searcher.search_page(f'"{parsed.doi}"[AID]', limit=3)
        results = self._validated_search_items(page)
        exact_matches = [article for article in results if normalize_article_doi(article.get("doi")) == parsed.doi]
        return self._choose_best_candidate(parsed, exact_matches)

    async def _resolve_by_citation(
        self,
        parsed: ParsedReference,
        *,
        prefetched_pmid: str | None = None,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve by ECitMatch, reusing a batch result (including a batch miss) when present."""
        pmid = prefetched_pmid
        if pmid is None:
            pmid = await self._searcher.find_by_citation(**self._citation_payload(parsed))
        if not pmid:
            return None
        return await self._fetch_article_by_pmid(pmid, article_cache=article_cache)

    async def _search_candidates(self, query: str) -> list[dict[str, Any]]:
        """Run one bounded PubMed search without a publication-year filter."""
        page = await self._searcher.search_page(query, limit=SEARCH_CANDIDATE_LIMIT)
        return self._validated_search_items(page)

    @staticmethod
    def _citation_payload(parsed: ParsedReference) -> dict[str, str]:
        """Build ECitMatch fields; the pipe-delimited protocol needs ASCII-safe values."""

        def clean(value: str) -> str:
            return _ECITMATCH_UNSAFE_RE.sub(" ", value).strip()

        return {
            "journal": clean(parsed.journal),
            "year": clean(parsed.year),
            "volume": clean(parsed.volume),
            "first_page": clean(parsed.first_page),
            "author": clean(fold_ascii(parsed.first_author)),
            "title": clean(parsed.title),
        }

    async def _fetch_article_by_pmid(
        self,
        pmid: str,
        *,
        article_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one PubMed article and reject malformed source payloads."""
        if article_cache and pmid in article_cache:
            cached = article_cache[pmid]
            if str(cached.get("pmid") or "").strip() != pmid:
                raise RuntimeError("PubMed article cache returned an invalid article row")
            return cached

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
        """Batch-resolve citation-like references via the ECitMatch workflow.

        Returns ``{index: pmid}`` for matches and ``{index: ""}`` for rows the
        batch checked without a match, so those rows are not re-sent to
        ECitMatch individually. Rows missing from the mapping were not covered.
        """
        if not hasattr(self._searcher, "verify_references"):
            return {}

        ecitmatch_candidates = [
            parsed for parsed in parsed_entries if not parsed.pmid and not parsed.doi and parsed.journal and parsed.year
        ]
        if not ecitmatch_candidates:
            return {}

        payload = [self._citation_payload(parsed) for parsed in ecitmatch_candidates]
        try:
            matches = await self._searcher.verify_references(payload)
        except Exception:
            return {}

        if not isinstance(matches, list):
            return {}
        prefetched: dict[int, str] = {}
        for parsed, match in zip(ecitmatch_candidates, matches, strict=False):
            if not isinstance(match, dict):
                continue
            pmid = str(match.get("pmid", "") or "")
            verified = match.get("verified")
            if pmid and (verified is True or verified == "True"):
                prefetched[parsed.index] = pmid
            elif not pmid and (verified is False or verified == "False"):
                prefetched[parsed.index] = ""
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

        if not isinstance(details, list):
            return {}
        cache: dict[str, dict[str, Any]] = {}
        for article in details:
            if not isinstance(article, dict):
                continue
            pmid = str(article.get("pmid", "") or "")
            if pmid in pmids:
                cache[pmid] = article
        return cache

    def _choose_best_candidate(
        self, parsed: ParsedReference, candidates: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Choose the highest-scoring candidate from a small PubMed result set."""
        scored: list[tuple[float, dict[str, Any]]] = []
        for article in candidates:
            if not isinstance(article, dict) or not str(article.get("pmid") or "").strip():
                continue
            score = score_candidate(parsed, article, build_comparison(parsed, article))
            if score > 0:
                scored.append((score, article))

        if not scored:
            return None

        scored.sort(key=lambda row: row[0], reverse=True)
        return scored[0][1]

    def _select_search_candidate(self, parsed: ParsedReference, candidates: list[dict[str, Any]]) -> _SearchSelection:
        """Pick the best year-tolerant search hit that passes the identity gate.

        Ranking prefers the closest publication year, cited author order,
        volume/page/issue agreement, and title similarity, so an updated
        version of a review (same title, newer year) beats an older one when
        the cited year is closer to it.
        """
        accepted: list[tuple[float, int, dict[str, Any]]] = []
        rejected: list[tuple[float, int, dict[str, Any], str]] = []
        for position, article in enumerate(candidates):
            comparison = build_comparison(parsed, article)
            score = score_candidate(parsed, article, comparison)
            reason = search_candidate_rejection(parsed, article, comparison)
            if reason is None:
                accepted.append((score, position, article))
            else:
                rejected.append((score, position, article, reason))

        if not accepted:
            if not rejected:
                return _SearchSelection()
            _score, _position, closest, reason = min(rejected, key=lambda row: (-row[0], row[1]))
            return _SearchSelection(rejected_article=closest, rejected_reason=reason)

        accepted.sort(key=lambda row: (-row[0], row[1]))
        best_score, _position, best = accepted[0]
        ambiguous = len(accepted) > 1 and best_score - accepted[1][0] < AMBIGUITY_SCORE_MARGIN
        return _SearchSelection(
            article=best,
            alternatives=tuple(article for _score, _position, article in accepted[1:]),
            ambiguous=ambiguous,
        )

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

        mismatches = [field for field, matched in comparison.items() if matched is False]
        matched_fields = [field for field, matched in comparison.items() if matched is True]

        if mismatches:
            return "partial_match" if matched_fields else "unresolved"

        if comparison.get("doi") is True or comparison.get("pmid") is True:
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

        if matched_fields:
            return "partial_match"

        return "unresolved"

    @staticmethod
    def _corrections_for(
        parsed: ParsedReference,
        outcome: _ResolutionOutcome,
        comparison: dict[str, bool | None],
        status: ReferenceStatus,
    ) -> tuple[list[dict[str, str]], str]:
        """Return field corrections, or the reason they were withheld."""
        article = outcome.article
        if article is None or status != "partial_match":
            return [], ""
        if not any(matched is False for matched in comparison.values()):
            return [], ""
        pmid = article.get("pmid", "")
        evidence = identity_evidence(parsed, article, comparison, method=outcome.method)
        blocker = correction_blocker(parsed, article, comparison, evidence=evidence)
        if blocker == "title_conflict":
            return [], (
                f"the cited title does not match PMID {pmid}; the identifier or locator may point to a different work"
            )
        if blocker == "few_locators":
            return [], "too few cited fields agree with the PubMed record to confirm it is the cited work"
        if blocker == "weak_corroboration":
            return [], ReferenceVerificationService._weak_corroboration_reason(evidence, pmid, outcome.method)
        if outcome.selection is not None and outcome.selection.ambiguous:
            return [], "several PubMed records match about equally well; confirm which one is intended"
        return build_corrections(parsed, article, comparison), ""

    @staticmethod
    def _weak_corroboration_reason(evidence: IdentityEvidence, pmid: object, method: ResolutionMethod | None) -> str:
        """Explain that too few independent fields corroborate the record to correct the citation."""
        key = _LOOKUP_KEY_LABELS.get(method or "", "lookup key")
        if evidence.agreeing:
            agreeing = ", ".join(evidence.agreeing)
            verb = "agrees" if len(evidence.agreeing) == 1 else "agree"
            found = f"only {agreeing} {verb} with PMID {pmid} besides the {key}"
        else:
            found = f"no cited field agrees with PMID {pmid} besides the {key}"
        disagreeing = f" ({', '.join(evidence.conflicting)} differ)" if evidence.conflicting else ""
        return (
            f"{found}{disagreeing}; at least {MIN_CORROBORATING_FIELDS} independent cited fields must agree "
            "before corrections are proposed, so confirm this is the cited work rather than a different paper"
        )

    def _build_notes(
        self,
        parsed: ParsedReference,
        outcome: _ResolutionOutcome,
        status: ReferenceStatus,
        matched_fields: list[str],
        mismatched_fields: list[str],
        *,
        corrections: list[dict[str, str]],
        withheld_reason: str,
    ) -> list[str]:
        """Build concise evidence notes for one verification row."""
        article = outcome.article
        notes: list[str] = []
        if outcome.method:
            notes.append(f"Resolved via {outcome.method}")
        if outcome.identifier_check is not None:
            notes.append(self._identifier_note(parsed, outcome))
        if article is None:
            notes.extend(self._unresolved_notes(parsed, outcome))
            return notes

        if status == "verified":
            notes.append("PubMed bibliographic evidence matches this reference; claim support has not been assessed")
        elif status == "partial_match":
            notes.append("A PubMed candidate was found, but bibliographic evidence is insufficient or conflicting")
        else:
            notes.append("A PubMed candidate was found, but evidence is too weak to verify")

        if matched_fields:
            notes.append(f"Matched fields: {', '.join(matched_fields)}")
        if mismatched_fields:
            notes.append(f"Mismatched fields: {', '.join(mismatched_fields)}")
        if corrections:
            doi = str(article.get("doi") or "")
            record = f"PMID {article.get('pmid', '')}" + (f" (DOI {doi})" if doi else "")
            changes = "; ".join(f"{item['field']} {item['cited']} -> {item['pubmed']}" for item in corrections)
            notes.append(f"Cited fields differ from PubMed {record}: {changes}")
        elif withheld_reason:
            notes.append(f"No field corrections proposed: {withheld_reason}")

        selection = outcome.selection
        if selection is not None and selection.alternatives:
            others = ", ".join(
                f"PMID {alternative.get('pmid', '')} ({alternative.get('year', '') or 'year unknown'})"
                for alternative in selection.alternatives[:MAX_ALTERNATIVE_NOTES]
            )
            notes.append(f"Other PubMed records with a matching title: {others}")
        return notes

    @staticmethod
    def _unresolved_notes(parsed: ParsedReference, outcome: _ResolutionOutcome) -> list[str]:
        """Explain what was tried for a row with no accepted PubMed record."""
        if not outcome.attempted:
            return ["Insufficient structured metadata for PubMed resolution"]
        notes: list[str] = []
        identifier_field = outcome.identifier_check.field if outcome.identifier_check is not None else ""
        if parsed.doi and "doi_search" in outcome.attempted and identifier_field != "doi":
            notes.append("No PubMed candidate resolved from the provided DOI")
        tried = "; ".join(_STRATEGY_LABELS[method] for method in outcome.attempted)
        notes.append(f"No PubMed record was found after: {tried}")
        not_run = [
            f"{_STRATEGY_LABELS[method]} ({_STRATEGY_REQUIREMENTS[method]})"
            for method in outcome.skipped
            if method in _STRATEGY_REQUIREMENTS
        ]
        if not_run:
            notes.append(f"Not attempted because the parsed reference lacks fields: {'; '.join(not_run)}")
        selection = outcome.selection
        if selection is not None and selection.article is not None:
            notes.append(
                f"PubMed search hit PMID {selection.article.get('pmid', '')} was not reported instead because "
                "too few cited fields corroborate it either"
            )
        elif selection is not None and selection.rejected_article is not None:
            rejected = selection.rejected_article
            notes.append(
                f"Closest PubMed search hit PMID {rejected.get('pmid', '')} was not accepted because "
                f"{selection.rejected_reason}"
            )
        notes.append(
            "Absence from PubMed does not by itself prove the reference is fabricated; check the DOI, "
            "publisher site, or non-PubMed indexes before rejecting it"
        )
        return notes

    @staticmethod
    def _replacement_pmid(outcome: _ResolutionOutcome) -> str:
        """PMID reported instead of an uncorroborated identifier record, or ``""``."""
        check, article = outcome.identifier_check, outcome.article
        if check is None or article is None:
            return ""
        pmid = str(article.get("pmid") or "")
        return "" if pmid == str(check.article.get("pmid") or "") else pmid

    def _identifier_assessment(self, parsed: ParsedReference, outcome: _ResolutionOutcome) -> dict[str, Any]:
        """Structured evidence for a cited identifier that the other cited fields do not corroborate."""
        check = outcome.identifier_check
        if check is None:
            return {}
        return {
            "field": check.field,
            "cited": getattr(parsed, check.field),
            "assessment": "probably_wrong" if check.probably_wrong else "weakly_corroborated",
            "agreeing_fields": list(check.evidence.agreeing),
            "conflicting_fields": list(check.evidence.conflicting),
            "resolved_article": self._serialize_article(check.article),
            "replaced_by_pmid": self._replacement_pmid(outcome) or None,
        }

    def _identifier_note(self, parsed: ParsedReference, outcome: _ResolutionOutcome) -> str:
        """Explain why a cited identifier did not settle the row."""
        check = outcome.identifier_check
        if check is None:
            return ""
        label = check.field.upper()
        record = check.article
        journal = str(record.get("journal_abbrev") or record.get("journal") or "")
        where = " ".join(part for part in (journal, str(record.get("year") or "")) if part)
        resolved = f"PMID {record.get('pmid', '')}" + (f" ({where})" if where else "")
        conflicting = ", ".join(check.evidence.conflicting)
        if check.probably_wrong:
            finding = (
                f"The cited {label} {getattr(parsed, check.field)} resolves to {resolved}, which disagrees with "
                f"every other comparable cited field ({conflicting}); the {label} is probably wrong"
            )
        else:
            finding = (
                f"The cited {label} {getattr(parsed, check.field)} resolves to {resolved}, which agrees only on "
                f"{', '.join(check.evidence.agreeing)} and disagrees on {conflicting}; the {label} may be wrong"
            )
        if replacement := self._replacement_pmid(outcome):
            return (
                f"{finding}; PMID {replacement} found via {outcome.method} is corroborated by the other cited "
                "fields and is reported instead"
            )
        return f"{finding}; no other resolution strategy found a better-corroborated record"

    @staticmethod
    def _serialize_article(article: dict[str, Any] | None) -> dict[str, Any] | None:
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
            "issue": article.get("issue", ""),
            "pages": article.get("pages", ""),
            "first_author": article_first_author(article),
        }
