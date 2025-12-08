"""
iCite Module - NIH Citation Metrics Integration

Provides citation metrics from NIH's iCite API:
- citation_count: Total citations
- relative_citation_ratio (RCR): Field-normalized citation metric
- nih_percentile: Percentile among NIH-funded papers
- apt: Approximate Potential to Translate (clinical relevance)

API Documentation: https://icite.od.nih.gov/api
"""

import logging
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

ICITE_API_BASE = "https://icite.od.nih.gov/api/pubs"
MAX_PMIDS_PER_REQUEST = 200  # iCite API limit


class ICiteMixin:
    """
    Mixin providing iCite citation metrics functionality.
    
    Methods:
        get_citation_metrics: Get citation data for PMIDs
        enrich_with_citations: Add citation metrics to search results
    """
    
    def get_citation_metrics(
        self, 
        pmids: List[str], 
        fields: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get citation metrics from iCite API.
        
        Args:
            pmids: List of PubMed IDs
            fields: Specific fields to return (default: all citation-related)
            
        Returns:
            Dict mapping PMID -> metrics dict
        """
        if not pmids:
            return {}
        
        # Default fields for citation analysis
        if fields is None:
            fields = [
                "pmid", "year", "title", "journal",
                "citation_count", "citations_per_year",
                "relative_citation_ratio", "nih_percentile",
                "expected_citations_per_year", "field_citation_rate",
                "apt", "is_clinical", "cited_by_clin",
                "human", "animal", "molecular_cellular"
            ]
        
        results = {}
        
        # Process in batches of 200 (API limit)
        for i in range(0, len(pmids), MAX_PMIDS_PER_REQUEST):
            batch = pmids[i:i + MAX_PMIDS_PER_REQUEST]
            batch_results = self._fetch_icite_batch(batch, fields)
            results.update(batch_results)
        
        return results
    
    def _fetch_icite_batch(
        self, 
        pmids: List[str], 
        fields: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch a single batch from iCite API."""
        try:
            params = {
                "pmids": ",".join(str(p) for p in pmids),
                "fl": ",".join(fields)
            }
            
            response = requests.get(ICITE_API_BASE, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Map by PMID for easy lookup
            results = {}
            for item in data.get("data", []):
                pmid = str(item.get("pmid", ""))
                if pmid:
                    results[pmid] = item
            
            return results
            
        except requests.RequestException as e:
            logger.error(f"iCite API request failed: {e}")
            return {}
        except Exception as e:
            logger.error(f"iCite processing error: {e}")
            return {}
    
    def enrich_with_citations(
        self, 
        articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich article list with iCite citation metrics.
        
        Args:
            articles: List of article dicts (must have 'pmid' field)
            
        Returns:
            Articles with added 'icite' field containing metrics
        """
        if not articles:
            return articles
        
        # Extract PMIDs
        pmids = [str(a.get("pmid", "")) for a in articles if a.get("pmid")]
        
        if not pmids:
            return articles
        
        # Fetch metrics
        metrics = self.get_citation_metrics(pmids)
        
        # Enrich articles
        enriched = []
        for article in articles:
            pmid = str(article.get("pmid", ""))
            article_copy = article.copy()
            
            if pmid in metrics:
                article_copy["icite"] = metrics[pmid]
            
            enriched.append(article_copy)
        
        return enriched
    
    def sort_by_citations(
        self, 
        articles: List[Dict[str, Any]], 
        metric: str = "citation_count",
        descending: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Sort articles by citation metric.
        
        Args:
            articles: List of enriched articles (with 'icite' field)
            metric: Which metric to sort by:
                - citation_count: Raw citation count
                - relative_citation_ratio: Field-normalized (recommended)
                - nih_percentile: Percentile ranking
                - citations_per_year: Citation velocity
            descending: Sort high to low (default True)
            
        Returns:
            Sorted article list
        """
        def get_metric(article):
            icite = article.get("icite", {})
            value = icite.get(metric)
            # Handle None/missing values - put at end
            if value is None:
                return float("-inf") if descending else float("inf")
            return value
        
        return sorted(articles, key=get_metric, reverse=descending)
    
    def filter_by_citations(
        self,
        articles: List[Dict[str, Any]],
        min_citations: Optional[int] = None,
        min_rcr: Optional[float] = None,
        min_percentile: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Filter articles by citation thresholds.
        
        Args:
            articles: List of enriched articles
            min_citations: Minimum citation count
            min_rcr: Minimum Relative Citation Ratio
            min_percentile: Minimum NIH percentile
            
        Returns:
            Filtered article list
        """
        filtered = []
        
        for article in articles:
            icite = article.get("icite", {})
            
            # Check citation count
            if min_citations is not None:
                count = icite.get("citation_count", 0) or 0
                if count < min_citations:
                    continue
            
            # Check RCR
            if min_rcr is not None:
                rcr = icite.get("relative_citation_ratio")
                if rcr is None or rcr < min_rcr:
                    continue
            
            # Check percentile
            if min_percentile is not None:
                percentile = icite.get("nih_percentile")
                if percentile is None or percentile < min_percentile:
                    continue
            
            filtered.append(article)
        
        return filtered
