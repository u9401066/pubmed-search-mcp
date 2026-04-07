"""APScheduler-backed scheduling service for saved pipelines."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from pubmed_search.domain.entities.pipeline import ScheduleEntry
from pubmed_search.shared.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from pubmed_search.application.pipeline.runner import StoredPipelineRunner
    from pubmed_search.application.pipeline.store import PipelineStore

logger = logging.getLogger(__name__)


class APSPipelineScheduler:
    """Manage saved pipeline schedules and execute them via APScheduler."""

    def __init__(
        self,
        *,
        store: PipelineStore,
        runner: StoredPipelineRunner,
        settings: AppSettings | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._settings = settings or load_settings()
        self._timezone = self._resolve_timezone(self._settings.scheduler_timezone)
        self._scheduler = AsyncIOScheduler(
            timezone=self._timezone,
            job_defaults={
                "coalesce": self._settings.scheduler_coalesce,
                "max_instances": self._settings.scheduler_max_instances,
                "misfire_grace_time": self._settings.scheduler_misfire_grace_seconds,
            },
        )
        self._started = False

    def start(self) -> None:
        """Start the APScheduler loop and restore persisted schedules."""
        if self._started or not self._settings.scheduler_enabled:
            return

        self._scheduler.start()
        self._started = True
        for entry in self._store.list_schedules():
            if entry.enabled:
                self._register_live_job(entry)

    def shutdown(self) -> None:
        """Stop the APScheduler loop."""
        if not self._started:
            return

        with suppress(Exception):
            self._scheduler.shutdown(wait=False)
        self._started = False

    def schedule(self, name: str, cron: str, *, diff_mode: bool = True, notify: bool = True) -> ScheduleEntry:
        """Create or update one persisted pipeline schedule."""
        if not self._settings.scheduler_enabled:
            msg = "Pipeline scheduler is disabled via settings"
            raise RuntimeError(msg)

        pipeline_name = name.strip().lower()
        if not self._store.exists(pipeline_name):
            msg = f"Pipeline '{pipeline_name}' not found"
            raise FileNotFoundError(msg)

        trigger = self._build_trigger(cron)
        existing = self._store.get_schedule(pipeline_name)
        entry = ScheduleEntry(
            pipeline_name=pipeline_name,
            cron=cron.strip(),
            enabled=True,
            diff_mode=diff_mode,
            notify=notify,
            timezone=str(self._timezone),
            next_run=trigger.get_next_fire_time(None, datetime.now(self._timezone)),
            last_run=existing.last_run if existing else None,
            last_status=existing.last_status if existing else "scheduled",
            last_error=existing.last_error if existing else None,
        )
        self._store.save_schedule(entry)

        if self._started:
            self._register_live_job(entry)

        return self.get_schedule(pipeline_name) or entry

    def unschedule(self, name: str) -> ScheduleEntry | None:
        """Remove a persisted pipeline schedule and any live APScheduler job."""
        pipeline_name = name.strip().lower()
        entry = self.get_schedule(pipeline_name)

        if self._started:
            with suppress(JobLookupError):
                self._scheduler.remove_job(self._job_id(pipeline_name))

        self._store.delete_schedule(pipeline_name)
        return entry

    def get_schedule(self, name: str) -> ScheduleEntry | None:
        """Get one schedule, merging in the current live next-run time if available."""
        pipeline_name = name.strip().lower()
        entry = self._store.get_schedule(pipeline_name)
        if entry is None:
            return None

        if self._started:
            job = self._scheduler.get_job(self._job_id(pipeline_name))
            if job is not None:
                entry.next_run = job.next_run_time
        elif entry.enabled:
            entry.next_run = self._build_trigger(entry.cron).get_next_fire_time(None, datetime.now(self._timezone))

        return entry

    def list_schedules(self) -> list[ScheduleEntry]:
        """List all persisted schedules with live next-run times when available."""
        schedules: list[ScheduleEntry] = []
        for entry in self._store.list_schedules():
            schedules.append(self.get_schedule(entry.pipeline_name) or entry)
        return schedules

    def _register_live_job(self, entry: ScheduleEntry) -> None:
        """Register or update one live APScheduler job from a persisted entry."""
        trigger = self._build_trigger(entry.cron)
        job = self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=self._job_id(entry.pipeline_name),
            replace_existing=True,
            kwargs={"pipeline_name": entry.pipeline_name},
        )
        entry.next_run = job.next_run_time
        self._store.save_schedule(entry)

    async def _execute_job(self, pipeline_name: str) -> None:
        """Execute one scheduled pipeline and persist updated schedule status."""
        entry = self._store.get_schedule(pipeline_name)
        if entry is None:
            logger.warning("Skipping scheduled run for missing entry: %s", pipeline_name)
            return

        try:
            run = await self._runner.execute_saved_pipeline(pipeline_name)
            entry.last_run = run.finished or run.started or datetime.now(timezone.utc)
            entry.last_status = "success"
            entry.last_error = None
        except Exception as exc:
            entry.last_run = datetime.now(timezone.utc)
            entry.last_status = "error"
            entry.last_error = str(exc)
        finally:
            job = self._scheduler.get_job(self._job_id(pipeline_name))
            entry.next_run = job.next_run_time if job is not None else None
            self._store.save_schedule(entry)

    def _build_trigger(self, cron: str) -> CronTrigger:
        """Build a validated cron trigger from a 5-field crontab expression."""
        cron_expr = cron.strip()
        if not cron_expr:
            msg = "Cron expression is required"
            raise ValueError(msg)
        try:
            return CronTrigger.from_crontab(cron_expr, timezone=self._timezone)
        except ValueError as exc:
            msg = f"Invalid cron expression '{cron_expr}': {exc}"
            raise ValueError(msg) from exc

    def _resolve_timezone(self, timezone_name: str) -> ZoneInfo:
        """Resolve configured scheduler timezone."""
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            msg = f"Unknown scheduler timezone: {timezone_name}"
            raise ValueError(msg) from exc

    @staticmethod
    def _job_id(pipeline_name: str) -> str:
        """Stable APScheduler job identifier for one pipeline."""
        return f"pipeline:{pipeline_name}"
