"""
Timeline Application Services

This package provides timeline building and milestone detection logic.

Modules:
    - timeline_builder: Build research timelines from search results
    - milestone_detector: Pattern-based milestone detection

Usage:
    >>> from pubmed_search.application.timeline import TimelineBuilder
    >>> builder = TimelineBuilder(searcher)
    >>> timeline = builder.build_timeline("remimazolam", max_events=50)
"""

from __future__ import annotations

from .milestone_detector import MilestoneDetector
from .timeline_builder import TimelineBuilder

__all__ = ["MilestoneDetector", "TimelineBuilder"]
