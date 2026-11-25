"""Regression tests for year-tolerant, correction-capable reference verification.

The fake below replaces only the external PubMed boundary (ECitMatch, ESearch,
EFetch). It honours the query semantics the service relies on - exact-title
phrase search, ``[1au]``/``[ta]``/``[vi]``/``[pg]`` metadata search, and the
publication-year filter - so a regression back to year-pinned searching makes
these tests fail instead of passing against a permissive mock.

Benchmark list (v0.10.0 run): references 1-3 are correct, 4 cites the wrong
year (2012; the matching record is the 2014 update, PMID 24937564, while a 2007
version PMID 17943802 shares the title with a different author order), 5 cites
the wrong year and volume (2018;320 instead of 2019;321), 6 and 7 are
fabricated. v0.10.0 reported 3-7 as indistinguishable ``unresolved`` rows.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pytest

from pubmed_search.application.reference_verification import ReferenceVerificationService
from pubmed_search.application.search.source_models import SourceSearchPage

BENCHMARK_REFERENCES = """
1. Aldrete JA. The post-anesthesia recovery score revisited. J Clin Anesth. 1995;7(1):89-91.
2. Sessler CN, Gosnell MS, Grap MJ, et al. The Richmond Agitation-Sedation Scale: validity and reliability in adult intensive care unit patients. Am J Respir Crit Care Med. 2002;166(10):1338-1344.
3. Evered L, Silbert B, Knopman DS, et al. Recommendations for the nomenclature of cognitive change associated with anaesthesia and surgery-2018. Br J Anaesth. 2018;121(5):1005-1012.
4. Punjasawadwong Y, Phongchiewboon A, Bunchungmongkol N. Bispectral index for improving anaesthetic delivery and postoperative recovery. Cochrane Database Syst Rev. 2012;(6):CD003843.
5. Wildes TS, Mickle AM, Ben Abdallah A, et al. Effect of electroencephalography-guided anesthetic administration on postoperative delirium among older adults undergoing major surgery: the ENGAGES randomized clinical trial. JAMA. 2018;320(5):473-483.
6. Chen YH, Lin WC, Huang SM. Processed electroencephalography-guided discharge from the post-anesthesia care unit: a randomized trial. Anesth Analg. 2021;132(4):1021-1029.
7. Müller K, Svensson P. Emergence trajectories measured by spectral edge frequency in the post-anaesthesia care unit. Br J Anaesth. 2019;123(2):e310-e318.
"""


def _record(
    pmid: str,
    *,
    title: str,
    authors: list[str],
    journal: str,
    journal_abbrev: str,
    year: str,
    volume: str,
    issue: str,
    pages: str,
    doi: str = "",
) -> dict[str, Any]:
    """Build an EFetch-shaped article row like ``SearchMixin._parse_pubmed_article``."""
    return {
        "pmid": pmid,
        "title": title,
        "authors": [f"{surname} {initials}" for surname, initials in (name.rsplit(" ", 1) for name in authors)],
        "authors_full": [
            {"last_name": surname, "fore_name": initials, "initials": initials}
            for surname, initials in (name.rsplit(" ", 1) for name in authors)
        ],
        "journal": journal,
        "journal_abbrev": journal_abbrev,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
    }


# Real PubMed records for the benchmark (identifiers as indexed in PubMed).
PUBMED_RECORDS = [
    _record(
        "7772368",
        title="The post-anesthesia recovery score revisited.",
        authors=["Aldrete JA"],
        journal="Journal of clinical anesthesia",
        journal_abbrev="J Clin Anesth",
        year="1995",
        volume="7",
        issue="1",
        pages="89-91",
        doi="10.1016/0952-8180(94)00001-k",
    ),
    _record(
        "12421743",
        title=(
            "The Richmond Agitation-Sedation Scale: validity and reliability in adult intensive care unit patients."
        ),
        authors=["Sessler CN", "Gosnell MS", "Grap MJ", "Brophy GM", "O'Neal PV", "Keane KA"],
        journal="American journal of respiratory and critical care medicine",
        journal_abbrev="Am J Respir Crit Care Med",
        year="2002",
        volume="166",
        issue="10",
        pages="1338-44",
        doi="10.1164/rccm.2107138",
    ),
    _record(
        "30336844",
        title=(
            "Recommendations for the nomenclature of cognitive change associated with anaesthesia and surgery-2018."
        ),
        authors=["Evered L", "Silbert B", "Knopman DS", "Scott DA", "DeKosky ST"],
        journal="British journal of anaesthesia",
        journal_abbrev="Br J Anaesth",
        year="2018",
        volume="121",
        issue="5",
        pages="1005-1012",
    ),
    # Synthetic identifier: the same consensus statement co-published elsewhere.
    _record(
        "90000003",
        title=(
            "Recommendations for the nomenclature of cognitive change associated with anaesthesia and surgery-2018."
        ),
        authors=["Evered L", "Silbert B", "Knopman DS", "Scott DA", "DeKosky ST"],
        journal="Anesthesiology",
        journal_abbrev="Anesthesiology",
        year="2018",
        volume="129",
        issue="5",
        pages="872-879",
    ),
    _record(
        "24937564",
        title="Bispectral index for improving anaesthetic delivery and postoperative recovery.",
        authors=["Punjasawadwong Y", "Phongchiewboon A", "Bunchungmongkol N"],
        journal="The Cochrane database of systematic reviews",
        journal_abbrev="Cochrane Database Syst Rev",
        year="2014",
        volume="2014",
        issue="6",
        pages="CD003843",
        doi="10.1002/14651858.CD003843.pub3",
    ),
    _record(
        "17943802",
        title="Bispectral index for improving anaesthetic delivery and postoperative recovery.",
        authors=["Punjasawadwong Y", "Boonjeungmonkol N", "Phongchiewboon A"],
        journal="The Cochrane database of systematic reviews",
        journal_abbrev="Cochrane Database Syst Rev",
        year="2007",
        volume="",
        issue="4",
        pages="CD003843",
        doi="10.1002/14651858.CD003843.pub2",
    ),
    _record(
        "30721296",
        title=(
            "Effect of Electroencephalography-Guided Anesthetic Administration on Postoperative Delirium Among "
            "Older Adults Undergoing Major Surgery: The ENGAGES Randomized Clinical Trial."
        ),
        authors=["Wildes TS", "Mickle AM", "Ben Abdallah A", "Maybrier HR", "Oberhaus J"],
        journal="JAMA",
        journal_abbrev="JAMA",
        year="2019",
        volume="321",
        issue="5",
        pages="473-483",
        doi="10.1001/jama.2018.22005",
    ),
    # Synthetic distractors: real-looking articles that share the fabricated
    # references' first author, journal and volume but not their titles.
    _record(
        "90000006",
        title="Postoperative nausea after ambulatory knee arthroscopy: a cohort study.",
        authors=["Chen Y", "Wang L"],
        journal="Anesthesia and analgesia",
        journal_abbrev="Anesth Analg",
        year="2021",
        volume="132",
        issue="2",
        pages="455-463",
    ),
    _record(
        "90000007",
        title="Sugammadex and postoperative pulmonary complications in older adults.",
        authors=["Müller K", "Schmidt A"],
        journal="British journal of anaesthesia",
        journal_abbrev="Br J Anaesth",
        year="2019",
        volume="123",
        issue="3",
        pages="301-309",
    ),
]

_TITLE_CLAUSE_RE = re.compile(r"^\(?(?P<words>[a-z0-9]+\[ti\](?: OR [a-z0-9]+\[ti\])*)\)?$")
_TITLE_WORD_RE = re.compile(r"([a-z0-9]+)\[ti\]")
# Live ESearch returns no hits for a tagged PubMed stopword such as ``among[ti]``.
_PUBMED_STOPWORD_SAMPLE = frozenset({"among", "the", "for", "and", "of", "on", "in", "with", "a"})
_METADATA_QUERY_RE = re.compile(r'^(?P<author>[^\[]+)\[1au\] AND "(?P<journal>[^"]+)"\[ta\] AND (?P<locators>.+)$')
_LOCATOR_TERM_RE = re.compile(r'"(?P<value>[^"]+)"\[(?P<tag>vi|pg)\]')
_AID_QUERY_RE = re.compile(r'^"(?P<doi>[^"]+)"\[AID\]$')


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower().strip()


def _title_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold(value)))


def _title_query_matches(query: str, title: str) -> bool | None:
    """Evaluate ``word[ti] AND (a[ti] OR b[ti])`` like ESearch; ``None`` if not a title query."""
    clauses = query.split(" AND ")
    if not all(_TITLE_CLAUSE_RE.match(clause) for clause in clauses):
        return None
    words = _title_words(title)
    for clause in clauses:
        alternatives = _TITLE_WORD_RE.findall(clause)
        if any(alternative in _PUBMED_STOPWORD_SAMPLE for alternative in alternatives):
            return False
        if not any(alternative in words for alternative in alternatives):
            return False
    return True


def _first_page(pages: str) -> str:
    match = re.match(r"\s*([A-Za-z]{0,4}\d+[A-Za-z]?)", pages)
    return match.group(1).lower() if match else ""


class FakePubMed:
    """In-memory PubMed boundary with ECitMatch/ESearch/EFetch semantics."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = {record["pmid"]: record for record in records}
        self.ecitmatch_calls: list[dict[str, str]] = []
        self.search_calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_queries: tuple[str, ...] = ()

    async def find_by_citation(
        self,
        journal: str,
        year: str,
        volume: str = "",
        first_page: str = "",
        author: str = "",
        title: str = "",
    ) -> str | None:
        del title  # ECitMatch ignores titles.
        self.ecitmatch_calls.append(
            {"journal": journal, "year": year, "volume": volume, "first_page": first_page, "author": author}
        )
        matches = [
            record
            for record in self.records.values()
            if _fold(journal) in {_fold(record["journal_abbrev"]), _fold(record["journal"])}
            and year == record["year"]
            and (not volume or volume == record["volume"])
            and (not first_page or first_page.lower() == _first_page(record["pages"]))
            and (not author or _fold(author) == _fold(record["authors_full"][0]["last_name"]))
        ]
        return matches[0]["pmid"] if len(matches) == 1 else None

    async def verify_references(self, citations: list[dict[str, str]]) -> list[dict[str, Any]]:
        results = []
        for citation in citations:
            pmid = await self.find_by_citation(**citation)
            results.append({**citation, "pmid": pmid, "verified": pmid is not None})
        return results

    async def fetch_details(self, id_list: list[str]) -> list[dict[str, Any]]:
        return [dict(self.records[pmid]) for pmid in id_list if pmid in self.records]

    async def search_page(self, query: str, limit: int = 5, **kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        self.search_calls.append((query, dict(kwargs)))
        if any(fragment in query for fragment in self.fail_queries):
            raise RuntimeError("upstream unavailable")
        hits = [record for record in self.records.values() if self._matches(query, record)]
        min_year, max_year = kwargs.get("min_year"), kwargs.get("max_year")
        hits = [
            record
            for record in hits
            if (min_year is None or int(record["year"]) >= min_year)
            and (max_year is None or int(record["year"]) <= max_year)
        ]
        items = [dict(record) for record in hits[:limit]]
        return SourceSearchPage(source="pubmed", items=items, total=len(hits), query=query)

    @staticmethod
    def _matches(query: str, record: dict[str, Any]) -> bool:
        if '"' in query and "[Title]" in query:
            # E-utilities cannot phrase-search long titles (QuotedPhraseNotFound, zero hits).
            return False
        title_match = _title_query_matches(query, record["title"])
        if title_match is not None:
            return title_match
        if aid_match := _AID_QUERY_RE.match(query):
            return _fold(aid_match.group("doi")) == _fold(record["doi"])
        metadata_match = _METADATA_QUERY_RE.match(query)
        if metadata_match is None:
            raise AssertionError(f"Unexpected PubMed query shape: {query}")
        if _fold(metadata_match.group("author")) != _fold(record["authors_full"][0]["last_name"]):
            return False
        if _fold(metadata_match.group("journal")) not in {_fold(record["journal_abbrev"]), _fold(record["journal"])}:
            return False
        locator_values = {"vi": record["volume"].lower(), "pg": _first_page(record["pages"])}
        terms = _LOCATOR_TERM_RE.findall(metadata_match.group("locators"))
        assert terms, query
        return any(value.lower() == locator_values[tag] for value, tag in terms)


@pytest.fixture
def pubmed() -> FakePubMed:
    return FakePubMed(PUBMED_RECORDS)


async def test_benchmark_list_separates_correct_miscited_and_unfound_references(pubmed: FakePubMed) -> None:
    report = await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES)
    rows = report["results"]

    assert [row["status"] for row in rows] == [
        "verified",
        "verified",
        "verified",
        "partial_match",
        "partial_match",
        "unresolved",
        "unresolved",
    ]
    assert report["summary"] == {
        "verified": 3,
        "partial_match": 2,
        "unresolved": 2,
        "invalid_input": 0,
        "source_unavailable": 0,
        "not_checked": 0,
    }
    assert [row["matched_article"]["pmid"] for row in rows[:5]] == [
        "7772368",
        "12421743",
        "30336844",
        "24937564",
        "30721296",
    ]
    assert [row["resolution_method"] for row in rows] == [
        "ecitmatch",
        "ecitmatch",
        "ecitmatch",
        "title_search",
        "title_search",
        None,
        None,
    ]
    assert all(row["corrections"] == [] for row in rows[:3])


