"""Regression tests for datetime parsing shared by supported Python runtimes."""

from __future__ import annotations

from datetime import datetime, timezone

from pubmed_search.application.session import CachedArticle
from pubmed_search.domain.entities.pipeline import PipelineMeta, PipelineRun, ScheduleEntry
from pubmed_search.shared.cache_substrate import StoredCacheEntry

UTC_TIMESTAMP = "2026-08-10T04:05:06Z"


def test_cache_entry_from_dict_accepts_utc_z_designator() -> None:
    entry = StoredCacheEntry.from_dict(
        {
            "value": "cached",
            "cached_at": UTC_TIMESTAMP,
            "expires_at": UTC_TIMESTAMP,
        }
    )

    assert not entry.is_expired(now=datetime(2026, 8, 10, 4, 5, 5, tzinfo=timezone.utc))
    assert entry.is_expired(now=datetime(2026, 8, 10, 4, 5, 6, tzinfo=timezone.utc))


def test_cached_article_is_expired_accepts_utc_z_designator() -> None:
    article = CachedArticle.from_article_data(
        "12345678",
        {
            "title": "Compatibility study",
            "authors": [],
            "abstract": "",
            "journal": "",
            "year": "2000",
            "cached_at": "2000-01-01T00:00:00Z",
        },
    )

    assert article.is_expired(max_age_days=7)


def test_pipeline_from_dict_contracts_accept_utc_z_designator() -> None:
    metadata = PipelineMeta.from_dict(
        {
            "name": "utc-compatible",
            "created": UTC_TIMESTAMP,
            "updated": UTC_TIMESTAMP,
        }
    )
    run = PipelineRun.from_dict(
        {
            "run_id": "run-1",
            "started": UTC_TIMESTAMP,
            "finished": UTC_TIMESTAMP,
        }
    )
    schedule = ScheduleEntry.from_dict(
        {
            "pipeline_name": "utc-compatible",
            "cron": "0 8 * * *",
            "next_run": UTC_TIMESTAMP,
            "last_run": UTC_TIMESTAMP,
        }
    )

    parsed_values = (
        metadata.created,
        metadata.updated,
        run.started,
        run.finished,
        schedule.next_run,
        schedule.last_run,
    )
    assert all(value is not None and value.utcoffset() == timezone.utc.utcoffset(value) for value in parsed_values)
