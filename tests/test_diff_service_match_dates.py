from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine, select

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Base, PublishJob
from app.services.diff_service import DiffService
from app.settings import AppSettings
from app.storage.database import create_session_factory
from app.storage.repositories import MatchRepository, TournamentRepository


def test_detect_and_queue_jobs_skips_unscheduled_tomorrow_matches_until_all_are_arranged() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="903:2026:2026-05-24:2026-06-07",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 24),
                    end_date=date(2026, 6, 7),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="tomorrow-unscheduled-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Round 3",
                    scheduled_at_utc=None,
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "U",
                        "MatchTimeStamp": "2026-05-29T09:00:00+00:00",
                        "Unscheduled": True,
                        "isEstimatedStartTime": True,
                        "RoundID": "3",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert jobs == []
