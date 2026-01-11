"""
Common utilities for MCP tools.

Shared functions:
- Session manager and strategy generator setup
- Result caching and cache lookup
- Output formatting
- Input normalization (Phase 2.1)
- Response formatting (Phase 2.1)
"""

import logging
import re
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Phase 2.1: Input Normalizer - Agent-Friendly Input Handling
# ============================================================================

class InputNormalizer:
    """
    Agent-friendly input normalizer for MCP tools.
    
    Automatically corrects common input format mistakes that Agents make,
    improving robustness for weaker models.
    
    Features:
    - Multi-format PMID support (str, list, int, with prefixes)
    - Year format normalization
    - Limit range clamping
    - Boolean string conversion
    - Key alias mapping
    """
    
    # Common PMID prefixes to strip
    PMID_PREFIXES = ['pmid:', 'pmid', 'pubmed:', 'pubmed']
    
    # Common PMC prefixes
    PMC_PREFIXES = ['pmc', 'pmcid:', 'pmcid']
    
    @staticmethod
    def normalize_pmids(value: Union[str, List, int, None]) -> List[str]:
        """
        Accept multiple PMID formats and normalize to list of clean strings.
        
        Supports:
        - "12345678"
        - "12345678,87654321"
        - "12345678, 87654321" (with spaces)
        - "12345678 87654321" (space separated)
        - "PMID:12345678"
        - "PMID: 12345678, PMID: 87654321"
        - ["12345678", "87654321"]
        - [12345678, 87654321] (int list)
        - 12345678 (single int)
        - "last" (special keyword for last search)
        
        Returns:
            List of clean PMID strings (digits only)
        """
        if value is None:
            return []
        
        # Handle "last" keyword
        if isinstance(value, str) and value.lower().strip() == 'last':
            return ['last']  # Special marker
        
        # Convert single int to string
        if isinstance(value, int):
            return [str(value)]
        
        # Handle list input
        if isinstance(value, (list, tuple)):
            result = []
            for item in value:
                result.extend(InputNormalizer.normalize_pmids(item))
            return result
        
        # Handle string input
        if isinstance(value, str):
            # Normalize separators: replace various separators with comma
            normalized = re.sub(r'[;|\s]+', ',', value.strip())
            
            # Split by comma
            parts = [p.strip() for p in normalized.split(',') if p.strip()]
            
            result = []
            for part in parts:
                # Strip common prefixes (case insensitive)
                cleaned = part
                for prefix in InputNormalizer.PMID_PREFIXES:
                    if cleaned.lower().startswith(prefix):
                        cleaned = cleaned[len(prefix):].strip()
                        # Also strip colon if present
                        if cleaned.startswith(':'):
                            cleaned = cleaned[1:].strip()
                        break
                
                # Extract digits only
                digits = re.sub(r'\D', '', cleaned)
                if digits:
                    result.append(digits)
            
            return result
        
        return []
    
    @staticmethod
    def normalize_pmid_single(value: Union[str, int, None]) -> Optional[str]:
        """
        Normalize a single PMID value.
        
        Returns:
            Clean PMID string or None if invalid
        """
        pmids = InputNormalizer.normalize_pmids(value)
        return pmids[0] if pmids else None
    
    @staticmethod
    def normalize_pmcid(value: Union[str, None]) -> Optional[str]:
        """
        Normalize PMC ID to standard format (PMCxxxxxxx).
        
        Supports:
        - "PMC7096777"
        - "7096777"
        - "pmc7096777"
        - "PMCID: PMC7096777"
        """
        if value is None:
            return None
        
        if not isinstance(value, str):
            value = str(value)
        
        value = value.strip()
        
        # Strip prefixes
        for prefix in InputNormalizer.PMC_PREFIXES:
            if value.lower().startswith(prefix):
                value = value[len(prefix):].strip()
                if value.startswith(':'):
                    value = value[1:].strip()
                break
        
        # Extract digits
        digits = re.sub(r'\D', '', value)
        
        if digits:
            return f"PMC{digits}"
        
        return None
    
    @staticmethod
    def normalize_year(value: Union[str, int, None]) -> Optional[int]:
        """
        Normalize year value to integer.
        
        Supports:
        - 2024 (int)
        - "2024" (str)
        - "2024年"
        - "since 2020" → 2020
        - "before 2024" → 2024
        """
        if value is None:
            return None
        
        if isinstance(value, int):
            # Validate range
            if 1900 <= value <= 2100:
                return value
            return None
        
        if isinstance(value, str):
            value = value.strip()
            
            # Extract 4-digit year
            match = re.search(r'(19|20)\d{2}', value)
            if match:
                year = int(match.group())
                if 1900 <= year <= 2100:
                    return year
        
        return None
    
    @staticmethod
    def normalize_limit(
        value: Union[int, str, None],
        default: int = 10,
        min_val: int = 1,
        max_val: int = 100
    ) -> int:
        """
        Normalize limit value with bounds checking.
        
        Args:
            value: Input limit value
            default: Default if value is None
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            
        Returns:
            Clamped integer value
        """
        if value is None:
            return default
        
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                return default
        
        if isinstance(value, int):
            return max(min_val, min(value, max_val))
        
        return default
    
    @staticmethod
    def normalize_bool(
        value: Union[bool, str, int, None],
        default: bool = False
    ) -> bool:
        """
        Normalize boolean value from various formats.
        
        Supports:
        - True/False (bool)
        - "true"/"false" (case insensitive)
        - "yes"/"no"
        - "1"/"0"
        - 1/0 (int)
        - "on"/"off"
        """
        if value is None:
            return default
        
        if isinstance(value, bool):
            return value
        
        if isinstance(value, int):
            return bool(value)
        
        if isinstance(value, str):
            value_lower = value.strip().lower()
            if value_lower in ('true', 'yes', '1', 'on', 't', 'y'):
                return True
            if value_lower in ('false', 'no', '0', 'off', 'f', 'n'):
                return False
        
        return default
    
    @staticmethod
    def normalize_query(query: Union[str, None]) -> str:
        """
        Normalize search query string.
        
        - Strip whitespace
        - Normalize Unicode
        - Fix common typos in operators
        """
        if not query:
            return ""
        
        query = query.strip()
        
        # Normalize Unicode quotes to ASCII
        query = query.replace('"', '"').replace('"', '"')
        query = query.replace(''', "'").replace(''', "'")
        
        # Fix common operator typos (case insensitive replacement)
        replacements = [
            (r'\bAdn\b', 'AND'),
            (r'\bOr\b', 'OR'),
            (r'\bNto\b', 'NOT'),
        ]
        
        for pattern, replacement in replacements:
            query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
        
        return query