async def test_title_year_does_not_split_title_from_journal(pubmed: FakePubMed) -> None:
    row = (await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES))["results"][2]

    parsed = row["parsed_reference"]
    assert parsed["journal"] == "Br J Anaesth"
    assert parsed["title"].endswith("anaesthesia and surgery-2018")
    assert (parsed["year"], parsed["volume"], parsed["first_page"]) == ("2018", "121", "1005")
    # The BJA record wins over the same statement co-published in another journal.
    assert row["status"] == "verified"
    assert row["matched_article"]["journal_abbrev"] == "Br J Anaesth"


async def test_wrong_year_resolves_to_closest_version_with_year_correction(pubmed: FakePubMed) -> None:
    row = (await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES))["results"][3]

    assert row["status"] == "partial_match"
    assert row["matched_article"]["pmid"] == "24937564"
    assert row["matched_article"]["doi"] == "10.1002/14651858.CD003843.pub3"
    assert row["mismatched_fields"] == ["year"]
    assert row["corrections"] == [{"field": "year", "cited": "2012", "pubmed": "2014"}]
    assert row["parsed_reference"]["issue"] == "6"
    assert row["parsed_reference"]["first_page"] == "CD003843"
    assert any("PMID 17943802 (2007)" in note for note in row["notes"])
    assert any("year 2012 -> 2014" in note for note in row["notes"])


