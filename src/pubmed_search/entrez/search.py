"""
Entrez Search Module - Core Search Functionality

Provides search and fetch operations using esearch and efetch.
"""

import time
import logging
from Bio import Entrez
from typing import List, Dict, Any, Optional
import re

from .base import SearchStrategy, _rate_limit

logger = logging.getLogger(__name__)

# Retry settings for transient NCBI errors
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _retry_on_error(func):
    """Decorator to retry Entrez operations on transient errors."""
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Check for transient NCBI errors
                if any(msg in error_str for msg in [
                    "Database is not supported",
                    "Backend failed",
                    "temporarily unavailable",
                    "Service unavailable",
                    "rate limit",
                    "Too Many Requests"
                ]):
                    last_error = e
                    wait_time = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"NCBI transient error (attempt {attempt + 1}/{MAX_RETRIES}): {error_str}")
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
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
    
    def search(
        self, 
        query: str, 
        limit: int = 5, 
        min_year: Optional[int] = None, 
        max_year: Optional[int] = None, 
        article_type: Optional[str] = None, 
        strategy: str = "relevance",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        date_type: str = "edat"
    ) -> List[Dict[str, Any]]:
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
                full_query += f" AND \"{article_type}\"[pt]"
            
            # Step 1: Search for IDs with retry
            id_list = self._search_ids_with_retry(full_query, limit * 2, sort_param)
            
            results = self.fetch_details(id_list)
            
            return results[:limit]

        except Exception as e:
            return [{"error": str(e)}]

    def _search_ids_with_retry(self, query: str, retmax: int, sort: str) -> List[str]:
        """Search for PubMed IDs with retry on transient errors."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                _rate_limit()  # Rate limiting before API call
                handle = Entrez.esearch(db="pubmed", term=query, retmax=retmax, sort=sort)
                record = Entrez.read(handle)
                handle.close()
                return record["IdList"]
            except Exception as e:
                error_str = str(e)
                if any(msg in error_str.lower() for msg in [
                    "database is not supported",
                    "backend failed",
                    "temporarily unavailable",
                    "service unavailable",
                    "rate limit",
                    "too many requests",
                    "server error"
                ]):
                    last_error = e
                    wait_time = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"NCBI transient error (attempt {attempt + 1}/{MAX_RETRIES}): {error_str}")
                    time.sleep(wait_time)
                else:
                    raise
        raise last_error if last_error else Exception("Search failed after retries")

    def _fetch_with_retry(self, id_list: List[str]):
        """Fetch PubMed articles with retry on transient errors."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                _rate_limit()  # Rate limiting before API call
                handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
                papers = Entrez.read(handle)
                handle.close()
                return papers
            except Exception as e:
                error_str = str(e)
                if any(msg in error_str.lower() for msg in [
                    "database is not supported",
                    "backend failed",
                    "temporarily unavailable",
                    "service unavailable",
                    "rate limit",
                    "too many requests",
                    "server error"
                ]):
                    last_error = e
                    wait_time = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"NCBI transient error (attempt {attempt + 1}/{MAX_RETRIES}): {error_str}")
                    time.sleep(wait_time)
                else:
                    raise
        raise last_error if last_error else Exception("Fetch failed after retries")

    def fetch_details(self, id_list: List[str]) -> List[Dict[str, Any]]:
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
            papers = self._fetch_with_retry(id_list)
            
            results = []
            if 'PubmedArticle' in papers:
                for article in papers['PubmedArticle']:
                    result = self._parse_pubmed_article(article)
                    results.append(result)
            
            return results
        except Exception as e:
            return [{"error": str(e)}]

    def _parse_pubmed_article(self, article: Dict) -> Dict[str, Any]:
        """
        Parse a single PubMed article record into a structured dictionary.
        
        Args:
            article: Raw PubMed article data from Entrez.
            
        Returns:
            Structured article data dictionary.
        """
        medline_citation = article['MedlineCitation']
        article_data = medline_citation['Article']
        pubmed_data = article.get('PubmedData', {})
        
        title = article_data.get('ArticleTitle', 'No title')
        
        # Extract authors with full details
        authors, authors_full = self._extract_authors(article_data)
        
        # Extract abstract
        abstract_text = self._extract_abstract(article_data)
        
        # Extract Journal info (includes ISSN)
        journal_info = self._extract_journal_info(article_data)
        
        # Extract identifiers (DOI, PMC ID)
        doi, pmc_id = self._extract_identifiers(pubmed_data)
        
        # Extract PMID
        pmid = str(medline_citation.get('PMID', ''))
        
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
            **journal_info
        }

    def _extract_authors(self, article_data: Dict) -> tuple:
        """Extract author information from article data."""
        authors = []
        authors_full = []
        
        if 'AuthorList' in article_data:
            for author in article_data['AuthorList']:
                if 'LastName' in author:
                    last_name = author['LastName']
                    fore_name = author.get('ForeName', '')
                    initials = author.get('Initials', '')
                    authors.append(f"{last_name} {fore_name}".strip())
                    authors_full.append({
                        "last_name": last_name,
                        "fore_name": fore_name,
                        "initials": initials
                    })
                elif 'CollectiveName' in author:
                    authors.append(author['CollectiveName'])
                    authors_full.append({"collective_name": author['CollectiveName']})
        
        return authors, authors_full

    def _extract_abstract(self, article_data: Dict) -> str:
        """Extract abstract text from article data."""
        if 'Abstract' in article_data and 'AbstractText' in article_data['Abstract']:
            abstract_parts = article_data['Abstract']['AbstractText']
            if isinstance(abstract_parts, list):
                return " ".join([str(part) for part in abstract_parts])
            return str(abstract_parts)
        return ""

    def _extract_journal_info(self, article_data: Dict) -> Dict[str, str]:
        """Extract journal information from article data."""
        journal_data = article_data.get('Journal', {})
        journal_issue = journal_data.get('JournalIssue', {})
        pub_date = journal_issue.get('PubDate', {})
        
        year = pub_date.get('Year', '')
        month = pub_date.get('Month', '')
        day = pub_date.get('Day', '')
        
        if not year and 'MedlineDate' in pub_date:
            year_match = re.search(r'(\d{4})', pub_date['MedlineDate'])
            if year_match:
                year = year_match.group(1)
        
        pagination = article_data.get('Pagination', {})
        
        # Extract ISSN (electronic preferred, then print)
        issn = ''
        if 'ISSN' in journal_data:
            issn_data = journal_data['ISSN']
            if isinstance(issn_data, str):
                issn = issn_data
            elif hasattr(issn_data, '__str__'):
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
            "journal": journal_data.get('Title', 'Unknown Journal'),
            "journal_abbrev": journal_data.get('ISOAbbreviation', ''),
            "issn": issn,
            "year": year,
            "month": month,
            "day": day,
            "pub_date": pub_date_str,
            "volume": journal_issue.get('Volume', ''),
            "issue": journal_issue.get('Issue', ''),
            "pages": pagination.get('MedlinePgn', '')
        }

    def _extract_language(self, article_data: Dict) -> str:
        """Extract article language from article data."""
        language = article_data.get('Language', [])
        if isinstance(language, list) and language:
            return language[0]
        elif isinstance(language, str):
            return language
        return "eng"

    def _extract_publication_types(self, article_data: Dict) -> List[str]:
        """Extract publication types from article data."""
        pub_types = []
        pub_type_list = article_data.get('PublicationTypeList', [])
        for pt in pub_type_list:
            if hasattr(pt, '__str__'):
                pub_types.append(str(pt))
            elif isinstance(pt, str):
                pub_types.append(pt)
        return pub_types

    def _extract_identifiers(self, pubmed_data: Dict) -> tuple:
        """Extract DOI and PMC ID from article identifiers."""
        doi = ''
        pmc_id = ''
        
        article_ids = pubmed_data.get('ArticleIdList', [])
        for aid in article_ids:
            if hasattr(aid, 'attributes'):
                if aid.attributes.get('IdType') == 'doi':
                    doi = str(aid)
                elif aid.attributes.get('IdType') == 'pmc':
                    pmc_id = str(aid)
        
        return doi, pmc_id

    def _extract_keywords(self, medline_citation: Dict) -> List[str]:
        """Extract keywords from MedlineCitation."""
        keywords = []
        if 'KeywordList' in medline_citation:
            for kw_list in medline_citation['KeywordList']:
                keywords.extend([str(kw) for kw in kw_list])
        return keywords

    def _extract_mesh_terms(self, medline_citation: Dict) -> List[str]:
        """Extract MeSH terms from MedlineCitation."""
        mesh_terms = []
        if 'MeshHeadingList' in medline_citation:
            for mesh in medline_citation['MeshHeadingList']:
                if 'DescriptorName' in mesh:
                    mesh_terms.append(str(mesh['DescriptorName']))
        return mesh_terms

    def filter_results(
        self, 
        results: List[Dict[str, Any]], 
        min_sample_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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
            r"(\d+)\s*subjects"
        ]
        
        for paper in results:
            abstract = paper.get('abstract', '').lower()
            max_n = 0
            
            for p in patterns:
                matches = re.findall(p, abstract)
                for m in matches:
                    try:
                        val = int(m)
                        if val > max_n:
                            max_n = val
                    except ValueError:
                        pass
            
            if max_n >= min_sample_size:
                filtered.append(paper)
                
        return filtered
