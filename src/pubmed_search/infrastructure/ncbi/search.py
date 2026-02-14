"""
Entrez Search Module - Core Search Functionality

Provides search and fetch operations using esearch and efetch.
"""

import asyncio
import logging
import re
from typing import Any

from Bio import Entrez
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import SearchStrategy, _rate_limit

logger = logging.getLogger(__name__)

# Retry settings for transient NCBI errors
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


_RETRYABLE_MESSAGES = [
    "database is not supported",
    "backend failed",
    "temporarily unavailable",
    "service unavailable",
    "rate limit",
    "too many requests",
    "server error",
]


def _is_retryable_ncbi(error: BaseException) -> bool:
    """Check if an NCBI error is retryable."""
    error_str = str(error).lower()
    return any(msg in error_str for msg in _RETRYABLE_MESSAGES)


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


def _retry_on_error(func):
    """Decorator to retry Entrez operations on transient errors."""

    async def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Check for transient NCBI errors
                if any(
                    msg in error_str
                    for msg in [
                        "Database is not supported",
                        "Backend failed",
                        "temporarily unavailable",
                        "Service unavailable",
                        "rate limit",
                        "Too Many Requests",
                    ]
                ):
                    last_error = e
                    wait_time = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"NCBI transient error (attempt {attempt + 1}/{MAX_RETRIES}): {error_str}")
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    # Non-transient error, don't retry
                    raise
        # All retries exhausted
        raise last_error

    return wrapper


