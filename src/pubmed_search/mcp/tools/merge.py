"""
Merge Tool - Combine and deduplicate search results.

Tools:
- merge_search_results: Merge multiple searches, remove duplicates, identify high-relevance
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher

logger = logging.getLogger(__name__)


def register_merge_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register result merging tools."""
    
    @mcp.tool()
    def merge_search_results(results_json: str) -> str:
        """
        Merge multiple search results and remove duplicates.
        
        After running search_literature calls in parallel, use this to combine results.
        
        Accepts TWO formats:
        
        Format 1 (Simple - just PMIDs):
        [
            ["12345", "67890"],
            ["67890", "11111", "22222"]
        ]
        
        Format 2 (With query IDs):
        [
            {"query_id": "q1_title", "pmids": ["12345", "67890"]},
            {"query_id": "q2_tiab", "pmids": ["67890", "11111"]}
        ]
        
        Args:
            results_json: JSON array of search results (see formats above)
                
        Returns:
            Merged results with:
            - unique_pmids: Deduplicated list
            - high_relevance_pmids: Found in multiple searches (more relevant)
            - statistics: Counts and duplicates removed
        """
        logger.info("Merging search results")
        
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON format - {e}"
        
        pmid_sources = {}
        all_pmids = []
        by_query = {}
        
        for i, result in enumerate(results):
            # Support both formats
            if isinstance(result, list):
                # Format 1: Simple list of PMIDs
                query_id = f"search_{i+1}"
                pmids = result
            elif isinstance(result, dict):
                # Format 2: With query_id
                query_id = result.get("query_id", f"search_{i+1}")
                pmids = result.get("pmids", [])
            else:
                continue
            
            by_query[query_id] = len(pmids)
            
            for pmid in pmids:
                pmid = str(pmid).strip()
                if not pmid:
                    continue
                if pmid not in pmid_sources:
                    pmid_sources[pmid] = []
                    all_pmids.append(pmid)
                pmid_sources[pmid].append(query_id)
        
        # Find PMIDs that appeared in multiple searches (higher relevance)
        high_relevance = [pmid for pmid, sources in pmid_sources.items() if len(sources) > 1]
        
        # Sort: high relevance first, then others
        sorted_pmids = high_relevance + [p for p in all_pmids if p not in high_relevance]
        
        output = {
            "total_unique": len(all_pmids),
            "total_before_dedup": sum(by_query.values()),
            "duplicates_removed": sum(by_query.values()) - len(all_pmids),
            "high_relevance": {
                "count": len(high_relevance),
                "pmids": high_relevance[:20],
                "note": "Found by multiple search strategies - likely more relevant"
            },
            "by_source": by_query,
            "unique_pmids": sorted_pmids,
            "pmids_csv": ",".join(sorted_pmids[:50]),
            "next_step": f"fetch_article_details(pmids=\"{','.join(sorted_pmids[:20])}\")"
        }
        
        return json.dumps(output, indent=2, ensure_ascii=False)