async def test_wrong_year_and_volume_are_reported_as_field_corrections(pubmed: FakePubMed) -> None:
    report = await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES)
    row = report["results"][4]

    assert row["status"] == "partial_match"
    assert row["matched_article"]["pmid"] == "30721296"
    assert row["matched_article"]["doi"] == "10.1001/jama.2018.22005"
    assert row["corrections"] == [
        {"field": "year", "cited": "2018", "pubmed": "2019"},
        {"field": "volume", "cited": "320", "pubmed": "321"},
    ]
    queue_item = next(item for item in report["review_workflow"]["review_queue"] if item["index"] == 5)
    assert queue_item["review_priority"] == "high"
    assert "year (2018 -> 2019)" in queue_item["review_reason"]
    assert "PMID 30721296" in queue_item["review_reason"]


async def test_unfound_references_list_strategies_without_claiming_fabrication(pubmed: FakePubMed) -> None:
    rows = (await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES))["results"][5:]

    for row, distractor in zip(rows, ("90000006", "90000007"), strict=True):
        assert row["status"] == "unresolved"
        assert row["matched_article"] is None
        assert row["corrections"] == []
        assert row["attempted_strategies"] == ["ecitmatch", "title_search", "metadata_search"]
        notes = " ".join(row["notes"])
        assert "No PubMed record was found after" in notes
        assert "ECitMatch" in notes
        assert "title-word search without a year restriction" in notes
        assert "volume/first-page search without a year restriction" in notes
        assert "does not by itself prove the reference is fabricated" in notes
        # A same-author, same-journal article with another title is not accepted.
        assert f"PMID {distractor} was not accepted because its title does not match" in notes
        assert "ECitMatch did not resolve" not in notes


