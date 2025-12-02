"""
Entrez Utils Module - Utility Functions

Provides various utility functions for Entrez operations including:
- Quick summary fetch
- Spell checking
- Database info
- MeSH validation
- Citation matching
- Export functions
"""

from Bio import Entrez
from typing import List, Dict, Any, Optional


class UtilsMixin:
    """
    Mixin providing utility functions for Entrez operations.
    
    Methods:
        quick_fetch_summary: Fast metadata fetch using ESummary
        spell_check_query: Check and correct query spelling
        get_database_counts: Get result counts across databases
        validate_mesh_terms: Validate MeSH terms
        find_by_citation: Find article by citation details
        export_citations: Export citations in various formats
        get_database_info: Get database statistics
    """
    
    def quick_fetch_summary(self, id_list: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch article summaries using ESummary (faster than EFetch for metadata only).
        
        Args:
            id_list: List of PubMed IDs.
            
        Returns:
            List of article summaries with basic metadata.
        """
        if not id_list:
            return []
        
        try:
            handle = Entrez.esummary(db="pubmed", id=",".join(id_list))
            summaries = Entrez.read(handle)
            handle.close()
            
            results = []
            for summary in summaries:
                # ESummary returns DictionaryElement but hasattr check is safer
                if hasattr(summary, 'get') or hasattr(summary, '__getitem__'):
                    # AuthorList contains StringElements, not dicts
                    author_list = summary.get('AuthorList', [])
                    authors = [str(author) for author in author_list]
                    
                    pub_date = summary.get('PubDate', '')
                    year = pub_date.split()[0] if pub_date else ''
                    
                    results.append({
                        "pmid": str(summary.get('Id', '')),
                        "title": str(summary.get('Title', '')),
                        "authors": authors,
                        "journal": str(summary.get('Source', '')),
                        "year": year,
                        "doi": str(summary.get('DOI', '')),
                        "pmc_id": str(summary.get('PMCID', ''))
                    })
            
            return results
        except Exception as e:
            return [{"error": str(e)}]

    def spell_check_query(self, query: str) -> str:
        """
        Get spelling suggestions for search queries using ESpell.
        
        Args:
            query: The search query to check.
            
        Returns:
            Corrected query string if suggestions found, original query otherwise.
        """
        try:
            handle = Entrez.espell(db="pubmed", term=query)
            result = Entrez.read(handle)
            handle.close()
            
            corrected = result.get("CorrectedQuery", "")
            return corrected if corrected else query
        except Exception as e:
            print(f"Error in spell check: {e}")
            return query

    def get_database_counts(self, query: str) -> Dict[str, int]:
        """
        Get result counts across multiple NCBI databases using EGQuery.
        
        Args:
            query: The search query.
            
        Returns:
            Dictionary mapping database names to result counts.
        """
        try:
            handle = Entrez.egquery(term=query)
            result = Entrez.read(handle)
            handle.close()
            
            counts = {}
            for db_result in result["eGQueryResult"]:
                db_name = db_result.get("DbName", "")
                count = db_result.get("Count", "0")
                try:
                    counts[db_name] = int(count)
                except ValueError:
                    counts[db_name] = 0
            
            return counts
        except Exception as e:
            return {"error": str(e)}

    def validate_mesh_terms(self, terms: List[str]) -> Dict[str, Any]:
        """
        Validate MeSH terms and get their IDs using MeSH database.
        
        Args:
            terms: List of potential MeSH terms to validate.
            
        Returns:
            Dictionary with valid terms and their IDs.
        """
        try:
            query = " OR ".join([f'"{term}"[MeSH Terms]' for term in terms])
            handle = Entrez.esearch(db="mesh", term=query, retmax=len(terms))
            result = Entrez.read(handle)
            handle.close()
            
            mesh_ids = result.get("IdList", [])
            
            if mesh_ids:
                handle = Entrez.esummary(db="mesh", id=",".join(mesh_ids))
                summaries = Entrez.read(handle)
                handle.close()
                
                validated_terms = []
                for summary in summaries:
                    if isinstance(summary, dict):
                        validated_terms.append({
                            "mesh_id": summary.get("Id", ""),
                            "term": summary.get("DS_MeshTerms", [""])[0] if summary.get("DS_MeshTerms") else "",
                            "tree_numbers": summary.get("DS_IdxLinks", [])
                        })
                
                return {
                    "valid_count": len(validated_terms),
                    "terms": validated_terms
                }
            
            return {"valid_count": 0, "terms": []}
        except Exception as e:
            return {"error": str(e)}

    def find_by_citation(
        self, 
        journal: str, 
        year: str, 
        volume: str = "", 
        first_page: str = "", 
        author: str = "", 
        title: str = ""
    ) -> Optional[str]:
        """
        Find article by citation details using ECitMatch.
        
        Args:
            journal: Journal name or abbreviation.
            year: Publication year.
            volume: Volume number (optional).
            first_page: First page number (optional).
            author: First author last name (optional).
            title: Article title (optional).
            
        Returns:
            PMID if found, None otherwise.
        """
        try:
            citation_string = f"{journal}|{year}|{volume}|{first_page}|{author}||"
            
            handle = Entrez.ecitmatch(db="pubmed", bdata=citation_string)
            result = handle.read().strip()
            handle.close()
            
            if result and '\t' in result:
                parts = result.split('\t')
                if len(parts) > 1 and parts[1].isdigit():
                    return parts[1]
            
            return None
        except Exception as e:
            print(f"Error in citation match: {e}")
            return None

    def export_citations(self, id_list: List[str], format: str = "medline") -> str:
        """
        Export citations in various formats.
        
        Args:
            id_list: List of PubMed IDs.
            format: Output format - "medline", "pubmed" (XML), "abstract".
            
        Returns:
            Formatted citation text.
        """
        if not id_list:
            return ""
        
        try:
            valid_formats = {
                "medline": ("medline", "text"),
                "pubmed": ("pubmed", "xml"),
                "abstract": ("abstract", "text")
            }
            
            if format not in valid_formats:
                format = "medline"
            
            rettype, retmode = valid_formats[format]
            
            handle = Entrez.efetch(
                db="pubmed", 
                id=id_list, 
                rettype=rettype, 
                retmode=retmode
            )
            result = handle.read()
            handle.close()
            
            return result
        except Exception as e:
            return f"Error exporting citations: {str(e)}"

    def get_database_info(self, db: str = "pubmed") -> Dict[str, Any]:
        """
        Get database statistics and field information using EInfo.
        
        Args:
            db: Database name (default: pubmed).
            
        Returns:
            Dictionary with database information including:
            - name, description, count, last_update
            - available search fields
        """
        try:
            handle = Entrez.einfo(db=db)
            result = Entrez.read(handle)
            handle.close()
            
            db_info = result.get("DbInfo", {})
            
            return {
                "name": db_info.get("DbName", ""),
                "menu_name": db_info.get("MenuName", ""),
                "description": db_info.get("Description", ""),
                "count": db_info.get("Count", "0"),
                "last_update": db_info.get("LastUpdate", ""),
                "fields": [
                    {
                        "name": field.get("Name", ""),
                        "full_name": field.get("FullName", ""),
                        "description": field.get("Description", "")
                    }
                    for field in db_info.get("FieldList", [])
                ]
            }
        except Exception as e:
            return {"error": str(e)}
