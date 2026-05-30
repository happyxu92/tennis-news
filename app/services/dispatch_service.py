from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.publisher.service import PublisherService, PublishRunResult
from app.settings import AppSettings

logger = get_logger(__name__)


class DispatchService:
    """Runs publish job dispatch workflows."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session: Session,
        publisher: PublisherService | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.publisher = publisher or PublisherService(settings=settings, session=session)

    async def dispatch_pending_jobs(self, limit: int | None = None) -> PublishRunResult:
        result = await self.publisher.dispatch_pending_jobs(limit=limit)
        if result.retryable_job_ids or result.failed_job_ids:
            logger.warning(
                "dispatch completed with issues: %s retryable, %s failed",
                len(result.retryable_job_ids),
                len(result.failed_job_ids),
            )
        return result

    async def sync_publishing_jobs(self, limit: int | None = None) -> PublishRunResult:
        result = await self.publisher.sync_publishing_jobs(limit=limit)
        if result.retryable_job_ids or result.failed_job_ids:
            logger.warning(
                "publish status sync completed with issues: %s retryable, %s failed",
                len(result.retryable_job_ids),
                len(result.failed_job_ids),
            )
        return result

    async def aclose(self) -> None:
        await self.publisher.aclose()