async def test_searches_never_pin_the_cited_year_and_ecitmatch_is_not_repeated(pubmed: FakePubMed) -> None:
    await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES)

    assert all("min_year" not in kwargs and "max_year" not in kwargs for _query, kwargs in pubmed.search_calls)
    # One batched ECitMatch lookup per reference; misses are not re-sent individually.
    assert len(pubmed.ecitmatch_calls) == 7
    # Diacritics are folded for the pipe-delimited ECitMatch protocol and author search.
    assert pubmed.ecitmatch_calls[6]["author"] == "Muller"
    assert any(query.startswith("Muller[1au]") for query, _kwargs in pubmed.search_calls)


async def test_title_search_uses_title_words_not_an_unindexed_phrase(pubmed: FakePubMed) -> None:
    await ReferenceVerificationService(pubmed).verify_reference_list(BENCHMARK_REFERENCES)

    title_queries = [query for query, _kwargs in pubmed.search_calls if "[ti]" in query]
    engages = next(query for query in title_queries if "delirium[ti]" in query)
    assert '"' not in engages
    # ``among`` is a PubMed stopword: tagging it would make ESearch return nothing.
    assert "among[ti]" not in engages
    assert "(anesthetic[ti] OR anaesthetic[ti])" in engages
    assert "electroencephalography[ti]" in engages


async def test_spelling_variant_title_matches_without_title_correction(pubmed: FakePubMed) -> None:
    row = await ReferenceVerificationService(pubmed).verify_reference(
        "Wildes TS, Mickle AM. Effect of electroencephalography guided anaesthetic administration on "
        "postoperative delirium among older adults undergoing major surgery: the ENGAGES randomised clinical "
        "trial. JAMA. 2018;320(5):473-483.",
        index=1,
    )

    assert row["status"] == "partial_match"
    assert row["resolution_method"] == "title_search"
    assert row["comparison"]["title"] is True
    assert [item["field"] for item in row["corrections"]] == ["year", "volume"]


async def test_locator_search_corrects_year_when_no_title_is_cited(pubmed: FakePubMed) -> None:
    row = await ReferenceVerificationService(pubmed).verify_reference("Wildes TS. JAMA. 2018;321(5):473-483.", index=1)

    assert row["status"] == "partial_match"
    assert row["resolution_method"] == "metadata_search"
    assert row["matched_article"]["pmid"] == "30721296"
    assert row["corrections"] == [{"field": "year", "cited": "2018", "pubmed": "2019"}]
    assert row["attempted_strategies"] == ["ecitmatch", "metadata_search"]


