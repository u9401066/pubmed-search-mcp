"""
Entrez Search Module - Core Search Functionality

Provides search and fetch operations using esearch and efetch.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal, cast

from Bio import Entrez

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.provider_payload import has_provider_error_envelope

from .base import (
    DEFAULT_ENTREZ_TOOL,
    NCBIProviderSchemaError,
    SearchStrategy,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
    run_entrez_callable,
)

logger = logging.getLogger(__name__)

# When the number of requested IDs exceeds this threshold the main search flow
# automatically switches to History-Server-based efetch, which avoids URL-length
# limits and is more efficient for large result sets.
_HISTORY_BATCH_THRESHOLD = 200


MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
MAX_SEARCH_LIMIT = 10_000
MIN_PUBLICATION_YEAR = 1000
MAX_PUBLICATION_YEAR = 2100


# ============================================================================
# PubMed Advanced Filters - Based on official PubMed Help documentation
# https://pubmed.ncbi.nlm.nih.gov/help/
# ============================================================================

# Age Group Filters (MeSH-based)
AGE_GROUP_FILTERS = {
    "newborn": '"Infant, Newborn"[MeSH]',  # 0-1 month
    "infant": '"Infant"[MeSH]',  # 1-23 months
    "preschool": '"Child, Preschool"[MeSH]',  # 2-5 years
    "child": '"Child"[MeSH]',  # 6-12 years
    "adolescent": '"Adolescent"[MeSH]',  # 13-18 years
    "young_adult": '"Young Adult"[MeSH]',  # 19-24 years
    "adult": '"Adult"[MeSH]',  # 19+ years (general)
    "middle_aged": '"Middle Aged"[MeSH]',  # 45-64 years
    "aged": '"Aged"[MeSH]',  # 65+ years
    "aged_80": '"Aged, 80 and over"[MeSH]',  # 80+ years
}

# Sex Filters (MeSH-based)
SEX_FILTERS = {
    "male": '"Male"[MeSH]',
    "female": '"Female"[MeSH]',
}

# Species Filters
SPECIES_FILTERS = {
    "humans": '"Humans"[MeSH]',
    "animals": '"Animals"[MeSH]',
}

# Language Filters (common languages)
LANGUAGE_FILTERS = {
    "english": "eng[la]",
    "chinese": "chi[la]",
    "japanese": "jpn[la]",
    "german": "ger[la]",
    "french": "fre[la]",
    "spanish": "spa[la]",
    "korean": "kor[la]",
    "italian": "ita[la]",
    "portuguese": "por[la]",
    "russian": "rus[la]",
}

# Clinical Query Filters (validated PubMed search strategies)
# Reference: https://www.ncbi.nlm.nih.gov/pubmed/clinical
# Correct syntax: (Category/Scope[filter]) where Scope is Broad or Narrow
CLINICAL_QUERY_FILTERS = {
    # Broad = high sensitivity (more results, may include less relevant)
    # Narrow = high specificity (fewer results, more precise)
    "therapy": "(Therapy/Broad[filter])",
    "therapy_narrow": "(Therapy/Narrow[filter])",
    "diagnosis": "(Diagnosis/Broad[filter])",
    "diagnosis_narrow": "(Diagnosis/Narrow[filter])",
    "prognosis": "(Prognosis/Broad[filter])",
    "prognosis_narrow": "(Prognosis/Narrow[filter])",
    "etiology": "(Etiology/Broad[filter])",
    "etiology_narrow": "(Etiology/Narrow[filter])",
    "clinical_prediction": "(Clinical Prediction Guides/Broad[filter])",
    "clinical_prediction_narrow": "(Clinical Prediction Guides/Narrow[filter])",
}

# MeSH Subheadings (abbreviations for /subheading syntax)
# Reference: https://www.nlm.nih.gov/mesh/subhierarchy.html
MESH_SUBHEADINGS = {
    "therapy": "/therapy",
    "diagnosis": "/diagnosis",
    "drug_therapy": "/drug therapy",
    "adverse_effects": "/adverse effects",
    "surgery": "/surgery",
    "prevention": "/prevention & control",
    "etiology": "/etiology",
    "epidemiology": "/epidemiology",
    "mortality": "/mortality",
    "complications": "/complications",
    "physiopathology": "/physiopathology",
    "metabolism": "/metabolism",
    "genetics": "/genetics",
    "pharmacology": "/pharmacology",
    "therapeutic_use": "/therapeutic use",
    "toxicity": "/toxicity",
    "administration": "/administration & dosage",
    "methods": "/methods",
    "instrumentation": "/instrumentation",
    "nursing": "/nursing",
    "rehabilitation": "/rehabilitation",
    "classification": "/classification",
}


class SearchMixin:
    """
    Mixin providing core search functionality.

    Methods:
        search_page: Search PubMed with various filters and strategies
        fetch_details: Fetch complete article details by PMID
        filter_results: Filter results by sample size
    """

    async def search_page(
        self,
        query: str,
        limit: int = 5,
        min_year: int | None = None,
        max_year: int | None = None,
        article_type: str | None = None,
        strategy: str = "relevance",
        age_group: str | None = None,
        sex: str | None = None,
        species: str | None = None,
        language: str | None = None,
        clinical_query: str | None = None,
        detail_level: Literal["summary", "full"] = "full",
    ) -> SourceSearchPage[dict[str, Any]]:
        """
        Search PubMed and return one typed provider page.

        This is the sole PubMed search contract. Article rows never carry
        transport metadata, and a successful zero-result search is represented
        by ``items=[]`` rather than a metadata-only pseudo article. Invalid
        request values fail before any Entrez operation is attempted.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.
            min_year: Inclusive minimum publication year.
            max_year: Inclusive maximum publication year.
            article_type: Type of article (e.g., "Review", "Clinical Trial").
            strategy: Search strategy ("recent", "most_cited", "relevance", "impact", "agent_decided").
            age_group: Age group filter. Options:
                       "newborn" (0-1mo), "infant" (1-23mo), "preschool" (2-5y),
                       "child" (6-12y), "adolescent" (13-18y), "young_adult" (19-24y),
                       "adult" (19+), "middle_aged" (45-64y), "aged" (65+), "aged_80" (80+)
            sex: Sex filter. Options: "male", "female"
            species: Species filter. Options: "humans", "animals"
            language: Language filter. Options: "english", "chinese", "japanese",
                      "german", "french", "spanish", "korean", etc.
            clinical_query: Clinical query filter. Options:
                           "therapy", "diagnosis", "prognosis", "etiology", "clinical_prediction"
                           These are validated PubMed clinical query strategies.
            detail_level: Controls how much data is fetched per article.
                          - "full" (default): EFetch for complete records including abstract,
                            MeSH terms, affiliations. Best quality, slower.
                          - "summary": ESummary for lightweight metadata (title, authors,
                            journal, year, DOI). Best for result lists where full abstracts
                            are not immediately needed.

        Returns:
            A ``SourceSearchPage`` containing article dictionaries plus count,
            executed-query, retrieval-mode, and materialization provenance.
        """
        full_query, sort_param = self._compile_search_request(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            article_type=article_type,
            strategy=strategy,
            age_group=age_group,
            sex=sex,
            species=species,
            language=language,
            clinical_query=clinical_query,
            detail_level=detail_level,
        )
        executed_query: str | None = None
        query_executed = False
        try:
            # Step 1: Search for IDs with retry (usehistory=y for large requests)
            executed_query = full_query
            query_executed = True
            id_list, total_count, webenv, query_key = await self._search_ids(full_query, limit, sort_param)

            # Step 2: Fetch article records.
            # - "summary" mode: ESummary (fast, lightweight metadata only)
            # - "full" mode: EFetch via History Server when IDs are many, direct otherwise
            if detail_level == "summary":
                # quick_fetch_summary is defined in UtilsMixin; resolved via MRO.
                results = await cast("Any", self).quick_fetch_summary(id_list[:limit])
            elif webenv and query_key and len(id_list) >= _HISTORY_BATCH_THRESHOLD:
                # Auto History Server route: avoids large URL ID strings
                raw = await self._fetch_articles(id_list, webenv=webenv, query_key=query_key)
                results = self._parse_fetch_results(raw, expected_pmids=id_list)
            else:
                results = await self.fetch_details(id_list)

            final_results = results[:limit]
            self._validate_search_response(total_count, final_results)
            return SourceSearchPage(
                source="pubmed",
                items=final_results,
                total=total_count,
                query=executed_query,
                mode=strategy,
                metadata={
                    "logical_query": query,
                    "physical_query": executed_query,
                    "query_executed": True,
                    "provider_sort": sort_param,
                    "date_contract": "publication_year",
                    "min_year": min_year,
                    "max_year": max_year,
                    "detail_level": detail_level,
                    "requested_limit": limit,
                    "materialized_count": len(final_results),
                    "bounded": total_count > len(final_results),
                    "continuation_supported": False,
                },
            )

        except Exception as exc:
            raise_ncbi_infrastructure_error(
                "search",
                exc,
                execution_metadata={
                    "physical_query": executed_query if query_executed else None,
                    "query_executed": query_executed,
                },
            )

    @staticmethod
    def _compile_search_request(
        *,
        query: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        article_type: str | None,
        strategy: str,
        age_group: str | None,
        sex: str | None,
        species: str | None,
        language: str | None,
        clinical_query: str | None,
        detail_level: str,
    ) -> tuple[str, str]:
        """Validate one canonical request and compile its PubMed query."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_SEARCH_LIMIT}")
        for field_name, year in (("min_year", min_year), ("max_year", max_year)):
            if year is not None and (
                not isinstance(year, int)
                or isinstance(year, bool)
                or not MIN_PUBLICATION_YEAR <= year <= MAX_PUBLICATION_YEAR
            ):
                raise ValueError(
                    f"{field_name} must be an integer between {MIN_PUBLICATION_YEAR} and {MAX_PUBLICATION_YEAR}"
                )
        if min_year is not None and max_year is not None and min_year > max_year:
            raise ValueError("min_year must not exceed max_year")
        if article_type is not None and (not isinstance(article_type, str) or not article_type.strip()):
            raise ValueError("article_type must be a non-empty string or None")

        allowed_strategies = frozenset(member.value for member in SearchStrategy)
        if not isinstance(strategy, str) or strategy not in allowed_strategies:
            raise ValueError(f"strategy must be one of: {', '.join(sorted(allowed_strategies))}")
        if detail_level not in {"summary", "full"}:
            raise ValueError("detail_level must be one of: full, summary")

        filters = (
            ("age_group", age_group, AGE_GROUP_FILTERS),
            ("sex", sex, SEX_FILTERS),
            ("species", species, SPECIES_FILTERS),
            ("language", language, LANGUAGE_FILTERS),
            ("clinical_query", clinical_query, CLINICAL_QUERY_FILTERS),
        )
        for field_name, value, allowed in filters:
            if value is not None and (not isinstance(value, str) or value not in allowed):
                raise ValueError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")

        sort_param = "pub_date" if strategy == SearchStrategy.RECENT.value else "relevance"
        full_query = query
        if min_year is not None or max_year is not None:
            date_range = f"{min_year or MIN_PUBLICATION_YEAR}/01/01:{max_year or MAX_PUBLICATION_YEAR}/12/31[dp]"
            full_query += f" AND {date_range}"
        if article_type is not None:
            full_query += f' AND "{article_type}"[pt]'
        if age_group is not None:
            full_query += f" AND {AGE_GROUP_FILTERS[age_group]}"
        if sex is not None:
            full_query += f" AND {SEX_FILTERS[sex]}"
        if species is not None:
            full_query += f" AND {SPECIES_FILTERS[species]}"
        if language is not None:
            full_query += f" AND {LANGUAGE_FILTERS[language]}"
        if clinical_query is not None:
            full_query += f" AND {CLINICAL_QUERY_FILTERS[clinical_query]}"

        from pubmed_search.application.search.query_validator import validate_query

        validation = validate_query(full_query)
        if not validation.is_valid:
            raise ValueError("query failed PubMed syntax validation")
        if validation.has_warnings:
            logger.debug("PubMed query syntax validation found %s warning(s)", len(validation.warnings))
        return full_query, sort_param

    @staticmethod
    def _validate_search_response(total_count: object, articles: object) -> None:
        """Reject malformed provider values before constructing a typed page."""
        if not isinstance(articles, list):
            raise TypeError("NCBI returned an invalid article collection")
        if not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < len(articles):
            raise TypeError("NCBI returned an invalid search total")
        if any(not isinstance(article, dict) or not str(article.get("pmid") or "").strip() for article in articles):
            raise TypeError("NCBI returned an invalid article collection")

    async def _search_ids(self, query: str, retmax: int, sort: str) -> tuple[list[str], int, str, str]:
        """Search for PubMed IDs using History Server by default.

        Using ``usehistory="y"`` stores the result set on NCBI servers so that
        the subsequent efetch can reference it via WebEnv/QueryKey instead of
        sending a potentially very long ID list over the wire.

        Returns:
            Tuple of ``(id_list, total_count, webenv, query_key)``.
        """
        api_key = getattr(self, "_api_key", None)
        email = getattr(self, "_email", None)
        tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

        async def do_search() -> tuple[list[str], int, str, str]:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="pubmed",
                term=query,
                retmax=retmax,
                sort=sort,
                usehistory="y",
                email=email,
                api_key=api_key,
                tool=tool,
            )
            try:
                record: Any = await asyncio.to_thread(Entrez.read, handle)
            finally:
                handle.close()

            # Check NCBI WarningList for query translation issues
            warning_list = record.get("WarningList", {})
            if warning_list:
                for warn_type, warn_msgs in warning_list.items():
                    if isinstance(warn_msgs, list) and warn_msgs:
                        logger.warning("NCBI %s returned %s warning message(s)", warn_type, len(warn_msgs))

            translation_set = record.get("TranslationSet", [])
            if translation_set:
                logger.debug("NCBI translated %s query term(s)", len(translation_set))

            total_count = int(record.get("Count", 0))
            webenv = record.get("WebEnv", "")
            query_key = record.get("QueryKey", "")
            return record["IdList"], total_count, webenv, query_key

        return await execute_entrez_operation(
            do_search,
            api_key=api_key,
            service_name="ncbi-search:esearch",
            timeout=45.0,
            max_attempts=MAX_RETRIES,
            base_delay=float(RETRY_DELAY),
        )

    async def _fetch_articles(self, id_list: list[str], *, webenv: str = "", query_key: str = "") -> Any:
        """Fetch PubMed articles with retry on transient errors.

        When *webenv* and *query_key* are provided the efetch call references the
        stored History Server result set instead of sending the ID list in the
        URL, which avoids URL-length limits for large requests.
        """
        api_key = getattr(self, "_api_key", None)
        email = getattr(self, "_email", None)
        tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

        async def do_fetch() -> Any:
            kwargs: dict[str, Any] = {
                "db": "pubmed",
                "retmode": "xml",
                "email": email,
                "api_key": api_key,
                "tool": tool,
            }
            if webenv and query_key:
                # Prefer History Server reference to avoid long URL ID strings
                kwargs["webenv"] = webenv
                kwargs["query_key"] = query_key
                kwargs["retmax"] = len(id_list)
            else:
                kwargs["id"] = id_list
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.efetch,
                **kwargs,
            )
            try:
                return await asyncio.to_thread(Entrez.read, handle)
            finally:
                handle.close()

        return await execute_entrez_operation(
            do_fetch,
            api_key=api_key,
            service_name="ncbi-search:efetch",
            timeout=60.0,
            max_attempts=MAX_RETRIES,
            base_delay=float(RETRY_DELAY),
        )

    async def fetch_details(self, id_list: list[str]) -> list[dict[str, Any]]:
        """
        Fetch complete details for a list of PMIDs.

        Args:
            id_list: List of PubMed IDs.

        Returns:
            List of dictionaries containing article details including:
            - pmid, title, authors, authors_full
            - journal, journal_abbrev, year, month, day
            - volume, issue, pages, doi, pmc_id
            - abstract, keywords, mesh_terms
        """
        if not id_list:
            return []

        try:
            papers = await self._fetch_articles(id_list)
            return self._parse_fetch_results(papers, expected_pmids=id_list)
        except NCBIProviderSchemaError:
            raise
        except Exception as exc:
            raise_ncbi_infrastructure_error("fetch_details", exc)

    def _parse_fetch_results(
        self,
        papers: Any,
        *,
        expected_pmids: list[str],
    ) -> list[dict[str, Any]]:
        """Parse one strict EFetch envelope while preserving explicit empty success."""
        if (
            not isinstance(papers, dict)
            or has_provider_error_envelope(papers)
            or "PubmedArticle" not in papers
            or not isinstance(papers["PubmedArticle"], list)
        ):
            raise NCBIProviderSchemaError("fetch_details")

        try:
            results = [self._parse_pubmed_article(article) for article in papers["PubmedArticle"]]
        except Exception:
            raise NCBIProviderSchemaError("fetch_details") from None

        expected = set(expected_pmids)
        returned_pmids: list[str] = []
        for result in results:
            pmid = result.get("pmid")
            if (
                not isinstance(pmid, str)
                or not pmid.isascii()
                or not pmid.isdigit()
                or int(pmid) <= 0
                or pmid not in expected
            ):
                raise NCBIProviderSchemaError("fetch_details")
            returned_pmids.append(pmid)
        if len(returned_pmids) != len(set(returned_pmids)):
            raise NCBIProviderSchemaError("fetch_details")
        return results

    def _parse_pubmed_article(self, article: dict) -> dict[str, Any]:
        """
        Parse a single PubMed article record into a structured dictionary.

        Args:
            article: Raw PubMed article data from Entrez.

        Returns:
            Structured article data dictionary.
        """
        if not isinstance(article, dict):
            raise TypeError("NCBI returned an invalid PubMed article")
        medline_citation = article["MedlineCitation"]
        if not isinstance(medline_citation, dict):
            raise TypeError("NCBI returned an invalid Medline citation")
        article_data = medline_citation["Article"]
        if not isinstance(article_data, dict):
            raise TypeError("NCBI returned invalid PubMed article metadata")
        pubmed_data = article.get("PubmedData", {})

        title = article_data.get("ArticleTitle", "No title")

        # Extract authors with full details
        authors, authors_full = self._extract_authors(article_data)

        # Extract abstract
        abstract_text = self._extract_abstract(article_data)

        # Extract Journal info (includes ISSN)
        journal_info = self._extract_journal_info(article_data)

        # Extract identifiers (DOI, PMC ID)
        doi, pmc_id = self._extract_identifiers(pubmed_data)

        # Extract PMID
        pmid = str(medline_citation.get("PMID", ""))

        # Extract keywords and MeSH terms
        keywords = self._extract_keywords(medline_citation)
        mesh_terms = self._extract_mesh_terms(medline_citation)

        # Extract language
        language = self._extract_language(article_data)

        # Extract publication types
        publication_types = self._extract_publication_types(article_data)

        return {
            "pmid": pmid,
            "title": title,
            "authors": authors,
            "authors_full": authors_full,
            "abstract": abstract_text,
            "keywords": keywords,
            "mesh_terms": mesh_terms,
            "doi": doi,
            "pmc_id": pmc_id,
            "language": language,
            "publication_types": publication_types,
            **journal_info,
        }

    def _extract_authors(self, article_data: dict) -> tuple:
        """Extract author information from article data."""
        authors = []
        authors_full = []

        if "AuthorList" in article_data:
            for author in article_data["AuthorList"]:
                if "LastName" in author:
                    last_name = author["LastName"]
                    fore_name = author.get("ForeName", "")
                    initials = author.get("Initials", "")

                    # Extract affiliations if available
                    affiliations = []
                    if "AffiliationInfo" in author:
                        for aff_info in author["AffiliationInfo"]:
                            if "Affiliation" in aff_info:
                                affiliations.append(aff_info["Affiliation"])

                    authors.append(f"{last_name} {fore_name}".strip())
                    author_entry = {
                        "last_name": last_name,
                        "fore_name": fore_name,
                        "initials": initials,
                    }
                    if affiliations:
                        author_entry["affiliations"] = affiliations
                    authors_full.append(author_entry)
                elif "CollectiveName" in author:
                    authors.append(author["CollectiveName"])
                    authors_full.append({"collective_name": author["CollectiveName"]})

        return authors, authors_full

    def _extract_abstract(self, article_data: dict) -> str:
        """Extract abstract text from article data."""
        if "Abstract" in article_data and "AbstractText" in article_data["Abstract"]:
            abstract_parts = article_data["Abstract"]["AbstractText"]
            if isinstance(abstract_parts, list):
                return " ".join([str(part) for part in abstract_parts])
            return str(abstract_parts)
        return ""

    def _extract_journal_info(self, article_data: dict) -> dict[str, str]:
        """Extract journal information from article data."""
        journal_data = article_data.get("Journal", {})
        journal_issue = journal_data.get("JournalIssue", {})
        pub_date = journal_issue.get("PubDate", {})

        year = pub_date.get("Year", "")
        month = pub_date.get("Month", "")
        day = pub_date.get("Day", "")

        if not year and "MedlineDate" in pub_date:
            year_match = re.search(r"(\d{4})", pub_date["MedlineDate"])
            if year_match:
                year = year_match.group(1)

        pagination = article_data.get("Pagination", {})

        # Extract ISSN (electronic preferred, then print)
        issn = ""
        if "ISSN" in journal_data:
            issn_data = journal_data["ISSN"]
            if isinstance(issn_data, str):
                issn = issn_data
            elif hasattr(issn_data, "__str__"):
                issn = str(issn_data)

        # Format publication date
        pub_date_str = ""
        if year:
            pub_date_str = year
            if month:
                pub_date_str = f"{year}/{month}"
                if day:
                    pub_date_str = f"{year}/{month}/{day}"

        return {
            "journal": journal_data.get("Title", "Unknown Journal"),
            "journal_abbrev": journal_data.get("ISOAbbreviation", ""),
            "issn": issn,
            "year": year,
            "month": month,
            "day": day,
            "pub_date": pub_date_str,
            "volume": journal_issue.get("Volume", ""),
            "issue": journal_issue.get("Issue", ""),
            "pages": pagination.get("MedlinePgn", ""),
        }

    def _extract_language(self, article_data: dict) -> str:
        """Extract article language from article data."""
        language = article_data.get("Language", [])
        if isinstance(language, list) and language:
            return language[0]
        if isinstance(language, str):
            return language
        return "eng"

    def _extract_publication_types(self, article_data: dict) -> list[str]:
        """Extract publication types from article data."""
        pub_types = []
        pub_type_list = article_data.get("PublicationTypeList", [])
        for pt in pub_type_list:
            if hasattr(pt, "__str__"):
                pub_types.append(str(pt))
            elif isinstance(pt, str):
                pub_types.append(pt)
        return pub_types

    def _extract_identifiers(self, pubmed_data: dict) -> tuple:
        """Extract DOI and PMC ID from article identifiers."""
        doi = ""
        pmc_id = ""

        article_ids = pubmed_data.get("ArticleIdList", [])
        for aid in article_ids:
            if hasattr(aid, "attributes"):
                if aid.attributes.get("IdType") == "doi":
                    doi = str(aid)
                elif aid.attributes.get("IdType") == "pmc":
                    pmc_id = str(aid)

        return doi, pmc_id

    def _extract_keywords(self, medline_citation: dict) -> list[str]:
        """Extract keywords from MedlineCitation."""
        keywords = []
        if "KeywordList" in medline_citation:
            for kw_list in medline_citation["KeywordList"]:
                keywords.extend([str(kw) for kw in kw_list])
        return keywords

    def _extract_mesh_terms(self, medline_citation: dict) -> list[str]:
        """Extract MeSH terms from MedlineCitation."""
        mesh_terms = []
        if "MeshHeadingList" in medline_citation:
            for mesh in medline_citation["MeshHeadingList"]:
                if "DescriptorName" in mesh:
                    mesh_terms.append(str(mesh["DescriptorName"]))
        return mesh_terms

    def filter_results(self, results: list[dict[str, Any]], min_sample_size: int | None = None) -> list[dict[str, Any]]:
        """
        Filter results based on abstract content.

        Args:
            results: List of paper details.
            min_sample_size: Minimum number of participants mentioned.

        Returns:
            Filtered list of papers meeting the criteria.
        """
        if not min_sample_size:
            return results

        filtered = []
        patterns = [
            r"n\s*=\s*(\d+)",
            r"(\d+)\s*patients",
            r"(\d+)\s*participants",
            r"(\d+)\s*subjects",
        ]

        for paper in results:
            abstract = paper.get("abstract", "").lower()
            max_n = 0

            for p in patterns:
                matches = re.findall(p, abstract)
                for m in matches:
                    try:
                        val = int(m)
                        max_n = max(max_n, val)
                    except ValueError:
                        pass

            if max_n >= min_sample_size:
                filtered.append(paper)

        return filtered
