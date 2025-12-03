"""
Research Session Module - Session management and article caching.

Provides:
- Article caching to avoid redundant NCBI API calls
- Research session state management
- Search history tracking
- Reading list management
"""

import json
import logging
import os
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CachedArticle:
    """Cached article data."""
    pmid: str
    title: str
    authors: List[str]
    abstract: str
    journal: str
    year: str
    doi: str = ""
    pmc_id: str = ""
    cached_at: str = field(default_factory=lambda: datetime.now().isoformat())
    full_data: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self, max_age_days: int = 7) -> bool:
        """Check if cache entry is expired."""
        cached_time = datetime.fromisoformat(self.cached_at)
        return datetime.now() - cached_time > timedelta(days=max_age_days)


@dataclass
class SearchRecord:
    """Record of a search query."""
    query: str
    timestamp: str
    result_count: int
    pmids: List[str]
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass  
class ResearchSession:
    """
    Research session state - the aggregate root for a research project.
    
    Maintains:
    - Current research topic/context
    - Article cache (avoid redundant API calls)
    - Search history
    - Reading list with priorities
    - Notes and annotations
    """
    session_id: str
    topic: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Article cache: pmid -> CachedArticle
    article_cache: Dict[str, Dict] = field(default_factory=dict)
    
    # Search history
    search_history: List[Dict] = field(default_factory=list)
    
    # Reading list: pmid -> {"priority": 1-5, "status": "unread/reading/read", "notes": ""}
    reading_list: Dict[str, Dict] = field(default_factory=dict)
    
    # Excluded PMIDs (user marked as not relevant)
    excluded_pmids: List[str] = field(default_factory=list)
    
    # Notes: pmid -> notes
    notes: Dict[str, str] = field(default_factory=dict)
    
    def touch(self):
        """Update the last modified timestamp."""
        self.updated_at = datetime.now().isoformat()