async def test_same_title_with_different_author_and_journal_is_not_accepted(pubmed: FakePubMed) -> None:
    row = await ReferenceVerificationService(pubmed).verify_reference(
        "Doe A. The post-anesthesia recovery score revisited. Lancet. 1996;7(1):89-91.",
        index=1,
    )

    assert row["status"] == "unresolved"
    assert row["matched_article"] is None
    assert any("both the first author and the journal differ" in note for note in row["notes"])


async def test_conflicting_title_withholds_corrections_for_identifier_match(pubmed: FakePubMed) -> None:
    row = await ReferenceVerificationService(pubmed).verify_reference(
        "Doe A. Invented emergence trial in recovery units. JAMA. 2019;321(5):473-483. PMID: 30721296",
        index=1,
    )

    assert row["status"] == "partial_match"
    assert set(row["mismatched_fields"]) == {"first_author", "title"}
    assert row["corrections"] == []
    assert any(
        "No field corrections proposed: the cited title does not match PMID 30721296" in note for note in row["notes"]
    )


# A real-looking record that shares nothing with the ENGAGES citation except a
# cited identifier pointing at it (a transcription error or a fabricated PMID).
UNRELATED_CIRCULATION = _record(
    "90000099",
    title="Totally unrelated cardiology paper.",
    authors=["Zhang W"],
    journal="Circulation",
    journal_abbrev="Circulation",
    year="2010",
    volume="122",
    issue="2",
    pages="100-110",
    doi="10.1161/circ.2010.000001",
)
ENGAGES_TITLE = (
    "Effect of electroencephalography-guided anesthetic administration on postoperative delirium among older "
    "adults undergoing major surgery: the ENGAGES randomized clinical trial"
)
_PMID_FIX = {"field": "pmid", "cited": "90000099", "pubmed": "30721296"}
_YEAR_FIX = {"field": "year", "cited": "2018", "pubmed": "2019"}


@pytest.mark.parametrize(
    ("reference", "method", "attempted", "corrections"),
    [
        pytest.param(
            "Wildes TS, et al. JAMA. 2019;321(5):473-483. PMID: 90000099",
            "ecitmatch",
            ["pmid", "ecitmatch"],
            [_PMID_FIX],
            id="pmid-found-by-ecitmatch",
        ),
        pytest.param(
            "Wildes TS, et al. JAMA. 2018;321(5):473-483. PMID: 90000099",
            "metadata_search",
            ["pmid", "ecitmatch", "metadata_search"],
            [_YEAR_FIX, _PMID_FIX],
            id="pmid-and-year-wrong-found-by-locator-search",
        ),
        pytest.param(
            f"Wildes TS, Mickle AM. {ENGAGES_TITLE}. JAMA. 2018;320(5):473-483. PMID: 90000099",
            "title_search",
            ["pmid", "ecitmatch", "title_search"],
            [_YEAR_FIX, {"field": "volume", "cited": "320", "pubmed": "321"}, _PMID_FIX],
            id="pmid-with-title-found-by-title-search",
        ),
        pytest.param(
            "Wildes TS, et al. JAMA. 2018;321(5):473-483. doi:10.1161/circ.2010.000001",
            "metadata_search",
            ["doi_search", "ecitmatch", "metadata_search"],
            [_YEAR_FIX, {"field": "doi", "cited": "10.1161/circ.2010.000001", "pubmed": "10.1001/jama.2018.22005"}],
            id="doi-and-year-wrong-found-by-locator-search",
        ),
    ],
)
async def test_identifier_contradicted_by_every_cited_field_does_not_stop_resolution(
    reference: str, method: str, attempted: list[str], corrections: list[dict[str, str]]
) -> None:
    pubmed = FakePubMed([*PUBMED_RECORDS, UNRELATED_CIRCULATION])
    row = await ReferenceVerificationService(pubmed).verify_reference(reference, index=1)

    assert row["status"] == "partial_match"
    assert row["matched_article"]["pmid"] == "30721296"
    assert row["resolution_method"] == method
    assert row["attempted_strategies"] == attempted
    assert row["corrections"] == corrections
    assessment = row["identifier_assessment"]
    assert assessment["assessment"] == "probably_wrong"
    assert assessment["resolved_article"]["pmid"] == "90000099"
    assert assessment["agreeing_fields"] == []
    assert assessment["replaced_by_pmid"] == "30721296"
    assert any(f"is probably wrong; PMID 30721296 found via {method}" in note for note in row["notes"])


