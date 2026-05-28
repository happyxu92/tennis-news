from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.models import Base
from app.publisher.service import PublisherService
from app.settings import AppSettings
from app.storage.database import create_session_factory
from app.storage.repositories import PublishedArticleRepository, PublishJobRepository


class FakeWeChatClient:
    def __init__(self) -> None:
        self.inline_uploads: list[Path] = []
        self.cover_uploads: list[Path] = []
        self.submitted_media_ids: list[str] = []
        self.publish_status_response = {
            "publish_id": "publish-1",
            "publish_status": 0,
            "article_id": "article-1",
            "article_detail": {
                "count": 1,
                "item": [{"idx": 1, "article_url": "https://mp.weixin.qq.com/s/article-1"}],
            },
            "fail_idx": [],
        }

    async def aclose(self) -> None:
        return None

    async def upload_cover_image(self, image_path: str | Path) -> dict[str, str | None]:
        path = Path(image_path)
        self.cover_uploads.append(path)
        return {"media_id": "cover-media", "url": "https://mmbiz.test/cover.jpg"}

    async def upload_inline_image(self, image_path: str | Path) -> str:
        path = Path(image_path)
        self.inline_uploads.append(path)
        return "https://mmbiz.test/inline.png"

    async def create_draft(self, article: dict) -> str:
        return "draft-media"

    async def submit_publish(self, media_id: str) -> str:
        self.submitted_media_ids.append(media_id)
        return "publish-1"

    async def get_publish_status(self, publish_id: str) -> dict:
        return self.publish_status_response


class FailingWeChatClient(FakeWeChatClient):
    async def create_draft(self, article: dict) -> str:
        raise RuntimeError("draft creation failed")


def _build_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.mark.asyncio
async def test_dispatch_pending_jobs_marks_job_success_when_draft_created(
    tmp_path: Path,
) -> None:
    session_factory = _build_session_factory()
    cover_file = tmp_path / "cover.jpg"
    cover_file.write_bytes(b"cover")

    with session_factory() as session:
        publish_jobs = PublishJobRepository(session)
        articles = PublishedArticleRepository(session)
        job = publish_jobs.create(
            job_type="result_article",
            biz_key="result:1",
            content_hash="hash-1",
            payload={
                "tournament_name": "Roland Garros",
                "round_name": "Quarterfinal",
                "scheduled_at_local": "2026-05-28T18:00:00+08:00",
                "court_name": "Court Philippe-Chatrier",
                "player1_name": "Qinwen Zheng",
                "player2_name": "Player B",
                "score_text": "6-4,6-4",
                "winner_name": "Qinwen Zheng",
                "status": "finished",
            },
        )
        session.commit()

        wechat_client = FakeWeChatClient()
        service = PublisherService(
            settings=AppSettings(
                wechat_publish_enabled=True,
                wechat_default_cover_image_path=str(cover_file),
            ),
            session=session,
            wechat_client=wechat_client,
        )

        result = await service.dispatch_pending_jobs()

        stored_job = publish_jobs.get_by_id(job.id)
        stored_article = articles.get_by_job_id(job.id)

        assert result.success_job_ids == [job.id]
        assert stored_job is not None
        assert stored_job.status == "success"
        assert stored_job.payload["draft_media_id"] == "draft-media"
        assert stored_job.payload["delivery_mode"] == "draft_only"
        assert stored_article is not None
        assert stored_article.wechat_media_id == "draft-media"
        assert stored_article.publish_id is None
        assert wechat_client.submitted_media_ids == []


@pytest.mark.asyncio
async def test_dispatch_pending_jobs_reuses_existing_cover_media_id() -> None:
    session_factory = _build_session_factory()

    with session_factory() as session:
        publish_jobs = PublishJobRepository(session)
        job = publish_jobs.create(
            job_type="result_article",
            biz_key="result:media-id",
            content_hash="hash-media-id",
            payload={
                "tournament_name": "Roland Garros",
                "player1_name": "Player A",
                "player2_name": "Player B",
                "status": "finished",
            },
        )
        session.commit()

        wechat_client = FakeWeChatClient()
        service = PublisherService(
            settings=AppSettings(
                wechat_publish_enabled=True,
                wechat_default_cover_media_id="existing-cover-media-id",
            ),
            session=session,
            wechat_client=wechat_client,
        )

        result = await service.dispatch_pending_jobs()
        stored_job = publish_jobs.get_by_id(job.id)

        assert result.success_job_ids == [job.id]
        assert stored_job is not None
        assert stored_job.status == "success"
        assert stored_job.payload["cover_media_id"] == "existing-cover-media-id"
        assert wechat_client.cover_uploads == []
        assert wechat_client.submitted_media_ids == []


@pytest.mark.asyncio
async def test_sync_publishing_jobs_marks_success_and_saves_article_url(tmp_path: Path) -> None:
    session_factory = _build_session_factory()

    with session_factory() as session:
        publish_jobs = PublishJobRepository(session)
        articles = PublishedArticleRepository(session)
        job = publish_jobs.create(
            job_type="schedule_article",
            biz_key="schedule:1:2026-05-29",
            content_hash="hash-1",
            payload={
                "rendered_title": "Roland Garros05月29日赛程更新",
                "draft_media_id": "draft-media",
                "publish_id": "publish-1",
            },
            status="publishing",
        )
        articles.upsert(
            job_id=job.id,
            title="Roland Garros05月29日赛程更新",
            content_hash="hash-1",
            wechat_media_id="draft-media",
            publish_id="publish-1",
            article_url=None,
            published_at=None,
        )
        session.commit()

        service = PublisherService(
            settings=AppSettings(wechat_publish_enabled=True),
            session=session,
            wechat_client=FakeWeChatClient(),
        )

        result = await service.sync_publishing_jobs()

        stored_job = publish_jobs.get_by_id(job.id)
        stored_article = articles.get_by_job_id(job.id)

        assert result.success_job_ids == [job.id]
        assert stored_job is not None
        assert stored_job.status == "success"
        assert stored_job.payload["article_url"] == "https://mp.weixin.qq.com/s/article-1"
        assert stored_article is not None
        assert stored_article.article_url == "https://mp.weixin.qq.com/s/article-1"
        assert stored_article.published_at is not None


@pytest.mark.asyncio
async def test_dispatch_pending_jobs_marks_retryable_on_failure(tmp_path: Path) -> None:
    session_factory = _build_session_factory()
    cover_file = tmp_path / "cover.jpg"
    cover_file.write_bytes(b"cover")

    with session_factory() as session:
        publish_jobs = PublishJobRepository(session)
        job = publish_jobs.create(
            job_type="result_article",
            biz_key="result:2",
            content_hash="hash-2",
            payload={
                "tournament_name": "Roland Garros",
                "player1_name": "Player A",
                "player2_name": "Player B",
                "status": "finished",
            },
        )
        session.commit()

        service = PublisherService(
            settings=AppSettings(
                wechat_publish_enabled=True,
                wechat_default_cover_image_path=str(cover_file),
                wechat_publish_max_retries=2,
            ),
            session=session,
            wechat_client=FailingWeChatClient(),
        )

        result = await service.dispatch_pending_jobs()

        stored_job = publish_jobs.get_by_id(job.id)

        assert result.retryable_job_ids == [job.id]
        assert stored_job is not None
        assert stored_job.status == "retryable"
        assert stored_job.retry_count == 1
        assert stored_job.payload["last_error_stage"] == "draft_create"
        assert stored_job.error_message == "draft creation failed"
