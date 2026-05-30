from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.crawler.schemas import CrawlBundle
from app.services.diff_service import DiffRunResult
from app.services.sync_service import SyncService
from app.settings import AppSettings


class FakeCrawlerService:
    def __init__(self, events: list[str], crawl_bundle: CrawlBundle) -> None:
        self.events = events
        self.crawl_bundle = crawl_bundle
        self.calls: list[datetime | None] = []

    async def sync_all(self, now_utc: datetime | None = None) -> CrawlBundle:
        self.events.append("crawl")
        self.calls.append(now_utc)
        return self.crawl_bundle


class FakeDiffService:
    def __init__(self, events: list[str], diff_result: DiffRunResult) -> None:
        self.events = events
        self.diff_result = diff_result
        self.calls: list[datetime | None] = []

    def detect_and_queue_jobs(self, now_utc: datetime | None = None) -> DiffRunResult:
        self.events.append("diff")
        self.calls.append(now_utc)
        return self.diff_result


@pytest.mark.asyncio
async def test_sync_service_runs_crawl_before_diff() -> None:
    events: list[str] = []
    now_utc = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    crawl_bundle = CrawlBundle()
    diff_result = DiffRunResult(
        utc_today=date(2026, 5, 30),
        schedule_target_date=date(2026, 5, 31),
        created_job_ids=[101, 102],
    )
    crawler = FakeCrawlerService(events=events, crawl_bundle=crawl_bundle)
    diff_service = FakeDiffService(events=events, diff_result=diff_result)
    service = SyncService(
        settings=AppSettings(),
        session=None,
        crawler_service=crawler,
        diff_service=diff_service,
    )

    result = await service.run_once(now_utc=now_utc)

    assert events == ["crawl", "diff"]
    assert crawler.calls == [now_utc]
    assert diff_service.calls == [now_utc]
    assert result.crawl_bundle is crawl_bundle
    assert result.diff_result is diff_result
