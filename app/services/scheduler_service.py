from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session, sessionmaker

from app.logging import get_logger
from app.publisher.service import PublishRunResult
from app.services.dispatch_service import DispatchService
from app.services.sync_service import SyncRunResult, SyncService
from app.settings import AppSettings

logger = get_logger(__name__)


@dataclass(slots=True)
class AutomationRunResult:
    sync_result: SyncRunResult
    publish_result: PublishRunResult


class SchedulerService:
    """Runs the automated sync and publishing loop."""

    JOB_ID = "automation-cycle"

    def __init__(
        self,
        *,
        settings: AppSettings,
        session_factory: sessionmaker[Session],
        scheduler: AsyncIOScheduler | None = None,
        sync_service_factory: Callable[[Session], SyncService] | None = None,
        dispatch_service_factory: Callable[[Session], DispatchService] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self.sync_service_factory = sync_service_factory or self._build_sync_service
        self.dispatch_service_factory = dispatch_service_factory or self._build_dispatch_service

    def configure_jobs(self) -> None:
        if self.scheduler.get_job(self.JOB_ID) is not None:
            return

        self.scheduler.add_job(
            self._run_scheduled_cycle,
            trigger="interval",
            minutes=self.settings.scheduler_interval_minutes,
            id=self.JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    def start(self) -> None:
        self.configure_jobs()
        if self.scheduler.running:
            return

        self.scheduler.start()
        logger.info(
            "scheduler started with %s minute interval",
            self.settings.scheduler_interval_minutes,
        )

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def run_startup_cycle(self) -> AutomationRunResult | None:
        return await self.run_cycle_safely(trigger="startup")

    async def run_cycle(
        self,
        *,
        trigger: str = "manual",
    ) -> AutomationRunResult:
        logger.info("automation cycle started (%s)", trigger)
        sync_result = await self._run_sync_phase()
        publish_result = await self._run_dispatch_phase()
        logger.info(
            (
                "automation cycle completed (%s): %s tournaments, %s matches, "
                "%s jobs created, %s jobs processed, %s succeeded, %s retryable, %s failed"
            ),
            trigger,
            len(sync_result.crawl_bundle.tournaments),
            len(sync_result.crawl_bundle.matches),
            len(sync_result.diff_result.created_job_ids),
            len(publish_result.processed_job_ids),
            len(publish_result.success_job_ids),
            len(publish_result.retryable_job_ids),
            len(publish_result.failed_job_ids),
        )
        if publish_result.retryable_job_ids or publish_result.failed_job_ids:
            logger.warning(
                "automation cycle completed with publish issues (%s): %s retryable, %s failed",
                trigger,
                len(publish_result.retryable_job_ids),
                len(publish_result.failed_job_ids),
            )
        return AutomationRunResult(sync_result=sync_result, publish_result=publish_result)

    async def run_cycle_safely(self, *, trigger: str) -> AutomationRunResult | None:
        try:
            return await self.run_cycle(trigger=trigger)
        except Exception:
            logger.exception("automation cycle failed (%s)", trigger)
            return None

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await self.run_startup_cycle()
        self.start()
        await (stop_event or asyncio.Event()).wait()

    def _build_sync_service(self, session: Session) -> SyncService:
        return SyncService(settings=self.settings, session=session)

    def _build_dispatch_service(self, session: Session) -> DispatchService:
        return DispatchService(settings=self.settings, session=session)

    async def _run_scheduled_cycle(self) -> None:
        await self.run_cycle_safely(trigger="scheduled")

    async def _run_sync_phase(self) -> SyncRunResult:
        with self.session_factory() as session:
            service = self.sync_service_factory(session)
            return await service.run_once()

    async def _run_dispatch_phase(self) -> PublishRunResult:
        with self.session_factory() as session:
            service = self.dispatch_service_factory(session)
            try:
                return await service.dispatch_pending_jobs()
            finally:
                await service.aclose()