class ArticleCache:
    """
    Article cache manager with persistence.
    
    Caches article details to avoid redundant NCBI API calls.
    Supports both in-memory and file-based persistence.
    """
    
    def __init__(self, cache_dir: Optional[str] = None, max_age_days: int = 7):
        """
        Initialize article cache.
        
        Args:
            cache_dir: Directory for persistent cache. If None, uses memory only.
            max_age_days: Maximum age of cache entries before refresh.
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_age_days = max_age_days
        self._memory_cache: Dict[str, CachedArticle] = {}
        
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_cache()
    
    def _get_cache_file(self) -> Path:
        """Get the cache file path."""
        return self.cache_dir / "article_cache.json"
    
    def _load_cache(self):
        """Load cache from disk."""
        cache_file = self._get_cache_file()
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for pmid, article_data in data.items():
                        self._memory_cache[pmid] = CachedArticle(**article_data)
                logger.info(f"Loaded {len(self._memory_cache)} articles from cache")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
    
    def _save_cache(self):
        """Save cache to disk."""
        if not self.cache_dir:
            return
        
        cache_file = self._get_cache_file()
        try:
            data = {pmid: asdict(article) for pmid, article in self._memory_cache.items()}
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def get(self, pmid: str) -> Optional[CachedArticle]:
        """
        Get article from cache.
        
        Args:
            pmid: PubMed ID.
            
        Returns:
            CachedArticle if found and not expired, None otherwise.
        """
        article = self._memory_cache.get(pmid)
        if article and not article.is_expired(self.max_age_days):
            logger.debug(f"Cache hit for PMID {pmid}")
            return article
        return None
    
    def get_many(self, pmids: List[str]) -> tuple[Dict[str, CachedArticle], List[str]]:
        """
        Get multiple articles from cache.
        
        Args:
            pmids: List of PubMed IDs.
            
        Returns:
            Tuple of (cached_articles dict, missing_pmids list)
        """
        cached = {}
        missing = []
        
        for pmid in pmids:
            article = self.get(pmid)
            if article:
                cached[pmid] = article
            else:
                missing.append(pmid)
        
        logger.info(f"Cache: {len(cached)} hits, {len(missing)} misses")
        return cached, missing
    
    def put(self, pmid: str, article_data: Dict[str, Any]):
        """
        Add article to cache.
        
        Args:
            pmid: PubMed ID.
            article_data: Full article data from NCBI.
        """
        cached_article = CachedArticle(
            pmid=pmid,
            title=article_data.get('title', ''),
            authors=article_data.get('authors', []),
            abstract=article_data.get('abstract', ''),
            journal=article_data.get('journal', ''),
            year=article_data.get('year', ''),
            doi=article_data.get('doi', ''),
            pmc_id=article_data.get('pmc_id', ''),
            full_data=article_data
        )
        self._memory_cache[pmid] = cached_article
        self._save_cache()
        logger.debug(f"Cached article PMID {pmid}")
    
    def put_many(self, articles: List[Dict[str, Any]]):
        """Add multiple articles to cache."""
        for article in articles:
            pmid = article.get('pmid', '')
            if pmid:
                self.put(pmid, article)
    
    def invalidate(self, pmid: str):
        """Remove article from cache."""
        if pmid in self._memory_cache:
            del self._memory_cache[pmid]
            self._save_cache()
    
    def clear(self):
        """Clear all cached articles."""
        self._memory_cache.clear()
        self._save_cache()
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = len(self._memory_cache)
        expired = sum(1 for a in self._memory_cache.values() if a.is_expired(self.max_age_days))
        return {
            "total_cached": total,
            "valid": total - expired,
            "expired": expired,
            "cache_dir": str(self.cache_dir) if self.cache_dir else "memory_only"
        }


class SessionManager:
    """
    Manages research sessions with persistence.
    
    Each session represents a research project/topic with its own:
    - Article cache
    - Search history
    - Reading list
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize session manager.
        
        Args:
            data_dir: Directory for session data. If None, uses memory only.
        """
        self.data_dir = Path(data_dir) if data_dir else None
        self._sessions: Dict[str, ResearchSession] = {}
        self._current_session_id: Optional[str] = None
        
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._load_sessions()
    
    def _get_sessions_file(self) -> Path:
        """Get the sessions index file path."""
        return self.data_dir / "sessions.json"
    
    def _get_session_file(self, session_id: str) -> Path:
        """Get a specific session file path."""
        return self.data_dir / f"session_{session_id}.json"
    
    def _load_sessions(self):
        """Load sessions index from disk."""
        sessions_file = self._get_sessions_file()
        if sessions_file.exists():
            try:
                with open(sessions_file, 'r', encoding='utf-8') as f:
                    index = json.load(f)
                    self._current_session_id = index.get('current_session_id')
                    for session_id in index.get('sessions', []):
                        self._load_session(session_id)
                logger.info(f"Loaded {len(self._sessions)} sessions")
            except Exception as e:
                logger.warning(f"Failed to load sessions: {e}")
    
    def _load_session(self, session_id: str):
        """Load a specific session from disk."""
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._sessions[session_id] = ResearchSession(**data)
            except Exception as e:
                logger.warning(f"Failed to load session {session_id}: {e}")
    
    def _save_session(self, session: ResearchSession):
        """Save a session to disk."""
        if not self.data_dir:
            return
        
        session_file = self._get_session_file(session.session_id)
        try:
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(session), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")
        
        # Update index
        self._save_sessions_index()
    
    def _save_sessions_index(self):
        """Save sessions index."""
        if not self.data_dir:
            return
        
        sessions_file = self._get_sessions_file()
        try:
            index = {
                'current_session_id': self._current_session_id,
                'sessions': list(self._sessions.keys())
            }
            with open(sessions_file, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save sessions index: {e}")
    
    def create_session(self, topic: str = "") -> ResearchSession:
        """
        Create a new research session.
        
        Args:
            topic: Research topic description.
            
        Returns:
            New ResearchSession instance.
        """
        session_id = hashlib.md5(f"{topic}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        session = ResearchSession(session_id=session_id, topic=topic)
        self._sessions[session_id] = session
        self._current_session_id = session_id
        self._save_session(session)
        logger.info(f"Created session {session_id}: {topic}")
        return session
    
    def get_current_session(self) -> Optional[ResearchSession]:
        """Get the current active session."""
        if self._current_session_id:
            return self._sessions.get(self._current_session_id)
        return None
    
    def get_or_create_session(self, topic: str = "default") -> ResearchSession:
        """Get current session or create a new one."""
        session = self.get_current_session()
        if not session:
            session = self.create_session(topic)
        return session
    
    def switch_session(self, session_id: str) -> Optional[ResearchSession]:
        """Switch to a different session."""
        if session_id in self._sessions:
            self._current_session_id = session_id
            self._save_sessions_index()
            return self._sessions[session_id]
        return None
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions."""
        return [
            {
                "session_id": s.session_id,
                "topic": s.topic,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "article_count": len(s.article_cache),
                "search_count": len(s.search_history),
                "is_current": s.session_id == self._current_session_id
            }
            for s in self._sessions.values()
        ]
    
    def add_to_cache(self, articles: List[Dict[str, Any]]):
        """Add articles to current session's cache."""
        session = self.get_or_create_session()
        for article in articles:
            pmid = article.get('pmid', '')
            if pmid:
                session.article_cache[pmid] = {
                    **article,
                    'cached_at': datetime.now().isoformat()
                }
        session.touch()
        self._save_session(session)
    
    def get_from_cache(self, pmids: List[str]) -> tuple[List[Dict], List[str]]:
        """
        Get articles from current session's cache.
        
        Returns:
            Tuple of (cached_articles, missing_pmids)
        """
        session = self.get_current_session()
        if not session:
            return [], pmids
        
        cached = []
        missing = []
        
        for pmid in pmids:
            if pmid in session.article_cache:
                cached.append(session.article_cache[pmid])
            else:
                missing.append(pmid)
        
        return cached, missing
    
    def is_searched(self, pmid: str) -> bool:
        """Check if PMID was already searched in this session."""
        session = self.get_current_session()
        if not session:
            return False
        return pmid in session.article_cache
    
    def add_search_record(self, query: str, pmids: List[str], filters: Dict = None):
        """Record a search in history."""
        session = self.get_or_create_session()
        record = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "result_count": len(pmids),
            "pmids": pmids,
            "filters": filters or {}
        }
        session.search_history.append(record)
        session.touch()
        self._save_session(session)
    
    def add_to_reading_list(self, pmid: str, priority: int = 3, notes: str = ""):
        """Add article to reading list."""
        session = self.get_or_create_session()
        session.reading_list[pmid] = {
            "priority": priority,
            "status": "unread",
            "added_at": datetime.now().isoformat(),
            "notes": notes
        }
        session.touch()
        self._save_session(session)
    
    def exclude_article(self, pmid: str):
        """Mark article as excluded/not relevant."""
        session = self.get_or_create_session()
        if pmid not in session.excluded_pmids:
            session.excluded_pmids.append(pmid)
            session.touch()
            self._save_session(session)
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session for Agent context."""
        session = self.get_current_session()
        if not session:
            return {"status": "no_active_session"}
        
        return {
            "session_id": session.session_id,
            "topic": session.topic,
            "cached_articles": len(session.article_cache),
            "searches_performed": len(session.search_history),
            "reading_list_count": len(session.reading_list),
            "excluded_count": len(session.excluded_pmids),
            "recent_searches": [
                {"query": s["query"], "count": s["result_count"]}
                for s in session.search_history[-5:]
            ],
            "cached_pmids": list(session.article_cache.keys())[:20],
            "reading_list": session.reading_list
        }
