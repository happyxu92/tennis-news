from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine

from app.crawler.schemas import CrawlBundle
from app.models import Base
from app.publisher.service import PublishRunResult
from app.services.diff_service import DiffRunResult
from app.services.scheduler_service import SchedulerService
from app.services.sync_service import SyncRunResult
from app.settings import AppSettings
from app.storage.database import create_session_factory


@dataclass
class FakeJob:
    func: object
    trigger: str
    minutes: int
    id: str
    replace_existing: bool
    coalesce: bool
    max_instances: int


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.running = False
        self.started = False
        self.shutdown_called = False

    def get_job(self, job_id: str) -> FakeJob | None:
        return self.jobs.get(job_id)

    def add_job(
        self,
        func,
        *,
        trigger: str,
        minutes: int,
        id: str,
        replace_existing: bool,
        coalesce: bool,
        max_instances: int,
    ) -> FakeJob:
        job = FakeJob(
            func=func,
            trigger=trigger,
            minutes=minutes,
            id=id,
            replace_existing=replace_existing,
            coalesce=coalesce,
            max_instances=max_instances,
        )
        self.jobs[id] = job
        return job

    def start(self) -> None:
        self.running = True
        self.started = True

    def shutdown(self, wait: bool = False) -> None:
        self.running = False
        self.shutdown_called = True


class FakeSyncService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def run_once(self) -> SyncRunResult:
        self.events.append("sync")
        return SyncRunResult(
            crawl_bundle=CrawlBundle(),
            diff_result=DiffRunResult(
                utc_today=date(2026, 5, 30),
                schedule_target_date=date(2026, 5, 31),
                created_job_ids=[11],
            ),
        )


class FakeDispatchService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def dispatch_pending_jobs(self) -> PublishRunResult:
        self.events.append("dispatch")
        return PublishRunResult(processed_job_ids=[21], success_job_ids=[21])

    async def aclose(self) -> None:
        self.events.append("close")


def _build_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def test_scheduler_service_configures_interval_job() -> None:
    scheduler = FakeScheduler()
    service = SchedulerService(
        settings=AppSettings(scheduler_interval_minutes=15),
        session_factory=_build_session_factory(),
        scheduler=scheduler,
    )

    service.configure_jobs()

    job = scheduler.get_job(SchedulerService.JOB_ID)
    assert job is not None
    assert job.trigger == "interval"
    assert job.minutes == 15
    assert job.coalesce is True
    assert job.max_instances == 1


@pytest.mark.asyncio
async def test_scheduler_service_runs_sync_then_dispatch_with_separate_sessions() -> None:
    events: list[str] = []
    seen_sessions: list[tuple[str, int]] = []
    session_factory = _build_session_factory()

    def build_sync_service(session):
        seen_sessions.append(("sync", id(session)))
        return FakeSyncService(events)

    def build_dispatch_service(session):
        seen_sessions.append(("dispatch", id(session)))
        return FakeDispatchService(events)

    service = SchedulerService(
        settings=AppSettings(),
        session_factory=session_factory,
        scheduler=FakeScheduler(),
        sync_service_factory=build_sync_service,
        dispatch_service_factory=build_dispatch_service,
    )

    result = await service.run_cycle(trigger="manual")

    assert events == ["sync", "dispatch", "close"]
    assert result.sync_result.diff_result.created_job_ids == [11]
    assert result.publish_result.success_job_ids == [21]
    assert seen_sessions[0][0] == "sync"
    assert seen_sessions[1][0] == "dispatch"
    assert seen_sessions[0][1] != seen_sessions[1][1]


@pytest.mark.asyncio
async def test_scheduler_service_run_forever_executes_startup_cycle_before_waiting() -> None:
    events: list[str] = []
    stop_event = asyncio.Event()
    stop_event.set()
    scheduler = FakeScheduler()
    session_factory = _build_session_factory()

    service = SchedulerService(
        settings=AppSettings(),
        session_factory=session_factory,
        scheduler=scheduler,
        sync_service_factory=lambda session: FakeSyncService(events),
        dispatch_service_factory=lambda session: FakeDispatchService(events),
    )

    await service.run_forever(stop_event=stop_event)

    assert events == ["sync", "dispatch", "close"]
    assert scheduler.started is True
    assert scheduler.get_job(SchedulerService.JOB_ID) is not None
