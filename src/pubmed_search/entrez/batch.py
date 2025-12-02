"""
Entrez Batch Module - Large Result Set Processing

Provides functionality for processing large result sets using NCBI History Server.
"""

from Bio import Entrez
from typing import List, Dict, Any


class BatchMixin:
    """
    Mixin providing batch processing functionality using NCBI History Server.
    
    Methods:
        search_with_history: Search and store results on NCBI server
        fetch_batch_from_history: Fetch results in batches
    """
    
    def search_with_history(self, query: str, batch_size: int = 500) -> Dict[str, Any]:
        """
        Search large result sets efficiently using NCBI History Server.
        Returns WebEnv and QueryKey for batch processing.
        
        Args:
            query: Search query string.
            batch_size: Number of results to process per batch.
            
        Returns:
            Dictionary with search metadata for batch processing:
            - webenv: WebEnv identifier for this search session
            - query_key: QueryKey for this search
            - count: Total number of results
            - batch_size: Recommended batch size
        """
        try:
            handle = Entrez.esearch(db="pubmed", term=query, usehistory="y", retmax=0)
            search_results = Entrez.read(handle)
            handle.close()
            
            return {
                "webenv": search_results.get("WebEnv", ""),
                "query_key": search_results.get("QueryKey", ""),
                "count": int(search_results.get("Count", 0)),
                "batch_size": batch_size
            }
        except Exception as e:
            return {"error": str(e)}

    def fetch_batch_from_history(
        self, 
        webenv: str, 
        query_key: str, 
        start: int, 
        batch_size: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch a batch of results using History Server credentials.
        
        Args:
            webenv: WebEnv from search_with_history.
            query_key: QueryKey from search_with_history.
            start: Starting index (0-based).
            batch_size: Number of results to fetch.
            
        Returns:
            List of article details for this batch.
            
        Example:
            >>> history = searcher.search_with_history("cancer therapy")
            >>> total = history['count']
            >>> batch_size = history['batch_size']
            >>> for start in range(0, total, batch_size):
            ...     batch = searcher.fetch_batch_from_history(
            ...         history['webenv'], history['query_key'],
            ...         start, batch_size
            ...     )
            ...     process_batch(batch)
        """
        try:
            handle = Entrez.efetch(
                db="pubmed", 
                retstart=start, 
                retmax=batch_size,
                webenv=webenv, 
                query_key=query_key, 
                retmode="xml"
            )
            papers = Entrez.read(handle)
            handle.close()
            
            results = []
            if 'PubmedArticle' in papers:
                for article in papers['PubmedArticle']:
                    medline_citation = article['MedlineCitation']
                    article_data = medline_citation['Article']
                    
                    title = article_data.get('ArticleTitle', 'No title')
                    pmid = str(medline_citation.get('PMID', ''))
                    
                    # Extract basic info
                    authors = []
                    if 'AuthorList' in article_data:
                        for author in article_data['AuthorList']:
                            if 'LastName' in author:
                                authors.append(f"{author['LastName']} {author.get('ForeName', '')}".strip())
                    
                    journal = article_data.get('Journal', {}).get('Title', 'Unknown')
                    year = article_data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {}).get('Year', '')
                    
                    results.append({
                        "pmid": pmid,
                        "title": title,
                        "authors": authors,
                        "journal": journal,
                        "year": year
                    })
            
            return results
        except Exception as e:
            return [{"error": str(e)}]
