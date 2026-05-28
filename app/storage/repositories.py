from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Match, MatchSnapshot, PublishJob, Tournament


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
