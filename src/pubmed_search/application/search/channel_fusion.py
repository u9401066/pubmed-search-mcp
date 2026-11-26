"""Fuse independently ranked retrieval channels for hybrid search.

Each channel (PubMed Best Match, a full-text index, a semantic index) returns
its own ranked list. Fusion uses only those provider ranks:

    score(d) = sum over channels c of  weight_c / (k + rank_c(d))

so a provider's relevance order is never replaced by a local re-scoring of
abstracts. A record found by several channels outranks one found by a single
channel at the same position.

Breadth quota: a share of the returned slots is reserved for records the
primary channel did not return, so a full-text or semantic hit is not pushed
out by a long primary list. Reserved slots are only used when such records
exist, and those records are labelled, never presented as primary matches.

This module is pure: no I/O and no provider knowledge beyond channel names.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pubmed_search.domain.entities.article import ChannelHit
from pubmed_search.shared.article_identity import (
    normalize_article_doi,
    normalize_article_identifier,
    normalize_article_title,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pubmed_search.domain.entities.article import UnifiedArticle

RRF_K = 60
DEFAULT_BREADTH_QUOTA = 0.25
DEFAULT_PRIMARY_CHANNEL = "pubmed"
#: The caller's own query on the primary channel counts double: it is the only
#: channel that ran the query as written.
DEFAULT_CHANNEL_WEIGHTS: dict[str, float] = {"pubmed": 2.0}
#: Hybrid-search channels in fusion order: the caller's query on PubMed, a
#: full-text index, and a semantic index.
HYBRID_CHANNELS: tuple[str, ...] = ("pubmed", "europe_pmc", "openalex")
HYBRID_CHANNEL_MIN_DEPTH = 50
HYBRID_CHANNEL_MAX_DEPTH = 100


def hybrid_channel_limit(limit: int) -> int:
    """Records to request per channel: deeper than ``limit`` so ranks can disagree usefully."""
    return max(HYBRID_CHANNEL_MIN_DEPTH, min(HYBRID_CHANNEL_MAX_DEPTH, limit * 3))


@dataclass(frozen=True)
class FusionReport:
    """What fusion did, for disclosure to the agent."""

    channels: dict[str, int]
    """Records each channel returned (after in-channel deduplication)."""
    multi_channel: int
    """Returned records found by two or more channels."""
    breadth_only: int
    """Returned records the primary channel did not return."""
    breadth_slots: int
    """Slots reserved for breadth-only records."""
    primary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": "channel_rrf",
            "primary_channel": self.primary,
            "channels": dict(self.channels),
            "multi_channel_records": self.multi_channel,
            "breadth_only_records": self.breadth_only,
            "breadth_slots": self.breadth_slots,
        }


def identity_keys(article: UnifiedArticle) -> tuple[str, ...]:
    """Return every stable key under which ``article`` may match another record."""
    keys: list[str] = []
    if pmid := normalize_article_identifier("pmid", article.pmid):
        keys.append(f"pmid:{pmid}")
    if doi := normalize_article_doi(article.doi):
        keys.append(f"doi:{doi}")
    if pmc := normalize_article_identifier("pmc", article.pmc):
        keys.append(f"pmc:{pmc.upper()}")
    if not keys and (title := normalize_article_title(article.title)):
        keys.append(f"title:{title}:{article.year or ''}")
    return tuple(keys)


def _channel_ranks(articles: Sequence[UnifiedArticle]) -> dict[str, int]:
    """Map every identity key to the 1-based rank of its first record."""
    ranks: dict[str, int] = {}
    position = 0
    for article in articles:
        keys = identity_keys(article)
        if not keys or any(key in ranks for key in keys):
            continue
        position += 1
        for key in keys:
            ranks[key] = position
    return ranks


def fuse_channels(
    merged: Sequence[UnifiedArticle],
    channel_results: Mapping[str, Sequence[UnifiedArticle]],
    *,
    limit: int,
    primary: str = DEFAULT_PRIMARY_CHANNEL,
    breadth_quota: float = DEFAULT_BREADTH_QUOTA,
    weights: Mapping[str, float] | None = None,
    k: int = RRF_K,
) -> tuple[list[UnifiedArticle], FusionReport]:
    """Order ``merged`` by weighted reciprocal-rank fusion of provider ranks.

    Args:
        merged: Deduplicated records (one per work) to order.
        channel_results: Each channel's records in provider rank order.
        limit: Number of records to return.
        primary: Channel that ran the caller's query as written.
        breadth_quota: Share of ``limit`` reserved for records ``primary`` did
            not return (0 disables the reservation).
        weights: Per-channel RRF weights; unnamed channels weigh 1.
        k: RRF constant.

    Returns:
        The ordered records (each with ``channels`` and ``ranking_score`` set)
        and a disclosure report.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if not 0 <= breadth_quota < 1:
        raise ValueError("breadth_quota must be in [0, 1)")
    if k < 0:
        raise ValueError("k must be non-negative")
    channel_weights = {**DEFAULT_CHANNEL_WEIGHTS, **(weights or {})}
    ranks_by_channel = {channel: _channel_ranks(articles) for channel, articles in channel_results.items()}

    scored: list[tuple[float, int, UnifiedArticle]] = []
    for order, article in enumerate(merged):
        keys = identity_keys(article)
        hits: list[ChannelHit] = []
        score = 0.0
        for channel, ranks in ranks_by_channel.items():
            rank = min((ranks[key] for key in keys if key in ranks), default=None)
            if rank is None:
                continue
            hits.append(ChannelHit(channel=channel, rank=rank))
            score += channel_weights.get(channel, 1.0) / (k + rank)
        article.channels = hits
        scored.append((score, order, article))
    scored.sort(key=lambda item: (-item[0], item[1]))
    top_score = scored[0][0] if scored and scored[0][0] > 0 else 1.0
    for score, _order, article in scored:
        article.ranking_score = score / top_score

    ordered = [article for _score, _order, article in scored]
    has_primary = primary in ranks_by_channel
    breadth_pool = [article for article in ordered if not article.found_by(primary)] if has_primary else []
    breadth_slots = min(len(breadth_pool), math.floor(limit * breadth_quota)) if has_primary else 0

    selected = ordered[:limit]
    missing = breadth_slots - sum(1 for article in selected if not article.found_by(primary))
    if missing > 0:
        # Replace the lowest-ranked primary records with the best breadth-only
        # records that fell below the cut; fused order is kept within each group.
        chosen = {id(article) for article in selected}
        promoted = [article for article in breadth_pool if id(article) not in chosen][:missing]
        kept: list[UnifiedArticle] = []
        to_drop = len(promoted)
        for article in reversed(selected):
            if to_drop and article.found_by(primary):
                to_drop -= 1
                continue
            kept.append(article)
        selected = [*reversed(kept), *promoted]

    report = FusionReport(
        channels={channel: len(set(ranks.values())) for channel, ranks in ranks_by_channel.items()},
        multi_channel=sum(1 for article in selected if len(article.channels) > 1),
        breadth_only=sum(1 for article in selected if has_primary and not article.found_by(primary)),
        breadth_slots=breadth_slots,
        primary=primary,
    )
    return selected, report


__all__ = [
    "DEFAULT_BREADTH_QUOTA",
    "DEFAULT_CHANNEL_WEIGHTS",
    "DEFAULT_PRIMARY_CHANNEL",
    "HYBRID_CHANNELS",
    "hybrid_channel_limit",
    "RRF_K",
    "FusionReport",
    "fuse_channels",
    "identity_keys",
]
