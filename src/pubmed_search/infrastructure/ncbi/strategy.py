"""
Search Strategy Module - Intelligent query generation using NCBI APIs.

Uses:
- ESpell for spelling correction
- MeSH database exact-term lookup (ESearch + ESummary) for descriptors and synonyms
- PubMed ESearch translation (automatic term mapping) as corroborating evidence
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from Bio import Entrez
from cachetools import TTLCache

from pubmed_search.domain.services.mesh_phrase_matching import (
    MeshRecord,
    RecordType,
    contains_phrase,
    lookup_variants,
    matches_for,
    parse_topic,
    resolve_matches,
    select_mappings,
    term_key,
)

from .base import (
    DEFAULT_ENTREZ_TOOL,
    NCBIInfrastructureError,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
    run_entrez_callable,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Retry settings for NCBI intermittent errors
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Exact MeSH lookups: one ESearch per batch of quoted term clauses, one ESummary.
MESH_LOOKUP_MAX_CLAUSES = 200
MESH_LOOKUP_RETMAX = 500
MESH_SUBSTANCE_MAX_TOKENS = 3
MESH_CACHE_TTL = 6 * 60 * 60
MESH_CACHE_SIZE = 4096

_ATM_VOCABULARY_TERM = re.compile(r'"([^"]+)"\[(?:MeSH Terms|Supplementary Concept)(?::noexp)?\]', re.IGNORECASE)


def _mesh_uids(result: Any) -> list[str]:
    """Validated UIDs from a db=mesh ESearch record; they are later comma-joined into ESummary."""
    uids = [str(uid) for uid in result.get("IdList", [])]
    if any(not uid.isascii() or not uid.isdecimal() for uid in uids):
        raise ValueError("Invalid MeSH identifiers")
    return uids


def _mesh_record_from_summary(summary: Any) -> MeshRecord | None:
    """Reduce one db=mesh ESummary document to a matchable record.

    Qualifier (subheading) and pharmacological-action records are skipped:
    they are not standalone PubMed MeSH Terms and would shadow descriptors.
    ``DS_Subheading`` lists the qualifiers allowed with a descriptor.
    """
    uid = str(summary["Id"])
    terms = [str(term).strip() for term in summary["DS_MeshTerms"] if str(term).strip()]
    qualifiers = [str(name).strip() for name in summary.get("DS_Subheading") or [] if str(name).strip()]
    if not uid.isascii() or not uid.isdecimal():
        raise ValueError("Invalid MeSH identifier")
    if not terms:
        return None
    trees = [str(link["TreeNum"]) for link in summary.get("DS_IdxLinks") or [] if link.get("TreeNum")]
    record_type: RecordType
    if summary.get("DS_HeadingMappedToList") or (trees and all(tree.startswith("@") for tree in trees)):
        record_type = "supplementary_concept"
    elif any(tree.startswith("Y") for tree in trees) or summary.get("DS_PaList"):
        return None
    elif trees and all(tree.startswith("V") for tree in trees):
        record_type = "publication_type"
    else:
        record_type = "descriptor"
    return MeshRecord(
        uid=uid,
        preferred=terms[0],
        entry_terms=tuple(dict.fromkeys(term for term in terms[1:] if term != terms[0])),
        tree_numbers=tuple(tree for tree in trees if not tree.startswith("@")),
        record_type=record_type,
        allowed_qualifiers=tuple(dict.fromkeys(qualifiers)) if record_type == "descriptor" else (),
    )


def _atm_proposals(translation_set: Any) -> list[tuple[str, tuple[str, ...]]]:
    """Extract (source phrase, vocabulary names) pairs from a PubMed TranslationSet."""
    if not isinstance(translation_set, list):
        return []
    proposals: list[tuple[str, tuple[str, ...]]] = []
    for item in translation_set:
        try:
            source = str(item["From"]).strip()
            names = tuple(dict.fromkeys(_ATM_VOCABULARY_TERM.findall(str(item["To"]))))
        except (KeyError, TypeError):
            continue
        if source and names:
            proposals.append((source, names))
    return proposals


async def _read_entrez_handle(handle: Any) -> Any:
    """Read an Entrez handle and close it even if parsing fails."""
    try:
        return await asyncio.to_thread(Entrez.read, handle)
    finally:
        handle.close()


async def _read_text_handle(handle: Any) -> str:
    """Read text from an Entrez handle and close it even on failure."""
    try:
        return await asyncio.to_thread(handle.read)
    finally:
        handle.close()


class SearchStrategyGenerator:
    """
    Generates intelligent search strategies using NCBI APIs.

    Features:
    - Spelling correction via ESpell
    - MeSH mapping accepted only on preferred-term or entry-term equality
    - Synonym expansion from confirmed MeSH records
    - Query translation analysis
    """

    def __init__(self, email: str, api_key: str | None = None):
        # NOTE: Entrez global state is not set here; run_entrez_callable() handles
        # per-call snapshot/set/restore under a threading lock.
        self._email = email
        self._api_key = api_key
        self._tool = DEFAULT_ENTREZ_TOOL
        # Public vocabulary only; keyed by term_key, negative results included.
        self._mesh_cache: TTLCache[str, tuple[MeshRecord, ...]] = TTLCache(maxsize=MESH_CACHE_SIZE, ttl=MESH_CACHE_TTL)

    async def _execute_entrez(self, operation, *, service_name: str, timeout: float = 45.0):
        return await execute_entrez_operation(
            operation,
            api_key=self._api_key,
            service_name=service_name,
            timeout=timeout,
            max_attempts=MAX_RETRIES,
            base_delay=RETRY_DELAY,
        )

    async def spell_check(self, query: str) -> tuple[str, bool]:
        """
        Check and correct spelling using NCBI ESpell.

        Returns:
            Tuple of (corrected_query, was_corrected)
        """

        async def _do_spell_check():
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.espell,
                db="pubmed",
                term=query,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            result = await self._execute_entrez(_do_spell_check, service_name="ncbi-strategy:espell")
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_spell_check", exc)

        try:
            corrected = result.get("CorrectedQuery", "")
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy spelling response", exc)
        if corrected and corrected != query:
            logger.info(
                "NCBI spelling correction applied (input_length=%s, output_length=%s)",
                len(query),
                len(corrected),
            )
            return corrected, True
        return query, False

    async def lookup_mesh_records(self, phrases: Iterable[str]) -> dict[str, tuple[MeshRecord, ...]]:
        """Find MeSH records holding a phrase as an exact term, keyed by ``term_key``.

        Each phrase is searched only as quoted MeSH Terms (descriptor headings and
        entry terms) plus, for short phrases, Substance Name; free-text MeSH
        searches are never issued because they match scope notes. Results,
        including empty ones, are cached per normalized key. All uncached
        phrases share batched ESearch requests and one ESummary request.
        """
        phrases = list(phrases)
        requested: dict[str, list[str]] = {}
        for phrase in phrases:
            key = term_key(phrase)
            if key and key not in self._mesh_cache:
                requested.setdefault(key, []).append(phrase)

        if requested:
            clauses: list[str] = []
            for group in requested.values():
                for phrase in dict.fromkeys(group):
                    clauses.extend(f'"{variant}"[MeSH Terms]' for variant in lookup_variants(phrase))
                    if len(phrase.split()) <= MESH_SUBSTANCE_MAX_TOKENS:
                        clauses.append(f'"{phrase}"[Substance Name]')
            unique_clauses = list(dict.fromkeys(clauses))
            uids: list[str] = []
            for offset in range(0, len(unique_clauses), MESH_LOOKUP_MAX_CLAUSES):
                batch = unique_clauses[offset : offset + MESH_LOOKUP_MAX_CLAUSES]
                uids.extend(await self._search_mesh_uids(" OR ".join(batch)))
            records = await self._fetch_mesh_records(list(dict.fromkeys(uids))) if uids else []
            for key in requested:
                self._mesh_cache[key] = tuple(record for record in records if key in record.term_keys)

        return {key: self._mesh_cache.get(key, ()) for key in (term_key(phrase) for phrase in phrases) if key}

    async def _search_mesh_uids(self, term: str) -> list[str]:
        async def _do_search() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="mesh",
                term=term,
                retmax=MESH_LOOKUP_RETMAX,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            result = await self._execute_entrez(_do_search, service_name="ncbi-strategy:mesh-esearch")
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_mesh_lookup", exc)
        try:
            return _mesh_uids(result)
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy MeSH search response", exc)

    async def _fetch_mesh_records(self, uids: list[str]) -> list[MeshRecord]:
        async def _do_summary() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esummary,
                db="mesh",
                id=",".join(uids),
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            summaries = await self._execute_entrez(
                _do_summary,
                service_name="ncbi-strategy:mesh-esummary",
                timeout=60.0,
            )
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_mesh_lookup", exc)
        try:
            return [record for summary in summaries if (record := _mesh_record_from_summary(summary)) is not None]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy MeSH summary response", exc)

    async def get_mesh_info(self, term: str) -> dict[str, Any] | None:
        """
        Get the MeSH record whose preferred term or entry term equals ``term``.

        Equality ignores case, punctuation/hyphen spacing and simple plurals.
        A record that merely mentions the words (for example in its scope note)
        is not returned, and neither is a phrase claimed by several records.

        Returns:
            Dict with mesh_id, preferred_term, synonyms, tree_numbers, record_type,
            search_field, matched_on and matched_term; None when no record matches.
        """
        records = await self.lookup_mesh_records([term])
        match = resolve_matches(matches_for(term, records.get(term_key(term), ())))
        if match is None:
            return None
        record = match.record
        return {
            "mesh_id": record.uid,
            "preferred_term": record.preferred,
            "synonyms": record.text_synonyms(10),
            "tree_numbers": list(record.tree_numbers),
            "record_type": record.record_type,
            "search_field": record.search_field,
            "matched_on": match.matched_on,
            "matched_term": match.matched_term,
        }

    async def _pubmed_mesh_proposals(self, topic: str) -> list[tuple[str, tuple[str, ...]]] | None:
        """PubMed automatic term mapping for the topic, or None when unavailable."""
        try:
            analysis = await self.analyze_query(topic)
        except NCBIInfrastructureError:
            return None
        return _atm_proposals(analysis.get("translation_set") if isinstance(analysis, dict) else None)

    async def _map_topic_to_mesh(self, topic: str) -> dict[str, Any]:
        """Confirmed MeSH mappings, review candidates and unmapped phrases for one topic."""
        phrases = parse_topic(topic)
        proposals = await self._pubmed_mesh_proposals(topic)
        atm_names = [name for _, names in proposals or [] for name in names]
        lookups = list(dict.fromkeys([candidate.text for candidate in phrases.candidates] + atm_names))
        mesh_coverage: dict[str, Any] = {
            "status": "completed",
            "attempted": int(bool(lookups)),
            "completed": int(bool(lookups)),
            "failed": 0,
            "matched": 0,
            "unconfirmed": 0,
            "phrases_checked": 0,
        }
        outcome: dict[str, Any] = {
            "mesh_terms": [],
            "mesh_candidates": [],
            "unmapped_phrases": [],
            "warnings": [],
            "mesh_coverage": mesh_coverage,
            "atm_coverage": {
                "status": "completed" if proposals is not None else "failed",
                "attempted": 1,
                "completed": int(proposals is not None),
                "failed": int(proposals is None),
            },
        }
        if phrases.truncated:
            outcome["warnings"].append(
                f"Only the first {len(phrases.tokens)} topic words were checked against MeSH; "
                "split long topics into concepts."
            )
        try:
            records_by_key = await self.lookup_mesh_records(lookups) if lookups else {}
        except NCBIInfrastructureError:
            mesh_coverage.update(status="failed", completed=0, failed=1)
            outcome["warnings"].append("NCBI MeSH analysis was unavailable for one or more terms.")
            outcome["unmapped_phrases"] = list(select_mappings(phrases, {}).unmapped)
            return outcome

        selection = select_mappings(phrases, records_by_key)
        atm_by_key: dict[str, set[str]] = {}
        for source, names in proposals or []:
            atm_by_key.setdefault(term_key(source), set()).update(name.casefold() for name in names)

        for mapping in selection.confirmed:
            record = mapping.match.record
            entry: dict[str, Any] = {
                "input": mapping.phrase.text,
                "preferred": record.preferred,
                "synonyms": record.text_synonyms(5),
                "mesh_id": record.uid,
                "record_type": record.record_type,
                "search_field": record.search_field,
                "tree_numbers": list(record.tree_numbers),
                "matched_on": mapping.match.matched_on,
                "matched_term": mapping.match.matched_term,
                "pubmed_atm": None,  # PubMed translation unavailable
            }
            if proposals is not None:
                proposed = atm_by_key.get(term_key(mapping.phrase.text), set())
                entry["pubmed_atm"] = (
                    "agrees" if record.preferred.casefold() in proposed else "differs" if proposed else "not_mapped"
                )
                if entry["pubmed_atm"] == "differs":
                    entry["pubmed_atm_terms"] = sorted(proposed)
            outcome["mesh_terms"].append(entry)

        for item in selection.ambiguous:
            outcome["mesh_candidates"].append(
                {
                    "input": item.phrase.text,
                    "candidates": [
                        {
                            "preferred": match.record.preferred,
                            "mesh_id": match.record.uid,
                            "record_type": match.record.record_type,
                            "matched_on": match.matched_on,
                            "matched_term": match.matched_term,
                        }
                        for match in item.matches
                    ],
                    "reason": "ambiguous_exact_term",
                    "note": "The phrase is an exact term of several MeSH records; choose one explicitly.",
                }
            )

        claimed = [mapping.phrase.text for mapping in selection.confirmed]
        claimed.extend(item.phrase.text for item in selection.ambiguous)
        for source, names in proposals or []:
            if any(contains_phrase(text, source) for text in claimed):
                continue
            for name in names:
                proposed_record = next(
                    (
                        match.record
                        for match in matches_for(name, records_by_key.get(term_key(name), ()))
                        if match.matched_on == "preferred"
                    ),
                    None,
                )
                outcome["mesh_candidates"].append(
                    {
                        "input": source,
                        "preferred": proposed_record.preferred if proposed_record else name,
                        "mesh_id": proposed_record.uid if proposed_record else None,
                        "record_type": proposed_record.record_type if proposed_record else None,
                        "reason": "pubmed_atm_only",
                        "note": (
                            "PubMed automatic term mapping links this phrase to the record, "
                            "but the phrase is not its preferred term or an entry term."
                        ),
                    }
                )

        outcome["unmapped_phrases"] = list(selection.unmapped)
        mesh_coverage.update(
            matched=len(outcome["mesh_terms"]),
            unconfirmed=len(outcome["mesh_candidates"]),
            phrases_checked=len({term_key(text) for text in lookups} - {""}),
        )
        return outcome

    async def _query_record(self, query: str, retmax: int, *, preview: bool = False) -> Any:
        async def _do_esearch():
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="pubmed",
                term=query,
                retmax=retmax,
                usehistory="n",
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            if preview:
                return await execute_entrez_operation(
                    _do_esearch,
                    api_key=self._api_key,
                    service_name="ncbi-strategy:analyze-query",
                    timeout=5.0,
                    total_timeout=6.0,
                    max_attempts=1,
                )
            return await self._execute_entrez(_do_esearch, service_name="ncbi-strategy:analyze-query")
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_query_analysis", exc)

    async def probe_query(self, query: str, limit: int) -> dict[str, Any]:
        """Fetch a count, PubMed's interpretation and bounded sample in a single ESearch."""
        result = await self._query_record(query, limit, preview=True)
        try:
            return self._parse_probe(result, limit)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy probe response", exc)

    @staticmethod
    def _parse_probe(result: Any, limit: int) -> dict[str, Any]:
        count = int(str(result["Count"]))
        raw_ids = result["IdList"]
        if not isinstance(raw_ids, list) or len(raw_ids) != min(count, limit):
            raise ValueError("Invalid PubMed sample length")
        ids = [str(pmid) for pmid in raw_ids]
        if any(not pmid.isascii() or not pmid.isdecimal() for pmid in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid PubMed identifiers")
        messages = [
            str(value)
            for group in ("ErrorList", "WarningList")
            for values in result.get(group, {}).values()
            for value in values
            if not (count == 0 and str(value).strip().lower().rstrip(".") == "no items found")
        ]
        translation = result["QueryTranslation"]
        if not isinstance(translation, str) or not translation.strip() or result.get("ERROR"):
            raise ValueError("Invalid PubMed query translation")
        return {"count": count, "pmids": ids, "translation": translation, "warnings": messages}

    async def analyze_query(self, query: str) -> dict[str, Any]:
        """Analyze PubMed's ESearch translation without retrieving articles."""
        result = await self._query_record(query, 0)
        try:
            return {
                "original": query,
                "count": int(result["Count"]),
                "translated_query": result.get("QueryTranslation", query),
                "translation_set": result.get("TranslationSet", []),
                "translation_stack": result.get("TranslationStack", []),
            }
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy query-analysis response", exc)

    async def generate_strategies(
        self,
        topic: str,
        strategy: str = "comprehensive",
        use_mesh: bool = True,
        check_spelling: bool = True,
        include_suggestions: bool = True,
        analyze_queries: bool = True,
    ) -> dict[str, Any]:
        """
        Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide.

        The Agent (or a lightweight LLM like minimind) can decide how to use these materials:
        - Use mesh_terms (confirmed exact preferred/entry-term matches) to build MeSH queries
        - Review mesh_candidates (ambiguous or PubMed-ATM-only links) before using them
        - Cover unmapped_phrases with free-text terms
        - Use synonyms for query expansion
        - Use corrected spelling or not
        - Generate its own query combinations

        NEW: When analyze_queries=True, each suggested query includes:
        - estimated_count: How many results PubMed would return
        - pubmed_translation: How PubMed actually interprets the query

        This helps the Agent understand the difference between:
        - What the Agent thinks the query means
        - What PubMed actually searches for

        Args:
            topic: Research topic
            strategy: "comprehensive", "focused", or "exploratory" (for suggestions)
            use_mesh: Whether to lookup MeSH terms
            check_spelling: Whether to check spelling
            include_suggestions: Whether to include pre-built query suggestions
            analyze_queries: Whether to analyze how PubMed interprets each query

        Returns:
            Dict with raw materials (spelling, mesh_terms, mesh_candidates,
            unmapped_phrases, keywords) and optional suggestions
        """
        result: dict[str, Any] = {
            "topic": topic,
            "corrected_topic": topic,  # May be updated by spell check
            "spelling": None,
            "keywords": [],  # Extracted keywords from topic
            "mesh_terms": [],  # Confirmed MeSH mappings with match evidence
            "mesh_candidates": [],  # Unconfirmed links that need review, with reasons
            "unmapped_phrases": [],  # Topic phrases without a confirmed MeSH term
            "all_synonyms": [],  # Flattened list of all synonyms
            # Optional: pre-built suggestions (Agent can ignore)
            "suggested_queries": [] if include_suggestions else None,
            "coverage": {
                "spelling": {
                    "status": "pending" if check_spelling else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                },
                "mesh": {
                    "status": "pending" if use_mesh else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                    "matched": 0,
                    "unconfirmed": 0,
                    "phrases_checked": 0,
                },
                "pubmed_atm": {
                    "status": "pending" if use_mesh else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                },
                "query_analysis": {
                    "status": "pending" if include_suggestions and analyze_queries else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                },
            },
            "warnings": [],
        }

        # Step 1: Spell check
        working_topic = topic
        if check_spelling:
            try:
                corrected, was_corrected = await self.spell_check(topic)
            except NCBIInfrastructureError:
                result["coverage"]["spelling"] = {
                    "status": "failed",
                    "attempted": 1,
                    "completed": 0,
                    "failed": 1,
                }
                result["warnings"].append("NCBI spelling analysis was unavailable.")
            else:
                result["spelling"] = {
                    "original": topic,
                    "corrected": corrected,
                    "was_corrected": was_corrected,
                }
                result["coverage"]["spelling"] = {
                    "status": "completed",
                    "attempted": 1,
                    "completed": 1,
                    "failed": 0,
                    "corrected": was_corrected,
                }
                if was_corrected:
                    working_topic = corrected
                    result["corrected_topic"] = corrected

        # Step 2: Map stopword-bounded topic phrases to MeSH, longest first.
        # Only exact preferred/entry-term matches become mesh_terms.
        words = working_topic.split()
        stop_words = {
            "and",
            "or",
            "the",
            "in",
            "of",
            "for",
            "with",
            "to",
            "a",
            "an",
        }

        if use_mesh:
            mapping = await self._map_topic_to_mesh(working_topic)
            result["mesh_terms"] = mapping["mesh_terms"]
            result["mesh_candidates"] = mapping["mesh_candidates"]
            result["unmapped_phrases"] = mapping["unmapped_phrases"]
            result["coverage"]["mesh"] = mapping["mesh_coverage"]
            result["coverage"]["pubmed_atm"] = mapping["atm_coverage"]
            result["warnings"].extend(mapping["warnings"])

        # Extract keywords for Agent to use
        result["keywords"] = [w for w in words if w.lower() not in stop_words and len(w) > 2]

        # Flatten all synonyms for easy access
        all_synonyms = []
        for mesh in result["mesh_terms"]:
            all_synonyms.extend(mesh.get("synonyms", []))
        result["all_synonyms"] = list(dict.fromkeys(all_synonyms))[:15]  # Dedupe, limit

        # Step 3: Generate suggested queries (optional - Agent can ignore or use as reference)
        if not include_suggestions:
            return result

        queries = []
        query_id = 1

        # Basic queries
        queries.append(
            {
                "id": f"q{query_id}_title",
                "query": f"({working_topic})[Title]",
                "purpose": "Exact title match - highest precision",
                "priority": 1,
            }
        )
        query_id += 1

        queries.append(
            {
                "id": f"q{query_id}_tiab",
                "query": f"({working_topic})[Title/Abstract]",
                "purpose": "Title or abstract - balanced",
                "priority": 2,
            }
        )
        query_id += 1

        # AND query with all words
        if len(words) > 1:
            and_query = " AND ".join(words)
            queries.append(
                {
                    "id": f"q{query_id}_and",
                    "query": f"({and_query})",
                    "purpose": "All keywords required",
                    "priority": 2,
                }
            )
            query_id += 1

        # MeSH-based queries: confirmed mappings only, never unconfirmed candidates.
        confirmed = result["mesh_terms"]
        for mesh in confirmed[:2]:
            queries.append(
                {
                    "id": f"q{query_id}_mesh",
                    "query": f'"{mesh["preferred"]}"[{mesh["search_field"]}]',
                    "purpose": (
                        f"MeSH {mesh['matched_on'].replace('_', ' ')} match: {mesh['input']} → {mesh['preferred']}"
                    ),
                    "priority": 2,
                }
            )
            query_id += 1

        # Use synonyms for expansion
        if strategy in ["comprehensive", "exploratory"]:
            for mesh in confirmed[:1]:
                for syn in mesh.get("synonyms", [])[:2]:
                    queries.append(
                        {
                            "id": f"q{query_id}_syn",
                            "query": f"({syn})[Title/Abstract]",
                            "purpose": f"MeSH synonym: {mesh['input']} → {syn}",
                            "priority": 3,
                        }
                    )
                    query_id += 1

        # Strategy-specific queries
        if strategy == "comprehensive":
            # Add review filter
            queries.append(
                {
                    "id": f"q{query_id}_review",
                    "query": f"({working_topic}) AND (review[pt] OR systematic review[pt])",
                    "purpose": "Review articles only",
                    "priority": 3,
                }
            )
            query_id += 1

        if strategy == "exploratory" and len(words) >= 2:
            # Broader search
            queries.append(
                {
                    "id": f"q{query_id}_broad",
                    "query": f"({words[0]})[Title] AND ({' OR '.join(words[1:])})",
                    "purpose": "Broader: main term + any modifier",
                    "priority": 4,
                }
            )
            query_id += 1

        if strategy == "focused":
            # Add RCT filter for high-quality evidence
            queries.append(
                {
                    "id": f"q{query_id}_rct",
                    "query": f"({working_topic}) AND (randomized controlled trial[pt])",
                    "purpose": "Randomized controlled trial publication type; quality not assessed",
                    "priority": 1,
                }
            )
            query_id += 1

        # Step 4: Analyze how PubMed interprets each query (optional but recommended)
        if analyze_queries:
            completed_analyses = 0
            failed_analyses = 0
            for q in queries:
                try:
                    analysis = await self.analyze_query(str(q["query"]))
                    q["estimated_count"] = analysis.get("count", 0)
                    q["pubmed_translation"] = analysis.get("translated_query", q["query"])
                    completed_analyses += 1
                except NCBIInfrastructureError as exc:
                    logger.warning("Suggested-query analysis failed (%s)", type(exc).__name__)
                    q["estimated_count"] = None
                    q["pubmed_translation"] = None
                    failed_analyses += 1
            result["coverage"]["query_analysis"] = {
                "status": "completed" if not failed_analyses else "partial" if completed_analyses else "failed",
                "attempted": len(queries),
                "completed": completed_analyses,
                "failed": failed_analyses,
            }
            if failed_analyses:
                result["warnings"].append(
                    "PubMed translation analysis was unavailable for one or more suggested queries."
                )

        result["suggested_queries"] = queries

        return result

    async def expand_with_mesh(self, topic: str, existing_queries: list[str]) -> dict[str, Any]:
        """
        Generate expansion queries using MeSH relationships.

        Args:
            topic: Original topic
            existing_queries: List of already-used query IDs

        Returns:
            New queries for expansion
        """
        result: dict[str, Any] = {"topic": topic, "expansion_type": "mesh_based", "queries": []}

        existing_set = set(existing_queries)
        query_id = 1
        # Reserve both generated suffixes before allocating the next numeric ID.
        while any(f"q{query_id}_{suffix}" in existing_set for suffix in ("exp_syn", "exp_word")):
            query_id += 1

        # Get MeSH info
        mesh_info = await self.get_mesh_info(topic)

        if mesh_info:
            # Use remaining synonyms
            for syn in mesh_info.get("synonyms", [])[5:10]:
                while f"q{query_id}_exp_syn" in existing_set:
                    query_id += 1
                qid = f"q{query_id}_exp_syn"
                if qid not in existing_set:
                    result["queries"].append(
                        {
                            "id": qid,
                            "query": f"({syn})[Title/Abstract]",
                            "purpose": f"Expanded synonym: {syn}",
                            "priority": 4,
                        }
                    )
                    query_id += 1

        # Try related terms for individual words
        words = topic.split()
        for word in words[:2]:
            if len(word) > 4:
                word_mesh = await self.get_mesh_info(word)
                if word_mesh:
                    for syn in word_mesh.get("synonyms", [])[:2]:
                        new_topic = topic.replace(word, syn)
                        while f"q{query_id}_exp_word" in existing_set:
                            query_id += 1
                        qid = f"q{query_id}_exp_word"
                        if qid not in existing_set:
                            result["queries"].append(
                                {
                                    "id": qid,
                                    "query": f"({new_topic})[Title/Abstract]",
                                    "purpose": f"Word expansion: {word} → {syn}",
                                    "priority": 4,
                                }
                            )
                            query_id += 1

        result["queries_count"] = len(result["queries"])
        return result
