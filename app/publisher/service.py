from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.publisher.renderer import ArticleRenderer
from app.publisher.wechat_client import WeChatAPIError, WeChatClient
from app.settings import AppSettings
from app.storage.repositories import PublishedArticleRepository, PublishJobRepository

logger = get_logger(__name__)

PENDING_STATUSES = ("pending", "retryable")
PUBLISHING_STATUS = "publishing"
INLINE_IMAGE_RE = re.compile(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
PUBLISH_STATUS_LABELS = {
    2: "original_check_failed",
    3: "publish_failed",
    4: "review_rejected",
    5: "deleted_after_publish",
    6: "blocked_after_publish",
}


@dataclass(slots=True)
class PublishRunResult:
    processed_job_ids: list[int] = field(default_factory=list)
    publishing_job_ids: list[int] = field(default_factory=list)
    success_job_ids: list[int] = field(default_factory=list)
    retryable_job_ids: list[int] = field(default_factory=list)
    failed_job_ids: list[int] = field(default_factory=list)


class PublisherService:
    """Creates WeChat drafts for publish jobs and tracks legacy publish status."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session: Session,
        renderer: ArticleRenderer | None = None,
        wechat_client: WeChatClient | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.renderer = renderer or ArticleRenderer(article_timezone=settings.article_timezone)
        self.publish_jobs = PublishJobRepository(session)
        self.published_articles = PublishedArticleRepository(session)
        self.wechat_client = wechat_client or WeChatClient(
            app_id=settings.wechat_app_id,
            app_secret=settings.wechat_app_secret,
            timeout=settings.wechat_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self.wechat_client.aclose()

    async def dispatch_pending_jobs(self, limit: int | None = None) -> PublishRunResult:
        result = PublishRunResult()
        if not self.settings.wechat_publish_enabled:
            logger.info("wechat publishing is disabled, skipping pending jobs")
            return result

        jobs = self.publish_jobs.list_by_statuses(PENDING_STATUSES, limit=limit)
        for job in jobs:
            result.processed_job_ids.append(job.id)
            await self._dispatch_job(job, result)

        logger.info(
            (
                "publisher dispatched %s jobs, %s completed, %s moved to publishing, "
                "%s retryable, %s failed"
            ),
            len(result.processed_job_ids),
            len(result.success_job_ids),
            len(result.publishing_job_ids),
            len(result.retryable_job_ids),
            len(result.failed_job_ids),
        )
        return result

    async def sync_publishing_jobs(self, limit: int | None = None) -> PublishRunResult:
        result = PublishRunResult()
        if not self.settings.wechat_publish_enabled:
            logger.info("wechat publishing is disabled, skipping publish status sync")
            return result

        jobs = self.publish_jobs.list_by_statuses((PUBLISHING_STATUS,), limit=limit)
        for job in jobs:
            result.processed_job_ids.append(job.id)
            await self._sync_job_status(job, result)

        logger.info(
            "publisher checked %s publishing jobs, %s succeeded, %s retryable, %s failed",
            len(result.processed_job_ids),
            len(result.success_job_ids),
            len(result.retryable_job_ids),
            len(result.failed_job_ids),
        )
        return result

    async def _dispatch_job(self, job, result: PublishRunResult) -> None:
        claimed_job = self.publish_jobs.get_by_id(job.id)
        if claimed_job is None:
            return

        self.publish_jobs.update(
            claimed_job,
            status="processing",
            payload_updates={"processing_started_at": self._utcnow_iso()},
            error_message=None,
        )
        self.session.commit()

        stage = "render"
        try:
            article = self.renderer.render(claimed_job.job_type, claimed_job.payload)

            stage = "inline_images"
            html = await self._rewrite_inline_images(article.html)

            stage = "cover_prepare"
            cover_upload = await self._resolve_cover_asset(claimed_job.payload)

            stage = "draft_create"
            draft_media_id = await self.wechat_client.create_draft(
                {
                    "article_type": "news",
                    "title": article.title,
                    "author": self.settings.wechat_author,
                    "digest": article.summary,
                    "content": html,
                    "thumb_media_id": cover_upload["media_id"],
                    "content_source_url": claimed_job.payload.get("content_source_url"),
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                }
            )

            self.published_articles.upsert(
                job_id=claimed_job.id,
                title=article.title,
                content_hash=claimed_job.content_hash,
                wechat_media_id=draft_media_id,
                publish_id=None,
                article_url=None,
                published_at=None,
            )
            self.publish_jobs.update(
                claimed_job,
                status="success",
                payload_updates={
                    "rendered_title": article.title,
                    "rendered_summary": article.summary,
                    "draft_media_id": draft_media_id,
                    "cover_media_id": cover_upload["media_id"],
                    "cover_url": cover_upload.get("url"),
                    "draft_created_at": self._utcnow_iso(),
                    "delivery_mode": "draft_only",
                },
                error_message=None,
            )
            self.session.commit()
            result.success_job_ids.append(claimed_job.id)
        except Exception as exc:
            self.session.rollback()
            failed_job = self.publish_jobs.get_by_id(job.id)
            if failed_job is not None:
                self._mark_job_failure(failed_job, stage=stage, error=exc, result=result)

    async def _sync_job_status(self, job, result: PublishRunResult) -> None:
        publish_id = (job.payload or {}).get("publish_id")
        if not publish_id:
            self._mark_job_failure(
                job,
                stage="publish_status",
                error=ValueError("publish_id is missing from publish job payload"),
                result=result,
            )
            return

        try:
            response = await self.wechat_client.get_publish_status(publish_id)
        except Exception as exc:
            self._mark_job_failure(job, stage="publish_status", error=exc, result=result)
            return

        publish_status = int(response["publish_status"])
        payload_updates = {
            "last_publish_status": publish_status,
            "last_publish_status_checked_at": self._utcnow_iso(),
            "last_publish_status_response": response,
        }
        if publish_status == 1:
            self.publish_jobs.update(job, payload_updates=payload_updates)
            self.session.commit()
            return

        if publish_status == 0:
            article_url = self._extract_article_url(response)
            published_at = datetime.now(UTC)
            title = (job.payload or {}).get("rendered_title") or job.biz_key
            self.published_articles.upsert(
                job_id=job.id,
                title=title,
                content_hash=job.content_hash,
                wechat_media_id=(job.payload or {}).get("draft_media_id"),
                publish_id=publish_id,
                article_url=article_url,
                published_at=published_at,
            )
            self.publish_jobs.update(
                job,
                status="success",
                payload_updates={
                    **payload_updates,
                    "article_id": response.get("article_id"),
                    "article_url": article_url,
                    "publish_completed_at": published_at.isoformat(),
                },
                error_message=None,
            )
            self.session.commit()
            result.success_job_ids.append(job.id)
            return

        label = PUBLISH_STATUS_LABELS.get(publish_status, f"publish_status_{publish_status}")
        self._mark_job_failure(
            job,
            stage=label,
            error=WeChatAPIError(
                f"WeChat publish returned status {publish_status}",
                response=response,
            ),
            result=result,
            extra_payload=payload_updates,
        )

    async def _rewrite_inline_images(self, html: str) -> str:
        matches = list(INLINE_IMAGE_RE.finditer(html))
        if not matches:
            return html

        replacements: dict[str, str] = {}
        for match in matches:
            source = match.group(2)
            if source in replacements or self._is_remote_image_source(source):
                continue
            image_path = self._resolve_inline_image_path(source)
            replacements[source] = await self.wechat_client.upload_inline_image(image_path)

        if not replacements:
            return html

        def replace(match: re.Match[str]) -> str:
            source = match.group(2)
            replacement = replacements.get(source)
            if replacement is None:
                return match.group(0)
            return f"{match.group(1)}{replacement}{match.group(3)}"

        return INLINE_IMAGE_RE.sub(replace, html)

    async def _resolve_cover_asset(self, payload: dict[str, Any]) -> dict[str, str | None]:
        configured_media_id = (
            payload.get("thumb_media_id")
            or payload.get("cover_media_id")
            or self.settings.wechat_default_cover_media_id
        )
        if configured_media_id:
            return {"media_id": configured_media_id, "url": None}

        cover_path = self._resolve_cover_image_path(payload)
        return await self.wechat_client.upload_cover_image(cover_path)

    def _resolve_cover_image_path(self, payload: dict[str, Any]) -> Path:
        configured = (
            payload.get("cover_image_path") or self.settings.wechat_default_cover_image_path
        )
        if not configured:
            raise ValueError(
                "WeChat draft articles require a cover. Configure "
                "wechat_default_cover_image_path or wechat_default_cover_media_id"
            )
        return self._resolve_local_path(configured)

    def _resolve_inline_image_path(self, source: str) -> Path:
        return self._resolve_local_path(source)

    def _resolve_local_path(self, source: str) -> Path:
        parsed = urlparse(source)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
        elif parsed.scheme:
            raise ValueError(f"Unsupported local image source: {source}")
        else:
            path = Path(source)

        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Image file does not exist: {path}")
        return path

    def _is_remote_image_source(self, source: str) -> bool:
        parsed = urlparse(source)
        return parsed.scheme in {"http", "https", "data"}

    def _extract_article_url(self, response: dict[str, Any]) -> str | None:
        detail = response.get("article_detail") or {}
        items = detail.get("item") or []
        if not items:
            return None
        return items[0].get("article_url")

    def _mark_job_failure(
        self,
        job,
        *,
        stage: str,
        error: Exception,
        result: PublishRunResult,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        next_retry_count = job.retry_count + 1
        status = (
            "retryable"
            if next_retry_count < self.settings.wechat_publish_max_retries
            else "failed"
        )
        payload_updates = {
            "last_error_stage": stage,
            "last_error_at": self._utcnow_iso(),
        }
        if extra_payload:
            payload_updates.update(extra_payload)

        self.publish_jobs.update(
            job,
            status=status,
            payload_updates=payload_updates,
            error_message=str(error),
            increment_retry=True,
        )
        self.session.commit()
        if status == "retryable":
            result.retryable_job_ids.append(job.id)
        else:
            result.failed_job_ids.append(job.id)

        logger.warning("publish job %s failed at %s: %s", job.id, stage, error)

    def _utcnow_iso(self) -> str:
        return datetime.now(UTC).isoformat()
