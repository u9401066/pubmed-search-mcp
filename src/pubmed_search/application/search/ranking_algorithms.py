"""
Advanced Ranking Algorithms for Multi-Source Academic Retrieval.

This module implements three principled ranking algorithms that complement
the existing 6-dimensional scoring in ResultAggregator:

1. **BM25** (Okapi BM25) — Term-frequency based relevance scoring
   - Replaces naive term-overlap with TF-IDF + document length normalization
   - Standard parameters: k1=1.5, b=0.75

2. **Reciprocal Rank Fusion (RRF)** — Multi-ranker score fusion
   - Combines rankings from multiple dimensions without score calibration
   - Formula: RRF(d) = Σ 1/(k + rank_i(d)), k=60

3. **Maximal Marginal Relevance (MMR)** — Result diversification
   - Iteratively selects results balancing relevance and diversity
   - Uses MeSH/keyword Jaccard similarity (no embeddings needed)
   - Formula: MMR(d) = λ·Rel(d,q) - (1-λ)·max Sim(d,d')

References:
    - Robertson & Zaragoza (2009). "The Probabilistic Relevance Framework: BM25 and Beyond"
    - Cormack et al. (2009). "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
    - Carbonell & Goldstein (1998). "The use of MMR, diversity-based reranking for reordering documents"

Architecture:
    These algorithms are stateless functions called by ResultAggregator.
    They operate on UnifiedArticle objects and return scored/reranked lists.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle


# =============================================================================
# BM25 Relevance Scoring
# =============================================================================

# BM25 standard parameters (tuned for biomedical literature)
_BM25_K1 = 1.5  # Term frequency saturation parameter
_BM25_B = 0.75  # Document length normalization parameter
_BM25_TITLE_BOOST = 2.0  # Title match gets 2x IDF weight
_BM25_MESH_BOOST = 1.5  # MeSH/keyword match gets 1.5x IDF weight
_MIN_TERM_LENGTH = 3  # Minimum term length for indexing


@dataclass
class BM25Corpus:
    """
    Corpus statistics for BM25 scoring.

    Built from the current search result set (micro-corpus).
    Each search creates a fresh corpus from its results.
    """

    total_docs: int = 0
    avg_doc_length: float = 0.0
    doc_freq: dict[str, int] = field(default_factory=dict)  # term → number of docs containing term

    @classmethod
    def from_articles(cls, articles: list[UnifiedArticle]) -> BM25Corpus:
        """
        Build corpus statistics from a list of articles.

        Indexes title + abstract + keywords + MeSH terms.
        Time complexity: O(n × avg_doc_length).
        """
        corpus = cls(total_docs=len(articles))
        total_length = 0

        for article in articles:
            # Extract all terms from article
            terms = _extract_article_terms(article)
            total_length += len(terms)

            # Count document frequency (each term counted once per doc)
            unique_terms = set(terms)
            for term in unique_terms:
                corpus.doc_freq[term] = corpus.doc_freq.get(term, 0) + 1

        corpus.avg_doc_length = total_length / max(corpus.total_docs, 1)
        return corpus


def _extract_article_terms(article: UnifiedArticle) -> list[str]:
    """Extract all indexable terms from an article."""
    text_parts: list[str] = []

    if article.title:
        text_parts.append(article.title.lower())
    if article.abstract:
        text_parts.append(article.abstract.lower())

    keywords = getattr(article, "keywords", []) or []
    mesh_terms = getattr(article, "mesh_terms", []) or []
    for kw in keywords + mesh_terms:
        text_parts.append(kw.lower())

    full_text = " ".join(text_parts)
    return [t for t in re.findall(r"\b\w+\b", full_text) if len(t) >= _MIN_TERM_LENGTH]


def bm25_score(
    article: UnifiedArticle,
    query: str,
    corpus: BM25Corpus,
) -> float:
    """
    Calculate BM25 relevance score for a single article.

    BM25 formula per query term q_i:
        score(q_i, D) = IDF(q_i) × (f(q_i, D) × (k1 + 1)) / (f(q_i, D) + k1 × (1 - b + b × |D|/avgdl))

    where:
        IDF(q_i) = ln((N - n(q_i) + 0.5) / (n(q_i) + 0.5) + 1)
        f(q_i, D) = term frequency of q_i in document D
        |D| = document length
        avgdl = average document length in corpus
        N = total documents
        n(q_i) = document frequency of q_i

    Title and MeSH matches receive boosted IDF weights.

    Args:
        article: Article to score
        query: Search query
        corpus: Pre-computed corpus statistics

    Returns:
        BM25 score (raw, not normalized). Higher = more relevant.
    """
    query_terms = [t.lower() for t in re.findall(r"\b\w+\b", query) if len(t) >= _MIN_TERM_LENGTH]
    if not query_terms or corpus.total_docs == 0:
        return 0.0

    # Extract terms from different fields
    title_terms = re.findall(r"\b\w+\b", (article.title or "").lower())
    abstract_terms = re.findall(r"\b\w+\b", (article.abstract or "").lower())

    keywords = getattr(article, "keywords", []) or []
    mesh_terms = getattr(article, "mesh_terms", []) or []
    keyword_text = " ".join(keywords + mesh_terms).lower()
    keyword_terms = re.findall(r"\b\w+\b", keyword_text)

    # Full document terms for TF calculation
    all_terms = title_terms + abstract_terms + keyword_terms
    doc_length = len(all_terms)

    # Build term frequency map
    tf_map: dict[str, int] = {}
    for term in all_terms:
        tf_map[term] = tf_map.get(term, 0) + 1

    # Title term set and keyword term set (for boosting)
    title_set = set(title_terms)
    keyword_set = set(keyword_terms)

    N = corpus.total_docs
    avgdl = corpus.avg_doc_length

    score = 0.0
    for qt in query_terms:
        # Document frequency
        df = corpus.doc_freq.get(qt, 0)

        # IDF with log(1+x) form (always non-negative)
        idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))

        # Term frequency in document
        tf = tf_map.get(qt, 0)

        # BM25 TF component
        tf_norm = (tf * (_BM25_K1 + 1)) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_length / max(avgdl, 1)))

        # Apply field boost
        boost = 1.0
        if qt in title_set:
            boost = _BM25_TITLE_BOOST
        elif qt in keyword_set:
            boost = _BM25_MESH_BOOST

        score += idf * tf_norm * boost

    return score


def bm25_score_normalized(
    article: UnifiedArticle,
    query: str,
    corpus: BM25Corpus,
    max_score: float,
) -> float:
    """
    Calculate normalized BM25 score in [0, 1] range.

    Divides raw BM25 score by the maximum observed score in the corpus.

    Args:
        article: Article to score
        query: Search query
        corpus: Pre-computed corpus statistics
        max_score: Maximum BM25 score in the current result set

    Returns:
        Normalized score in [0.0, 1.0]
    """
    if max_score <= 0:
        return 0.5  # Neutral fallback

    raw = bm25_score(article, query, corpus)
    return min(raw / max_score, 1.0)


# =============================================================================
# Reciprocal Rank Fusion (RRF)
# =============================================================================

_RRF_K = 60  # Standard RRF constant (Cormack et al., 2009)


@dataclass
class RRFResult:
    """Result of RRF fusion with per-article scores and diagnostics."""

    ranked_articles: list[UnifiedArticle]
    rrf_scores: dict[str, float]  # article_key → RRF score
    dimension_contributions: dict[str, dict[str, float]]  # article_key → {dim: contribution}


def reciprocal_rank_fusion(
    articles: list[UnifiedArticle],
    dimension_rankings: dict[str, list[str]],
    k: int = _RRF_K,
) -> RRFResult:
    """
    Apply Reciprocal Rank Fusion to combine multiple ranking dimensions.

    RRF formula:
        RRF(d) = Σ_r 1/(k + rank_r(d))

    where r iterates over ranking dimensions and rank_r(d) is the
    1-based rank of document d in dimension r.

    This is proven to outperform individual rankers and other fusion
    methods (Condorcet, CombMNZ) without requiring score calibration.

    Args:
        articles: List of articles to rank
        dimension_rankings: {dimension_name: [article_keys in ranked order]}
            Each value is a list of article keys (PMID/DOI/title) sorted by
            that dimension's score (best first).
        k: RRF constant (default 60, proven optimal in TREC evaluations)

    Returns:
        RRFResult with fused ranking, scores, and per-dimension contributions
    """
    # Build article key lookup
    article_map: dict[str, UnifiedArticle] = {}
    for article in articles:
        key = _article_key(article)
        article_map[key] = article

    # Build rank lookup for each dimension
    dim_rank_maps: dict[str, dict[str, int]] = {}
    for dim_name, ranked_keys in dimension_rankings.items():
        rank_map: dict[str, int] = {}
        for rank_1based, akey in enumerate(ranked_keys, start=1):
            rank_map[akey] = rank_1based
        dim_rank_maps[dim_name] = rank_map

    n_articles = len(articles)
    rrf_scores: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}

    for akey in article_map:
        dim_contribs: dict[str, float] = {}
        total = 0.0
        for dim_name, rank_map in dim_rank_maps.items():
            # Articles not in a dimension's ranking get worst rank
            rank = rank_map.get(akey, n_articles + 1)
            contrib = 1.0 / (k + rank)
            dim_contribs[dim_name] = contrib
            total += contrib

        rrf_scores[akey] = total
        contributions[akey] = dim_contribs

    # Sort articles by RRF score (descending)
    sorted_articles = sorted(
        articles,
        key=lambda a: rrf_scores.get(_article_key(a), 0),
        reverse=True,
    )

    return RRFResult(
        ranked_articles=sorted_articles,
        rrf_scores=rrf_scores,
        dimension_contributions=contributions,
    )


# =============================================================================
# Maximal Marginal Relevance (MMR)
# =============================================================================


@dataclass
class MMRResult:
    """Result of MMR diversification."""

    articles: list[UnifiedArticle]
    diversity_scores: dict[str, float]  # article_key → MMR score at selection time
    avg_pairwise_distance: float  # Average pairwise Jaccard distance in selected set


def mmr_diversify(
    articles: list[UnifiedArticle],
    query: str,
    lambda_param: float = 0.7,
    top_k: int | None = None,
) -> MMRResult:
    """
    Apply Maximal Marginal Relevance for result diversification.

    MMR iteratively selects documents that balance relevance and novelty:
        MMR(d) = λ × Sim(d, query) - (1-λ) × max_{d' ∈ S} Sim(d, d')

    Uses MeSH term + keyword Jaccard similarity (no ML embeddings needed).
    This is both efficient and domain-appropriate for biomedical literature.

    Args:
        articles: Pre-ranked articles (by relevance score)
        query: Original search query (for relevance component)
        lambda_param: Balance between relevance (1.0) and diversity (0.0).
            Default 0.7 = slight preference for relevance.
        top_k: Number of results to select. None = all articles.

    Returns:
        MMRResult with diversified article list and diagnostics
    """
    if len(articles) <= 1:
        return MMRResult(
            articles=articles,
            diversity_scores={_article_key(a): 1.0 for a in articles},
            avg_pairwise_distance=1.0,
        )

    n = len(articles)
    top_k = top_k or n

    # Pre-compute term sets for each article (MeSH + keywords + title terms)
    term_sets: list[set[str]] = []
    for article in articles:
        terms = set()
        for mesh in getattr(article, "mesh_terms", []) or []:
            terms.add(mesh.lower())
        for kw in getattr(article, "keywords", []) or []:
            terms.add(kw.lower())
        # Add significant title tokens (>= 4 chars to skip stop words)
        if article.title:
            for token in re.findall(r"\b\w{4,}\b", article.title.lower()):
                terms.add(token)
        term_sets.append(terms)

    # Query term set
    query_terms = set(re.findall(r"\b\w{3,}\b", query.lower()))

    # Pre-compute relevance scores (use existing ranking_score if available)
    relevance_scores: list[float] = []
    for article in articles:
        score = getattr(article, "ranking_score", None)
        if score is not None:
            relevance_scores.append(score)
        else:
            # Fallback: Jaccard with query
            relevance_scores.append(_jaccard_similarity(term_sets[articles.index(article)], query_terms))

    # Normalize relevance to [0, 1]
    max_rel = max(relevance_scores) if relevance_scores else 1.0
    if max_rel > 0:
        norm_relevance = [r / max_rel for r in relevance_scores]
    else:
        norm_relevance = [0.5] * n

    # MMR greedy selection
    selected_indices: list[int] = []
    remaining = set(range(n))
    diversity_scores: dict[str, float] = {}

    # Start with highest relevance article
    first_idx = max(range(n), key=lambda i: norm_relevance[i])
    selected_indices.append(first_idx)
    remaining.remove(first_idx)
    diversity_scores[_article_key(articles[first_idx])] = norm_relevance[first_idx]

    while remaining and len(selected_indices) < top_k:
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            # Relevance component
            rel = norm_relevance[idx]

            # Diversity component: max similarity to any already-selected article
            max_sim = 0.0
            for sel_idx in selected_indices:
                sim = _jaccard_similarity(term_sets[idx], term_sets[sel_idx])
                if sim > max_sim:
                    max_sim = sim

            # MMR formula
            mmr = lambda_param * rel - (1 - lambda_param) * max_sim

            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx >= 0:
            selected_indices.append(best_idx)
            remaining.remove(best_idx)
            diversity_scores[_article_key(articles[best_idx])] = best_mmr

    # Calculate average pairwise distance in selected set
    avg_dist = _average_pairwise_distance(
        [term_sets[i] for i in selected_indices],
    )

    selected_articles = [articles[i] for i in selected_indices]

    return MMRResult(
        articles=selected_articles,
        diversity_scores=diversity_scores,
        avg_pairwise_distance=avg_dist,
    )


# =============================================================================
# Source Disagreement Analysis
# =============================================================================


@dataclass
class SourceDisagreement:
    """
    Analysis of how different sources rank the same query results.

    Quantifies cross-source ranking consistency as a novel quality signal.
    High agreement → well-established topic. Low agreement → emerging/controversial.
    """

    source_agreement_score: float  # 0-1, higher = more agreement
    source_complementarity: float  # 0-1, higher = sources find different articles
    cross_source_articles: int  # Articles found by 2+ sources
    single_source_articles: int  # Articles found by only 1 source
    per_source_unique: dict[str, int]  # source → count of exclusively unique articles
    rank_correlation: dict[str, float]  # source_pair → Kendall tau correlation

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "source_agreement_score": round(self.source_agreement_score, 3),
            "source_complementarity": round(self.source_complementarity, 3),
            "cross_source_articles": self.cross_source_articles,
            "single_source_articles": self.single_source_articles,
            "per_source_unique": self.per_source_unique,
            "rank_correlation": {k: round(v, 3) for k, v in self.rank_correlation.items()},
        }


def analyze_source_disagreement(
    articles: list[UnifiedArticle],
    source_rankings: dict[str, list[str]] | None = None,
) -> SourceDisagreement:
    """
    Analyze disagreement between different academic data sources.

    This is a novel contribution: no existing system quantifies how different
    sources rank the same literature. Disagreement signals:
    - Emerging research (sources haven't converged)
    - Interdisciplinary topics (different sources prioritize differently)
    - Controversial findings (conflicting evidence)

    Calculates:
    1. Source Agreement Score (SAS): Based on rank correlation across sources
    2. Source Complementarity: Fraction of articles unique to one source
    3. Per-source unique counts
    4. Pairwise rank correlation (Kendall tau simplified)

    Args:
        articles: Deduplicated articles with source tracking
        source_rankings: Optional pre-computed {source: [article_keys]} rankings.
            If not provided, inferred from article.sources metadata.

    Returns:
        SourceDisagreement with all metrics
    """
    # Classify articles by source coverage
    source_to_articles: dict[str, list[str]] = {}
    article_to_sources: dict[str, list[str]] = {}

    for article in articles:
        key = _article_key(article)
        sources: list[str] = []

        # Get sources from SourceMetadata
        source_metas = getattr(article, "sources", []) or []
        for sm in source_metas:
            src_name = sm.source if hasattr(sm, "source") else str(sm)
            sources.append(src_name)

        # Always include primary_source
        if article.primary_source and article.primary_source not in sources:
            sources.append(article.primary_source)

        article_to_sources[key] = sources

        for src in sources:
            if src not in source_to_articles:
                source_to_articles[src] = []
            source_to_articles[src].append(key)

    total = len(articles)
    if total == 0:
        return SourceDisagreement(
            source_agreement_score=1.0,
            source_complementarity=0.0,
            cross_source_articles=0,
            single_source_articles=0,
            per_source_unique={},
            rank_correlation={},
        )

    # Count cross-source vs single-source
    cross_source = sum(1 for sources in article_to_sources.values() if len(sources) > 1)
    single_source = total - cross_source

    # Per-source unique (articles found ONLY by this source)
    per_source_unique: dict[str, int] = {}
    for src, art_keys in source_to_articles.items():
        unique_count = sum(1 for k in art_keys if len(article_to_sources.get(k, [])) == 1)
        per_source_unique[src] = unique_count

    # Source complementarity = fraction of articles from only 1 source
    complementarity = single_source / total if total > 0 else 0.0

    # Source Agreement Score: based on overlap between all source pairs
    rank_correlation: dict[str, float] = {}
    all_sas_values: list[float] = []

    source_names = sorted(source_to_articles.keys())
    for i in range(len(source_names)):
        for j in range(i + 1, len(source_names)):
            src_a = source_names[i]
            src_b = source_names[j]
            set_a = set(source_to_articles[src_a])
            set_b = set(source_to_articles[src_b])

            # Overlap coefficient: |A ∩ B| / min(|A|, |B|)
            intersection = len(set_a & set_b)
            min_size = min(len(set_a), len(set_b))
            overlap = intersection / max(min_size, 1)

            pair_key = f"{src_a}↔{src_b}"
            rank_correlation[pair_key] = overlap
            all_sas_values.append(overlap)

    # Overall SAS: average of all pairwise overlaps
    if all_sas_values:
        sas = sum(all_sas_values) / len(all_sas_values)
    elif len(source_names) <= 1:
        sas = 1.0  # Single source = perfect agreement (trivially)
    else:
        sas = 0.0

    return SourceDisagreement(
        source_agreement_score=sas,
        source_complementarity=complementarity,
        cross_source_articles=cross_source,
        single_source_articles=single_source,
        per_source_unique=per_source_unique,
        rank_correlation=rank_correlation,
    )


# =============================================================================
# Utility Functions
# =============================================================================


def _article_key(article: UnifiedArticle) -> str:
    """Get unique key for article (PMID > DOI > title hash)."""
    if article.pmid:
        return f"pmid:{article.pmid}"
    if article.doi:
        return f"doi:{article.doi}"
    return f"title:{hash(article.title)}"


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity coefficient: |A ∩ B| / |A ∪ B|."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _average_pairwise_distance(term_sets: list[set[str]]) -> float:
    """Average pairwise Jaccard distance in a set of documents."""
    n = len(term_sets)
    if n < 2:
        return 1.0

    total_distance = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard_similarity(term_sets[i], term_sets[j])
            total_distance += 1.0 - sim  # Distance = 1 - similarity
            count += 1

    return total_distance / count if count > 0 else 1.0