async def test_identifier_contradicted_by_every_cited_field_without_alternative_is_unresolved() -> None:
    pubmed = FakePubMed([UNRELATED_CIRCULATION])
    report = await ReferenceVerificationService(pubmed).verify_reference_list(
        "Wildes TS, et al. JAMA. 2019;321(5):473-483. PMID: 90000099"
    )
    row = report["results"][0]

    assert row["status"] == "unresolved"
    assert row["matched_article"] is None
    assert row["corrections"] == []
    # The cited PMID does not short-circuit ECitMatch or the year-tolerant search.
    assert row["attempted_strategies"] == ["pmid", "ecitmatch", "metadata_search"]
    assert len(pubmed.ecitmatch_calls) == 1
    assert any("[1au]" in query for query, _kwargs in pubmed.search_calls)
    assessment = row["identifier_assessment"]
    assert {key: assessment[key] for key in ("field", "cited", "assessment", "replaced_by_pmid")} == {
        "field": "pmid",
        "cited": "90000099",
        "assessment": "probably_wrong",
        "replaced_by_pmid": None,
    }
    assert assessment["agreeing_fields"] == []
    assert assessment["conflicting_fields"] == ["first_author", "journal", "year", "volume", "first_page"]
    assert assessment["resolved_article"]["journal"] == "Circulation"
    notes = " ".join(row["notes"])
    assert "The cited PMID 90000099 resolves to PMID 90000099 (Circulation 2010)" in notes
    assert "the PMID is probably wrong" in notes
    assert "No PubMed record was found after" in notes
    queue_item = report["review_workflow"]["review_queue"][0]
    assert queue_item["review_priority"] == "high"
    assert "PMID 90000099 is probably wrong" in queue_item["review_reason"]


async def test_failed_search_after_contradicted_identifier_keeps_the_identifier_evidence() -> None:
    pubmed = FakePubMed([UNRELATED_CIRCULATION])
    pubmed.fail_queries = ("[1au]",)
    row = await ReferenceVerificationService(pubmed).verify_reference(
        "Wildes TS, et al. JAMA. 2019;321(5):473-483. PMID: 90000099", index=1
    )

    assert row["status"] == "source_unavailable"
    assert row["source_errors"] == [{"source": "PubMed metadata search", "error": "upstream source unavailable"}]
    assert row["identifier_assessment"]["assessment"] == "probably_wrong"
    assert "the PMID is probably wrong" in row["notes"][0]


async def test_identifier_record_agreeing_on_one_field_is_kept_without_corrections() -> None:
    pubmed = FakePubMed([UNRELATED_CIRCULATION])
    row = await ReferenceVerificationService(pubmed).verify_reference(
        "Zhang W. JAMA. 2019;321(5):473-483. PMID: 90000099", index=1
    )

    assert row["status"] == "partial_match"
    assert row["resolution_method"] == "pmid"
    assert row["matched_article"]["pmid"] == "90000099"
    assert row["corrections"] == []
    assert row["attempted_strategies"] == ["pmid", "ecitmatch", "metadata_search"]
    assert row["identifier_assessment"]["assessment"] == "weakly_corroborated"
    assert row["identifier_assessment"]["agreeing_fields"] == ["first_author"]
    assert row["identifier_assessment"]["replaced_by_pmid"] is None
    assert "only first_author agrees with PMID 90000099 besides the cited PMID" in row["corrections_withheld_reason"]


async def test_equally_good_versions_withhold_corrections() -> None:
    twins = [
        _record(
            pmid,
            title="Spectral edge frequency for titration of propofol sedation.",
            authors=["Lee K", "Park S"],
            journal="Anaesthesia",
            journal_abbrev="Anaesthesia",
            year=year,
            volume="70",
            issue="1",
            pages="10-17",
        )
        for pmid, year in (("90000101", "2014"), ("90000102", "2016"))
    ]
    row = await ReferenceVerificationService(FakePubMed(twins)).verify_reference(
        "Lee K, Park S. Spectral edge frequency for titration of propofol sedation. Anaesthesia. 2015;70(1):10-17.",
        index=1,
    )

    assert row["status"] == "partial_match"
    assert row["corrections"] == []
    assert any("several PubMed records match about equally well" in note for note in row["notes"])


def _wang_dexmedetomidine_record(title: str) -> dict[str, Any]:
    """A real-looking record that shares only the cited first author and some title words."""
    return _record(
        "31000001",
        title=title,
        authors=["Wang H", "Chen L"],
        journal="Journal of cardiothoracic and vascular anesthesia",
        journal_abbrev="J Cardiothorac Vasc Anesth",
        year="2021",
        volume="35",
        issue="4",
        pages="1100-1110",
    )