# ============================================================================
# Phase 2.1: Response Formatter - Agent-Friendly Output
# ============================================================================

class ResponseFormatter:
    """
    Unified response formatter for consistent MCP tool outputs.
    
    Provides:
    - Consistent success/error formatting
    - Helpful error messages with suggestions
    - Multi-format output (markdown/json)
    """
    
    @staticmethod
    def success(
        data: Any,
        message: str = None,
        metadata: Dict = None,
        output_format: str = "markdown"
    ) -> str:
        """
        Format a successful response.
        
        Args:
            data: The main response data
            message: Optional success message
            metadata: Optional metadata dict
            output_format: "markdown" or "json"
            
        Returns:
            Formatted response string
        """
        import json
        
        if output_format == "json":
            result = {
                "success": True,
                "data": data,
            }
            if message:
                result["message"] = message
            if metadata:
                result["metadata"] = metadata
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        # Markdown format
        parts = []
        if message:
            parts.append(f"✅ {message}\n")
        
        if isinstance(data, str):
            parts.append(data)
        elif isinstance(data, (list, dict)):
            parts.append(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            parts.append(str(data))
        
        if metadata:
            parts.append(f"\n---\n*Metadata: {metadata}*")
        
        return "\n".join(parts)
    
    @staticmethod
    def error(
        error: Union[Exception, str],
        suggestion: str = None,
        example: str = None,
        tool_name: str = None,
        output_format: str = "markdown"
    ) -> str:
        """
        Format an error response with helpful suggestions.
        
        Args:
            error: The error exception or message
            suggestion: Helpful suggestion for fixing the error
            example: Example of correct usage
            tool_name: Name of the tool that failed
            output_format: "markdown" or "json"
            
        Returns:
            Formatted error string
        """
        import json
        
        error_msg = str(error)
        
        if output_format == "json":
            result = {
                "success": False,
                "error": error_msg,
            }
            if tool_name:
                result["tool"] = tool_name
            if suggestion:
                result["suggestion"] = suggestion
            if example:
                result["example"] = example
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        # Markdown format
        parts = []
        
        if tool_name:
            parts.append(f"❌ **Error in {tool_name}**: {error_msg}")
        else:
            parts.append(f"❌ **Error**: {error_msg}")
        
        if suggestion:
            parts.append(f"\n💡 **Suggestion**: {suggestion}")
        
        if example:
            parts.append(f"\n📝 **Example**: `{example}`")
        
        return "\n".join(parts)
    
    @staticmethod
    def no_results(
        query: str = None,
        suggestions: List[str] = None,
        alternative_tools: List[str] = None
    ) -> str:
        """
        Format a 'no results' response with helpful suggestions.
        
        Args:
            query: The search query that returned no results
            suggestions: List of search suggestions
            alternative_tools: List of alternative tools to try
            
        Returns:
            Formatted no-results message
        """
        parts = ["🔍 **No results found**"]
        
        if query:
            parts.append(f"\nQuery: `{query}`")
        
        if suggestions:
            parts.append("\n\n💡 **Suggestions**:")
            for s in suggestions:
                parts.append(f"- {s}")
        
        if alternative_tools:
            parts.append("\n\n🔧 **Alternative tools to try**:")
            for tool in alternative_tools:
                parts.append(f"- `{tool}`")
        
        return "\n".join(parts)
    
    @staticmethod
    def partial_success(
        successful: List[Any],
        failed: List[Dict],
        message: str = None
    ) -> str:
        """
        Format a partial success response (some items succeeded, some failed).
        
        Args:
            successful: List of successful results
            failed: List of failed items with error info
            message: Optional message
            
        Returns:
            Formatted partial success message
        """
        parts = []
        
        if message:
            parts.append(f"⚠️ {message}")
        else:
            parts.append(f"⚠️ **Partial success**: {len(successful)} succeeded, {len(failed)} failed")
        
        if failed:
            parts.append("\n\n**Failed items**:")
            for item in failed[:5]:  # Show first 5 failures
                parts.append(f"- {item.get('id', 'unknown')}: {item.get('error', 'unknown error')}")
            if len(failed) > 5:
                parts.append(f"- ... and {len(failed) - 5} more")
        
        return "\n".join(parts)


# ============================================================================
# Phase 2.1: Key Alias Mapping - Handle Alternative Parameter Names
# ============================================================================

# Map alternative parameter names to standard names
KEY_ALIASES = {
    # Year parameters
    "year_from": "min_year",
    "from_year": "min_year",
    "start_year": "min_year",
    "year_to": "max_year",
    "to_year": "max_year",
    "end_year": "max_year",
    
    # Limit parameters
    "max_results": "limit",
    "num_results": "limit",
    "count": "limit",
    "n": "limit",
    "limit_per_level": "limit",
    
    # Format parameters
    "format": "output_format",
    "fmt": "output_format",
    
    # ID parameters (less common but helpful)
    "pubmed_id": "pmid",
    "pmc_id": "pmcid",
}


def apply_key_aliases(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply key aliases to normalize parameter names.
    
    Args:
        kwargs: Original keyword arguments
        
    Returns:
        kwargs with aliased keys mapped to standard names
    """
    result = {}
    for key, value in kwargs.items():
        # Check if this key is an alias
        standard_key = KEY_ALIASES.get(key.lower(), key)
        
        # Only use alias if standard key isn't already present
        if standard_key not in result:
            result[standard_key] = value
        # If standard key exists and this is an alias, log warning
        elif key != standard_key:
            logger.debug(f"Ignoring alias '{key}' because '{standard_key}' already present")
    
    return result

# Global references (set by server.py after initialization)
_session_manager = None
_strategy_generator = None


def set_session_manager(session_manager):
    """Set the session manager for automatic caching."""
    global _session_manager
    _session_manager = session_manager


def set_strategy_generator(generator):
    """Set the strategy generator for intelligent query generation."""
    global _strategy_generator
    _strategy_generator = generator


def get_session_manager():
    """Get the current session manager."""
    return _session_manager


def get_strategy_generator():
    """Get the current strategy generator."""
    return _strategy_generator


def check_cache(query: str, limit: int = None) -> Optional[List[Dict]]:
    """
    Check if search results exist in cache.
    
    Args:
        query: Search query string
        limit: Required number of results
        
    Returns:
        Cached results if found, None otherwise
    """
    if not _session_manager:
        return None
    
    try:
        return _session_manager.find_cached_search(query, limit)
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
        return None


def _cache_results(results: list, query: str = None):
    """Cache search results if session manager is available."""
    if _session_manager and results and not results[0].get('error'):
        try:
            _session_manager.add_to_cache(results)
            if query:
                pmids = [r.get('pmid') for r in results if r.get('pmid')]
                _session_manager.add_search_record(query, pmids)
            logger.debug(f"Cached {len(results)} articles")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")


def _record_search_only(results: list, query: str):
    """Record search in history without caching article details.
    
    Used for filtered searches where we don't want to pollute the cache
    but still want to support 'last' export feature.
    """
    if _session_manager and results and not results[0].get('error'):
        try:
            pmids = [r.get('pmid') for r in results if r.get('pmid')]
            _session_manager.add_search_record(query, pmids)
            logger.debug(f"Recorded search '{query}' with {len(pmids)} PMIDs")
        except Exception as e:
            logger.warning(f"Failed to record search: {e}")


def get_last_search_pmids() -> List[str]:
    """Get PMIDs from the most recent search.
    
    Returns:
        List of PMIDs from last search, or empty list if none.
    """
    if not _session_manager:
        return []
    
    try:
        session = _session_manager.get_or_create_session()
        if session.search_history:
            last_search = session.search_history[-1]
            return last_search.pmids
        return []
    except Exception as e:
        logger.warning(f"Failed to get last search PMIDs: {e}")
        return []


def format_search_results(results: list, include_doi: bool = True) -> str:
    """Format search results for display."""
    if not results:
        return "No results found."
        
    if "error" in results[0]:
        return f"Error searching PubMed: {results[0]['error']}"
        
    formatted_output = f"Found {len(results)} results:\n\n"
    for i, paper in enumerate(results, 1):
        formatted_output += f"{i}. **{paper['title']}**\n"
        authors = paper.get('authors', [])
        formatted_output += f"   Authors: {', '.join(authors[:3])}{' et al.' if len(authors) > 3 else ''}\n"
        journal = paper.get('journal', 'Unknown Journal')
        year = paper.get('year', '')
        volume = paper.get('volume', '')
        pages = paper.get('pages', '')
        
        journal_info = f"{journal} ({year})"
        if volume:
            journal_info += f"; {volume}"
            if pages:
                journal_info += f": {pages}"
        formatted_output += f"   Journal: {journal_info}\n"
        formatted_output += f"   PMID: {paper.get('pmid', '')}"
        
        if include_doi and paper.get('doi'):
            formatted_output += f" | DOI: {paper['doi']}"
        if paper.get('pmc_id'):
            formatted_output += f" | PMC: {paper['pmc_id']} 📄"
        
        formatted_output += "\n"
        
        abstract = paper.get('abstract', '')
        if abstract:
            formatted_output += f"   Abstract: {abstract[:200]}...\n"
        formatted_output += "\n"
        
    return formatted_output
