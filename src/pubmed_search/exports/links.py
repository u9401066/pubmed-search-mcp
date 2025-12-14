"""
Fulltext Links - Get links to full text articles.

This module provides convenient functions for fulltext access.
Uses existing PDFMixin from entrez module for PMC lookups.

Provides URLs for:
- PubMed Central (PMC) - Open Access
- DOI links to publisher
- Publisher direct links
"""

import logging
from typing import Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import LiteratureSearcher

logger = logging.getLogger(__name__)


def get_fulltext_links(article: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get all available fulltext links for an article (from metadata only).
    
    This is a fast function that uses existing article metadata.
    For PMC lookup by PMID, use get_fulltext_links_with_lookup().
    
    Args:
        article: Article dictionary with pmid, doi, pmc_id.
        
    Returns:
        Dictionary with available links and access info.
    """
    pmid = article.get("pmid", "")
    doi = article.get("doi", "")
    pmc_id = article.get("pmc_id", "")
    
    links = {
        "pmid": pmid,
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        "doi_url": f"https://doi.org/{doi}" if doi else None,
        "pmc_url": None,
        "pmc_pdf_url": None,
        "has_free_fulltext": False,
        "access_type": "abstract_only"
    }
    
    # Check PMC availability from metadata
    if pmc_id:
        # Clean PMC ID (remove "PMC" prefix if present)
        pmc_num = pmc_id.replace("PMC", "")
        links["pmc_url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/"
        links["pmc_pdf_url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/"
        links["has_free_fulltext"] = True
        links["access_type"] = "open_access"
    elif doi:
        # DOI available but no PMC - likely paywalled
        links["access_type"] = "subscription"
    
    return links


def get_fulltext_links_with_lookup(
    pmid: str, 
    searcher: "LiteratureSearcher"
) -> Dict[str, Any]:
    """
    Get fulltext links with PMC lookup via API.
    
    Uses existing PDFMixin.get_pmc_fulltext_url() to lookup PMC availability.
    This makes an API call, use sparingly.
    
    Args:
        pmid: PubMed ID.
        searcher: LiteratureSearcher instance (has PDFMixin).
        
    Returns:
        Dictionary with available links and access info.
    """
    links = {
        "pmid": pmid,
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "doi_url": None,
        "pmc_url": None,
        "pmc_pdf_url": None,
        "has_free_fulltext": False,
        "access_type": "abstract_only"
    }
    
    try:
        # Use existing PDFMixin method
        pmc_url = searcher.get_pmc_fulltext_url(pmid)
        
        if pmc_url:
            links["pmc_url"] = pmc_url
            links["pmc_pdf_url"] = pmc_url.rstrip('/') + "/pdf/"
            links["has_free_fulltext"] = True
            links["access_type"] = "open_access"
    except Exception as e:
        logger.warning(f"Error looking up PMC for {pmid}: {e}")
    
    return links


def get_batch_fulltext_links(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Get fulltext links for multiple articles.
    
    Args:
        articles: List of article dictionaries.
        
    Returns:
        List of link dictionaries with article info.
    """
    results = []
    
    for article in articles:
        links = get_fulltext_links(article)
        links["title"] = article.get("title", "")[:100]  # Truncate for display
        results.append(links)
    
    return results


def summarize_access(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarize fulltext access for a list of articles.
    
    Args:
        articles: List of article dictionaries.
        
    Returns:
        Summary statistics.
    """
    total = len(articles)
    open_access = 0
    subscription = 0
    abstract_only = 0
    
    pmc_available = []
    no_fulltext = []
    
    for article in articles:
        links = get_fulltext_links(article)
        
        if links["access_type"] == "open_access":
            open_access += 1
            pmc_available.append({
                "pmid": article.get("pmid"),
                "title": article.get("title", "")[:80],
                "pmc_pdf_url": links["pmc_pdf_url"]
            })
        elif links["access_type"] == "subscription":
            subscription += 1
            no_fulltext.append({
                "pmid": article.get("pmid"),
                "title": article.get("title", "")[:80],
                "doi_url": links["doi_url"]
            })
        else:
            abstract_only += 1
            no_fulltext.append({
                "pmid": article.get("pmid"),
                "title": article.get("title", "")[:80],
                "doi_url": links["doi_url"]
            })
    
    return {
        "total": total,
        "open_access": open_access,
        "subscription": subscription,
        "abstract_only": abstract_only,
        "pmc_available": pmc_available[:20],  # Limit for display
        "no_fulltext": no_fulltext[:20],  # Limit for display
        "pmc_percentage": round(open_access / total * 100, 1) if total > 0 else 0
    }