@pytest.mark.parametrize(
    "record_title",
    [
        pytest.param(
            "Dexmedetomidine for the prevention of delirium in elderly patients after cardiac surgery: "
            "a meta-analysis of randomized trials.",
            id="cited-title-contained-in-longer-title",
        ),
        pytest.param("Dexmedetomidine for the prevention of delirium.", id="identical-title"),
    ],
)
async def test_title_hit_corroborated_by_one_field_is_returned_without_corrections(record_title: str) -> None:
    # Only the first author agrees besides the title used to find the record:
    # journal, year, volume and first page all differ, so this may be a
    # fabricated reference rather than a mis-cited one.
    unrelated_same_words = _record(
        "31000002",
        title="Dexmedetomidine for the prevention of delirium after non-cardiac surgery in older adults.",
        authors=["Zhang Q"],
        journal="Journal of clinical anesthesia",
        journal_abbrev="J Clin Anesth",
        year="2020",
        volume="60",
        issue="1",
        pages="50-58",
    )
    pubmed = FakePubMed([_wang_dexmedetomidine_record(record_title), unrelated_same_words])
    report = await ReferenceVerificationService(pubmed).verify_reference_list(
        "Wang Y, Li X. Dexmedetomidine for the prevention of delirium. Anesth Analg. 2019;128(3):456-62."
    )
    row = report["results"][0]

    assert row["status"] == "partial_match"
    assert row["resolution_method"] == "title_search"
    assert row["matched_article"]["pmid"] == "31000001"
    assert row["corrections"] == []
    assert "only first_author agrees" in row["corrections_withheld_reason"]
    assert any(note.startswith("No field corrections proposed: only first_author agrees") for note in row["notes"])
    queue_item = report["review_workflow"]["review_queue"][0]
    assert "no corrections are proposed" in queue_item["review_reason"]
    assert "->" not in queue_item["review_reason"]