class SearchMixin:
    """
    Mixin providing core search functionality.

    Methods:
        search: Search PubMed with various filters and strategies
        fetch_details: Fetch complete article details by PMID
        filter_results: Filter results by sample size
    """

    async def search(
        self,
        query: str,
        limit: int = 5,
        min_year: int | None = None,
        max_year: int | None = None,
        article_type: str | None = None,
        strategy: str = "relevance",
        date_from: str | None = None,
        date_to: str | None = None,
        date_type: str = "edat",
        # Advanced filters (Phase 2.1)
        age_group: str | None = None,
        sex: str | None = None,
        species: str | None = None,
        language: str | None = None,
        clinical_query: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search PubMed for articles using a specific strategy.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.
            min_year: Minimum publication year (legacy, use date_from for precision).
            max_year: Maximum publication year (legacy, use date_to for precision).
            article_type: Type of article (e.g., "Review", "Clinical Trial").
            strategy: Search strategy ("recent", "most_cited", "relevance", "impact", "agent_decided").
            date_from: Precise start date in YYYY/MM/DD format (e.g., "2025/10/01").
            date_to: Precise end date in YYYY/MM/DD format (e.g., "2025/11/28").
            date_type: Date field to search. Options:
                       - "edat" (default): Entrez date (when added to PubMed) - best for finding new articles
                       - "pdat": Publication date
                       - "mdat": Modification date
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

        Returns:
            List of dictionaries containing article details.
        """
        try:
            # Map strategy to PubMed sort parameter
            sort_param = "relevance"

            if strategy == SearchStrategy.RECENT.value:
                sort_param = "pub_date"
            elif strategy == SearchStrategy.MOST_CITED.value:
                sort_param = "relevance"  # Best proxy
            elif strategy == SearchStrategy.RELEVANCE.value:
                sort_param = "relevance"
            elif strategy == SearchStrategy.IMPACT.value:
                sort_param = "relevance"  # Best proxy without IF data
            elif strategy == SearchStrategy.AGENT_DECIDED.value:
                sort_param = "relevance"

            # Construct advanced query
            full_query = query

            # Date range handling - prefer precise dates over year-only
            if date_from or date_to:
                # Use precise date format: YYYY/MM/DD
                # date_type: edat (Entrez date), pdat (Publication date), mdat (Modification date)
                start_date = date_from if date_from else "1900/01/01"
                end_date = date_to if date_to else "3000/12/31"
                date_range = f"{start_date}:{end_date}[{date_type}]"
                full_query += f" AND {date_range}"
            elif min_year or max_year:
                # Legacy year-only format
                date_range = f"{min_year or 1900}/01/01:{max_year or 3000}/12/31[dp]"
                full_query += f" AND {date_range}"

            if article_type:
                full_query += f' AND "{article_type}"[pt]'

            # === Advanced Filters (Phase 2.1) ===

            # Age group filter
            if age_group:
                age_key = age_group.lower().replace(" ", "_").replace("-", "_")
                if age_key in AGE_GROUP_FILTERS:
                    full_query += f" AND {AGE_GROUP_FILTERS[age_key]}"
                else:
                    logger.warning(
                        f"Unknown age_group: {age_group}. Valid options: {', '.join(AGE_GROUP_FILTERS.keys())}"
                    )

            # Sex filter
            if sex:
                sex_key = sex.lower()
                if sex_key in SEX_FILTERS:
                    full_query += f" AND {SEX_FILTERS[sex_key]}"
                else:
                    logger.warning(f"Unknown sex: {sex}. Valid options: male, female")

            # Species filter
            if species:
                species_key = species.lower()
                if species_key in SPECIES_FILTERS:
                    full_query += f" AND {SPECIES_FILTERS[species_key]}"
                else:
                    logger.warning(f"Unknown species: {species}. Valid options: humans, animals")

            # Language filter
            if language:
                lang_key = language.lower()
                if lang_key in LANGUAGE_FILTERS:
                    full_query += f" AND {LANGUAGE_FILTERS[lang_key]}"
                else:
                    # Try direct language code (e.g., "eng", "chi")
                    full_query += f" AND {lang_key}[la]"
                    logger.info(f"Using direct language code: {lang_key}[la]")

            # Clinical query filter (validated PubMed search strategies)
            if clinical_query:
                cq_key = clinical_query.lower().replace(" ", "_").replace("-", "_")
                if cq_key in CLINICAL_QUERY_FILTERS:
                    full_query += f" AND {CLINICAL_QUERY_FILTERS[cq_key]}"
                else:
                    logger.warning(
                        f"Unknown clinical_query: {clinical_query}. "
                        f"Valid options: {', '.join(CLINICAL_QUERY_FILTERS.keys())}"
                    )

            # Pre-flight query validation
            from pubmed_search.application.search.query_validator import (
                validate_query,
            )

            validation = validate_query(full_query)
            if not validation.is_valid:
                logger.warning(f"Query syntax issues detected: {validation.errors}. Original: {full_query}")
                if validation.corrected_query:
                    logger.info(f"Auto-corrected query: {validation.corrected_query}")
                    full_query = validation.corrected_query
            elif validation.has_warnings:
                logger.debug(f"Query warnings: {validation.warnings}")

            # Step 1: Search for IDs with retry
            id_list, total_count = await self._search_ids_with_retry(full_query, limit * 2, sort_param)

            results = await self.fetch_details(id_list)

            # Attach total count to results for caller to access
            final_results = results[:limit]
            # Store metadata in a way that doesn't break existing code
            if final_results:
                final_results[0]["_search_metadata"] = {"total_count": total_count}
            elif total_count > 0:
                # No detailed results but we have a count
                final_results = [{"_search_metadata": {"total_count": total_count}}]

            return final_results

        except Exception as e:
            return [{"error": str(e)}]

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_DELAY, min=RETRY_DELAY, max=RETRY_DELAY * 4),
        retry=retry_if_exception(_is_retryable_ncbi),
        reraise=True,
    )
    async def _search_ids_with_retry(self, query: str, retmax: int, sort: str) -> tuple:
        """Search for PubMed IDs with retry on transient errors.

        Returns:
            Tuple of (id_list, total_count) where total_count is the total number
            of articles matching the query in PubMed (not limited by retmax).
        """
        await _rate_limit()  # Rate limiting before API call
        handle = await asyncio.to_thread(Entrez.esearch, db="pubmed", term=query, retmax=retmax, sort=sort)
        record = await asyncio.to_thread(Entrez.read, handle)
        handle.close()

        # Check NCBI WarningList for query translation issues
        warning_list = record.get("WarningList", {})
        if warning_list:
            # NCBI returns warnings like QuotedPhraseNotFound,
            # OutputMessage (e.g. term not found in MeSH), etc.
            for warn_type, warn_msgs in warning_list.items():
                if isinstance(warn_msgs, list) and warn_msgs:
                    logger.warning(f"NCBI {warn_type}: {warn_msgs}")

        # Check TranslationStack for how NCBI interpreted the query
        translation_set = record.get("TranslationSet", [])
        if translation_set:
            logger.debug(f"NCBI query translation: {[(t.get('From', ''), t.get('To', '')) for t in translation_set]}")

        total_count = int(record.get("Count", 0))
        return record["IdList"], total_count

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_DELAY, min=RETRY_DELAY, max=RETRY_DELAY * 4),
        retry=retry_if_exception(_is_retryable_ncbi),
        reraise=True,
    )
    async def _fetch_with_retry(self, id_list: list[str]):
        """Fetch PubMed articles with retry on transient errors."""
        await _rate_limit()  # Rate limiting before API call
        handle = await asyncio.to_thread(Entrez.efetch, db="pubmed", id=id_list, retmode="xml")
        papers = await asyncio.to_thread(Entrez.read, handle)
        handle.close()
        return papers

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
            papers = await self._fetch_with_retry(id_list)

            results = []
            if "PubmedArticle" in papers:
                for article in papers["PubmedArticle"]:
                    result = self._parse_pubmed_article(article)
                    results.append(result)

            return results
        except Exception as e:
            return [{"error": str(e)}]

    def _parse_pubmed_article(self, article: dict) -> dict[str, Any]:
        """
        Parse a single PubMed article record into a structured dictionary.

        Args:
            article: Raw PubMed article data from Entrez.

        Returns:
            Structured article data dictionary.
        """
        medline_citation = article["MedlineCitation"]
        article_data = medline_citation["Article"]
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
