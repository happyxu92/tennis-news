from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Match, MatchSnapshot, PublishedArticle, PublishJob, Tournament

UNSET = object()


class TournamentRepository:
    """Persistence access for tournaments."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, tournaments: Iterable[NormalizedTournament]) -> list[Tournament]:
        stored: list[Tournament] = []
        for item in tournaments:
            entity = self.session.scalar(
                select(Tournament).where(
                    Tournament.source == item.source,
                    Tournament.source_tournament_id == item.source_tournament_id,
                )
            )
            if entity is None:
                entity = Tournament(
                    source=item.source,
                    source_tournament_id=item.source_tournament_id,
                )
                self.session.add(entity)

            entity.name = item.name
            entity.tour = item.tour
            entity.level = item.level
            entity.surface = item.surface
            entity.location = item.location
            entity.start_date = item.start_date
            entity.end_date = item.end_date
            entity.metadata_json = item.metadata
            stored.append(entity)

        self.session.flush()
        return stored

    def get_by_source_id(self, source: str, source_tournament_id: str) -> Tournament | None:
        return self.session.scalar(
            select(Tournament).where(
                Tournament.source == source,
                Tournament.source_tournament_id == source_tournament_id,
            )
        )

    def list_in_sync_window(self, utc_today: date, future_days: int) -> list[Tournament]:
        window_end = utc_today + timedelta(days=future_days)
        statement = (
            select(Tournament)
            .where(Tournament.end_date.is_not(None), Tournament.end_date >= utc_today)
            .where(Tournament.start_date.is_not(None), Tournament.start_date <= window_end)
            .order_by(Tournament.start_date.asc(), Tournament.id.asc())
        )
        return list(self.session.scalars(statement))


class MatchRepository:
    """Persistence access for matches and snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, matches: Iterable[NormalizedMatch]) -> list[Match]:
        stored: list[Match] = []
        seen_keys: set[tuple[str, str]] = set()
        for item in matches:
            key = (item.source, item.source_match_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            entity = self.session.scalar(
                select(Match).where(
                    Match.source == item.source,
                    Match.source_match_id == item.source_match_id,
                )
            )
            if entity is None:
                entity = Match(source=item.source, source_match_id=item.source_match_id)
                self.session.add(entity)

            entity.tournament_id = item.tournament_id
            entity.round_name = item.round_name
            entity.scheduled_at_utc = item.scheduled_at_utc
            entity.court_name = item.court_name
            entity.player1_name = item.player1_name
            entity.player2_name = item.player2_name
            entity.player1_country = item.player1_country
            entity.player2_country = item.player2_country
            entity.player1_seed = item.player1_seed
            entity.player2_seed = item.player2_seed
            entity.status = item.status
            entity.score_text = item.score_text
            entity.winner_name = item.winner_name
            entity.is_key_match = item.is_key_match
            entity.metadata_json = item.metadata
            stored.append(entity)

        self.session.flush()
        return stored

    def create_snapshot(
        self,
        match_id: int,
        snapshot_type: str,
        snapshot_hash: str,
        payload: dict,
    ) -> MatchSnapshot:
        snapshot = MatchSnapshot(
            match_id=match_id,
            snapshot_type=snapshot_type,
            snapshot_hash=snapshot_hash,
            payload=payload,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def list_by_tournament_ids(self, tournament_ids: Iterable[int]) -> list[Match]:
        ids = list(dict.fromkeys(tournament_ids))
        if not ids:
            return []

        statement = select(Match).where(Match.tournament_id.in_(ids)).order_by(Match.id.asc())
        return list(self.session.scalars(statement))

    def list_recent_snapshots(
        self,
        match_ids: Iterable[int],
        snapshot_type: str,
        limit_per_match: int = 2,
    ) -> dict[int, list[MatchSnapshot]]:
        ids = list(dict.fromkeys(match_ids))
        if not ids:
            return {}

        statement = (
            select(MatchSnapshot)
            .where(
                MatchSnapshot.match_id.in_(ids),
                MatchSnapshot.snapshot_type == snapshot_type,
            )
            .order_by(
                MatchSnapshot.match_id.asc(),
                MatchSnapshot.created_at.desc(),
                MatchSnapshot.id.desc(),
            )
        )

        grouped: dict[int, list[MatchSnapshot]] = {}
        for snapshot in self.session.scalars(statement):
            bucket = grouped.setdefault(snapshot.match_id, [])
            if len(bucket) < limit_per_match:
                bucket.append(snapshot)
        return grouped


class PublishJobRepository:
    """Persistence access for publish jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        job_type: str,
        biz_key: str,
        content_hash: str,
        payload: dict,
        status: str = "pending",
    ) -> PublishJob:
        entity = PublishJob(
            job_type=job_type,
            biz_key=biz_key,
            content_hash=content_hash,
            payload=payload,
            status=status,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def get_by_id(self, job_id: int) -> PublishJob | None:
        return self.session.get(PublishJob, job_id)

    def list_by_statuses(
        self,
        statuses: Iterable[str],
        limit: int | None = None,
    ) -> list[PublishJob]:
        values = list(dict.fromkeys(statuses))
        if not values:
            return []

        statement = (
            select(PublishJob)
            .where(PublishJob.status.in_(values))
            .order_by(PublishJob.created_at.asc(), PublishJob.id.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def get_by_biz_key_and_content_hash(
        self,
        job_type: str,
        biz_key: str,
        content_hash: str,
    ) -> PublishJob | None:
        statement = select(PublishJob).where(
            PublishJob.job_type == job_type,
            PublishJob.biz_key == biz_key,
            PublishJob.content_hash == content_hash,
        )
        return self.session.scalar(statement)

    def get_latest_by_biz_key(self, job_type: str, biz_key: str) -> PublishJob | None:
        statement = (
            select(PublishJob)
            .where(PublishJob.job_type == job_type, PublishJob.biz_key == biz_key)
            .order_by(PublishJob.created_at.desc(), PublishJob.id.desc())
        )
        return self.session.scalar(statement)

    def count_by_biz_key(self, job_type: str, biz_key: str) -> int:
        statement = select(func.count(PublishJob.id)).where(
            PublishJob.job_type == job_type,
            PublishJob.biz_key == biz_key,
        )
        return int(self.session.scalar(statement) or 0)

    def update(
        self,
        job: PublishJob,
        *,
        status: str | None = None,
        payload_updates: dict[str, Any] | None = None,
        error_message: str | object = UNSET,
        increment_retry: bool = False,
    ) -> PublishJob:
        if status is not None:
            job.status = status
        if payload_updates:
            payload = dict(job.payload or {})
            payload.update(payload_updates)
            job.payload = payload
        if error_message is not UNSET:
            job.error_message = error_message
        if increment_retry:
            job.retry_count += 1

        self.session.add(job)
        self.session.flush()
        return job


class PublishedArticleRepository:
    """Persistence access for published article records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_job_id(self, job_id: int) -> PublishedArticle | None:
        statement = select(PublishedArticle).where(PublishedArticle.job_id == job_id)
        return self.session.scalar(statement)

    def upsert(
        self,
        *,
        job_id: int,
        title: str,
        content_hash: str,
        wechat_media_id: str | None = None,
        publish_id: str | None = None,
        article_url: str | None = None,
        published_at=None,
    ) -> PublishedArticle:
        entity = self.get_by_job_id(job_id)
        if entity is None:
            entity = PublishedArticle(job_id=job_id, title=title, content_hash=content_hash)
            self.session.add(entity)

        entity.title = title
        entity.content_hash = content_hash
        entity.wechat_media_id = wechat_media_id
        entity.publish_id = publish_id
        entity.article_url = article_url
        entity.published_at = published_at
        self.session.flush()
        return entity
