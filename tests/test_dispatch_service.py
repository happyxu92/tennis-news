from __future__ import annotations

import pytest

from app.publisher.service import PublishRunResult
from app.services.dispatch_service import DispatchService
from app.settings import AppSettings


class FakePublisherService:
    def __init__(self) -> None:
        self.dispatch_limits: list[int | None] = []
        self.sync_limits: list[int | None] = []
        self.closed = False

    async def dispatch_pending_jobs(self, limit: int | None = None) -> PublishRunResult:
        self.dispatch_limits.append(limit)
        return PublishRunResult(processed_job_ids=[1], success_job_ids=[1])

    async def sync_publishing_jobs(self, limit: int | None = None) -> PublishRunResult:
        self.sync_limits.append(limit)
        return PublishRunResult(processed_job_ids=[2], success_job_ids=[2])

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_dispatch_service_delegates_pending_job_dispatch() -> None:
    publisher = FakePublisherService()
    service = DispatchService(
        settings=AppSettings(),
        session=None,
        publisher=publisher,
    )

    result = await service.dispatch_pending_jobs(limit=5)
    await service.aclose()

    assert publisher.dispatch_limits == [5]
    assert publisher.closed is True
    assert result.processed_job_ids == [1]
    assert result.success_job_ids == [1]


@pytest.mark.asyncio
async def test_dispatch_service_delegates_publish_status_sync() -> None:
    publisher = FakePublisherService()
    service = DispatchService(
        settings=AppSettings(),
        session=None,
        publisher=publisher,
    )

    result = await service.sync_publishing_jobs(limit=3)

    assert publisher.sync_limits == [3]
    assert result.processed_job_ids == [2]
    assert result.success_job_ids == [2]