async def test_failed_year_tolerant_search_is_source_unavailable_not_unresolved(pubmed: FakePubMed) -> None:
    pubmed.fail_queries = ("[1au]",)
    report = await ReferenceVerificationService(pubmed).verify_reference_list(
        "Chen YH, Lin WC. Processed EEG-guided discharge from the PACU. Anesth Analg. 2021;132(4):1021-1029."
    )
    row = report["results"][0]

    assert row["status"] == "source_unavailable"
    assert row["source_errors"] == [{"source": "PubMed metadata search", "error": "upstream source unavailable"}]
    assert row["attempted_strategies"] == ["ecitmatch", "title_search", "metadata_search"]
    assert report["summary"]["unresolved"] == 0


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        pytest.param(
            "Evered L, Silbert B, Knopman DS, et al. Recommendations for the nomenclature of cognitive change "
            "associated with anaesthesia and surgery-2018. Br J Anaesth. 2018 Nov;121(5):1005-1012. Epub 2018 Oct 5.",
            {"year": "2018", "journal": "Br J Anaesth", "volume": "121", "issue": "5", "first_page": "1005"},
            id="title-year-month-and-epub",
        ),
        pytest.param(
            "Punjasawadwong Y, Phongchiewboon A, Bunchungmongkol N. Bispectral index for improving anaesthetic "
            "delivery and postoperative recovery. Cochrane Database Syst Rev. 2012;(6):CD003843.",
            {"year": "2012", "volume": "", "issue": "6", "first_page": "CD003843"},
            id="cochrane-issue-only",
        ),
        pytest.param(
            "Wildes TS, Mickle AM, Ben Abdallah A, et al. Effect of EEG-guided anesthetic administration: the "
            "ENGAGES trial. JAMA. 2019 Feb 5;321(5):473-483. doi: 10.1001/jama.2018.22005. PMID: 30721296.",
            {
                "year": "2019",
                "journal": "JAMA",
                "volume": "321",
                "first_page": "473",
                "authors": ["Wildes", "Mickle", "Ben Abdallah"],
                "doi": "10.1001/jama.2018.22005",
                "pmid": "30721296",
            },
            id="vancouver-day-doi-pmid",
        ),
        pytest.param(
            "Müller K, Svensson P. Emergence trajectories. Br J Anaesth. 2019;123(2):e310-e318.",
            {"first_author": "Müller", "first_page": "e310", "volume": "123"},
            id="diacritic-author-e-page",
        ),
        pytest.param(
            "Evered, L., Silbert, B., Knopman, D. S., & Scott, D. A. (2018). Recommendations for the nomenclature "
            "of cognitive change associated with anaesthesia and surgery-2018. British Journal of Anaesthesia, "
            "121(5), 1005–1012. https://doi.org/10.1016/j.bja.2017.11.087",
            {
                "year": "2018",
                "journal": "British Journal of Anaesthesia",
                "volume": "121",
                "first_page": "1005",
                "authors": ["Evered", "Silbert", "Knopman", "Scott"],
            },
            id="apa-author-year",
        ),
        pytest.param(
            "Wildes TS, et al. Effect of EEG guidance on delirium. JAMA. Published online January 22, 2019.",
            {"year": "2019", "journal": "JAMA", "title": "Effect of EEG guidance on delirium"},
            id="published-online",
        ),
        pytest.param(
            "Aldrete J. A. The post-anesthesia recovery score revisited. J Clin Anesth. 1995;7(1):89-91.",
            {"first_author": "Aldrete", "title": "The post-anesthesia recovery score revisited"},
            id="dotted-initials",
        ),
        pytest.param(
            "Smith J. Is it safe? A trial of 2.5 mg doses. Lancet. 2018;391(10120):S5-S10.",
            {"title": "Is it safe? A trial of 2.5 mg doses", "journal": "Lancet", "first_page": "S5"},
            id="question-and-decimal-title",
        ),
        pytest.param(
            "Smith J. Outcomes 2010-2015 in a registry. Lancet 2018;391:1-5.",
            {"year": "2018", "journal": "Lancet", "title": "Outcomes 2010-2015 in a registry"},
            id="title-year-range-journal-without-period",
        ),
        pytest.param(
            "Smith J. Trends from 1990 to 2010. Lancet.",
            {"year": "", "journal": "Lancet", "title": "Trends from 1990 to 2010"},
            id="no-publication-year",
        ),
        pytest.param(
            "Smith J. Example title. Science. 2024;12:1-9. Erratum in: Science. 2025;13:100.",
            {"year": "2024", "volume": "12", "first_page": "1"},
            id="erratum-after-locator",
        ),
        pytest.param(
            "Doe A. (Re)thinking recovery scores. J Med Internet Res [Internet]. 2020 Mar;22(3):e15201.",
            {"title": "(Re)thinking recovery scores", "journal": "J Med Internet Res", "first_page": "e15201"},
            id="leading-parenthesis-and-internet-marker",
        ),
        pytest.param(
            "Wildes TS. JAMA. 2018;321(5):473-483.",
            {"first_author": "Wildes", "journal": "JAMA", "title": ""},
            id="all-caps-journal-is-not-initials",
        ),
        pytest.param(
            "Wildes TS, et al. Effect of EEG guidance on delirium. JAMA. Published online January 22, 2019. "
            "Accessed March 1, 2020.",
            {"year": "2019", "journal": "JAMA", "title": "Effect of EEG guidance on delirium"},
            id="ama-access-date-is-not-publication-year",
        ),
        pytest.param(
            "World Health Organization. Delirium fact sheet. Published 2019. Accessed March 3, 2023.",
            {"year": "2019", "first_author": "World Health Organization"},
            id="ama-web-published-year-before-access-date",
        ),
        pytest.param(
            "Smith J. COVID-19 in 2020; 12 lessons. Anesth Analg. 2021;132(1):1-5.",
            {"year": "2021", "journal": "Anesth Analg", "volume": "132", "title": "COVID-19 in 2020; 12 lessons"},
            id="title-year-before-semicolon-number",
        ),
        pytest.param(
            "Smith J. Outcomes in 2019, 3 (n=12) cohort. BMJ. 2020;368:m1234.",
            {"year": "2020", "journal": "BMJ", "first_page": "m1234", "title": "Outcomes in 2019, 3 (n=12) cohort"},
            id="title-year-before-comma-number-parenthesis",
        ),
        pytest.param(
            "Smith J. Update of the ESC guidelines (2018) on heart failure. Eur Heart J 2019.",
            {
                "year": "2019",
                "first_author": "Smith",
                "journal": "Eur Heart J",
                "title": "Update of the ESC guidelines (2018) on heart failure",
            },
            id="parenthesised-year-inside-title",
        ),
        pytest.param(
            "Smith J. The ENGAGES Trial (2019). Lancet. 2020.",
            {"year": "2020", "journal": "Lancet", "title": "The ENGAGES Trial (2019)"},
            id="parenthesised-year-ending-title-case-title",
        ),
        pytest.param(
            "Wildes, T. S., Mickle, A. M., & Ben Abdallah, A. (2019). Effect of EEG-guided anesthetic "
            "administration. JAMA, 321(5), 473-483.",
            {
                "year": "2019",
                "authors": ["Wildes", "Mickle", "Ben Abdallah"],
                "journal": "JAMA",
                "volume": "321",
                "first_page": "473",
            },
            id="apa-dotted-initials-before-parenthesised-year",
        ),
        pytest.param(
            "Smith J, Jones K (2019a) Title of the study. Anaesthesia 74:1-5",
            {"year": "2019", "authors": ["Smith", "Jones"], "journal": "Anaesthesia", "first_page": "1"},
            id="harvard-parenthesised-year",
        ),
    ],
)
def test_parser_reads_citation_position_fields(reference: str, expected: dict[str, Any], pubmed: FakePubMed) -> None:
    parsed = ReferenceVerificationService(pubmed).parse_reference(reference, index=1).to_dict()

    assert {key: parsed[key] for key in expected} == expected
