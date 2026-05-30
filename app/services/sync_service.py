from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.crawler.schemas import CrawlBundle
from app.crawler.service import CrawlerService
from app.logging import get_logger
from app.services.diff_service import DiffRunResult, DiffService
from app.settings import AppSettings

logger = get_logger(__name__)


@dataclass(slots=True)
class SyncRunResult:
    crawl_bundle: CrawlBundle
    diff_result: DiffRunResult


class SyncService:
    """Runs the sync and diff phases as one workflow."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session: Session,
        crawler_service: CrawlerService | None = None,
        diff_service: DiffService | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.crawler_service = crawler_service or CrawlerService(settings=settings, session=session)
        self.diff_service = diff_service or DiffService(settings=settings, session=session)

    async def run_once(self, now_utc: datetime | None = None) -> SyncRunResult:
        crawl_bundle = await self.crawler_service.sync_all(now_utc=now_utc)
        diff_result = self.diff_service.detect_and_queue_jobs(now_utc=now_utc)
        logger.info(
            "sync workflow completed: %s tournaments, %s matches, %s jobs created",
            len(crawl_bundle.tournaments),
            len(crawl_bundle.matches),
            len(diff_result.created_job_ids),
        )
        return SyncRunResult(crawl_bundle=crawl_bundle, diff_result=diff_result)
