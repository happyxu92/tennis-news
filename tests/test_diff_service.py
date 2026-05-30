from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine, select

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Base, PublishJob
from app.services.diff_service import DiffService
from app.settings import AppSettings
from app.storage.database import create_session_factory
from app.storage.repositories import MatchRepository, PublishJobRepository, TournamentRepository


def _build_service():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    return session_factory


def test_detect_and_queue_jobs_creates_next_day_schedule_job_and_same_day_result_job() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        today_match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                    player1_name="Qinwen Zheng",
                    player2_name="Player B",
                    player1_country="CHN",
                    player2_country="USA",
                    status="finished",
                    score_text="6-4,6-4",
                    winner_name="Qinwen Zheng",
                    is_key_match=True,
                    metadata={
                        "MatchState": "F",
                        "ScoreString": "6-4,6-4",
                        "Winner": "2",
                        "PlayerNameFirstA": "Qinwen",
                        "PlayerNameLastA": "Zheng",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "PlayerCountryA": "CHN",
                        "PlayerCountryB": "USA",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
                    },
                ),
                NormalizedMatch(
                    source="wta",
                    source_match_id="tomorrow-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Semifinal",
                    scheduled_at_utc=datetime(2026, 5, 29, 9, 0, tzinfo=UTC),
                    player1_name="Player C",
                    player2_name="Player D",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "C",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "D",
                        "RoundID": "6",
                        "MatchTimeStamp": "2026-05-29T09:00:00+00:00",
                    },
                ),
            ]
        )
        session.flush()

        match_repo.create_snapshot(
            match_id=today_match[0].id,
            snapshot_type="upstream_sync",
            snapshot_hash="old-today",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Qinwen",
                "PlayerNameLastA": "Zheng",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "PlayerCountryA": "CHN",
                "PlayerCountryB": "USA",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
            },
        )
        match_repo.create_snapshot(
            match_id=today_match[0].id,
            snapshot_type="upstream_sync",
            snapshot_hash="new-today",
            payload=today_match[0].metadata_json,
        )
        match_repo.create_snapshot(
            match_id=today_match[1].id,
            snapshot_type="upstream_sync",
            snapshot_hash="old-tomorrow",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "C",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "D",
                "RoundID": "6",
            },
        )
        match_repo.create_snapshot(
            match_id=today_match[1].id,
            snapshot_type="upstream_sync",
            snapshot_hash="new-tomorrow",
            payload=today_match[1].metadata_json,
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        result = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(select(PublishJob).order_by(PublishJob.job_type.asc())).all()

        assert result.utc_today == date(2026, 5, 28)
        assert result.schedule_target_date == date(2026, 5, 29)
        assert result.schedule_target_dates == [date(2026, 5, 28), date(2026, 5, 29)]
        assert len(result.result_changes) == 1
        assert len(result.schedule_changes) == 1
        assert len(jobs) == 3
        assert jobs[0].job_type == "result_article"
        assert jobs[0].biz_key == f"result:{today_match[0].id}"
        assert jobs[0].payload["scheduled_at_utc"] == "2026-05-28T10:00:00+00:00"
        assert jobs[0].payload["scheduled_at_local"] == "2026-05-28T18:00:00+08:00"
        assert jobs[0].payload["court_name"] is None
        assert jobs[1].job_type == "schedule_article"
        assert jobs[1].biz_key == f"schedule:{tournament.id}:2026-05-28"
        assert jobs[1].payload["is_update"] is False
        assert jobs[1].payload["release_version"] == 1
        assert jobs[1].payload["source"] == "wta"
        assert jobs[2].job_type == "schedule_article"
        assert jobs[2].biz_key == f"schedule:{tournament.id}:2026-05-29"
        assert jobs[2].payload["is_update"] is False
        assert jobs[2].payload["release_version"] == 1
        assert jobs[2].payload["source"] == "wta"


def test_detect_and_queue_jobs_creates_today_schedule_job_when_missing() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-schedule-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
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
        result = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 8, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(result.schedule_changes) == 1
        assert len(jobs) == 1
        assert jobs[0].biz_key == f"schedule:{tournament.id}:2026-05-28"
        assert jobs[0].payload["target_utc_date"] == "2026-05-28"
        assert jobs[0].payload["is_update"] is False
        assert jobs[0].payload["release_version"] == 1


def test_detect_and_queue_jobs_marks_schedule_job_as_update_when_content_changes() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)
        publish_repo = PublishJobRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="tomorrow-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Semifinal",
                    scheduled_at_utc=datetime(2026, 5, 29, 12, 0, tzinfo=UTC),
                    court_name="Center Court",
                    player1_name="Player C",
                    player2_name="Player D",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "C",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "D",
                        "RoundID": "6",
                        "MatchTimeStamp": "2026-05-29T12:00:00+00:00",
                        "Venue": {"name": "Center Court"},
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "C",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "D",
                "RoundID": "6",
                "MatchTimeStamp": "2026-05-29T11:00:00+00:00",
                "Venue": {"name": "Court 1"},
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.flush()

        publish_repo.create(
            job_type="schedule_article",
            biz_key=f"schedule:{tournament.id}:2026-05-29",
            content_hash="existing-hash",
            payload={"matches": []},
            status="success",
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(jobs) == 2
        assert jobs[1].payload["is_update"] is True
        assert jobs[1].payload["previous_job_id"] == jobs[0].id
        assert jobs[1].payload["release_version"] == 2


def test_detect_and_queue_jobs_updates_today_schedule_job_when_content_changes() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)
        publish_repo = PublishJobRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 14, 0, tzinfo=UTC),
                    court_name="Center Court",
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T14:00:00+00:00",
                        "Venue": {"name": "Center Court"},
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "A",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T13:00:00+00:00",
                "Venue": {"name": "Court 1"},
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.flush()

        publish_repo.create(
            job_type="schedule_article",
            biz_key=f"schedule:{tournament.id}:2026-05-28",
            content_hash="existing-hash",
            payload={"matches": []},
            status="success",
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(jobs) == 2
        assert jobs[1].biz_key == f"schedule:{tournament.id}:2026-05-28"
        assert jobs[1].payload["is_update"] is True
        assert jobs[1].payload["previous_job_id"] == jobs[0].id
        assert jobs[1].payload["release_version"] == 2


def test_detect_and_queue_jobs_skips_schedule_update_for_non_scheduled_status_change() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)
        publish_repo = PublishJobRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-finished",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 14, 0, tzinfo=UTC),
                    court_name="Center Court",
                    player1_name="Player A",
                    player2_name="Player B",
                    status="finished",
                    score_text="6-4,6-4",
                    winner_name="Player A",
                    metadata={
                        "MatchState": "F",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T14:00:00+00:00",
                        "Venue": {"name": "Center Court"},
                        "ScoreString": "6-4,6-4",
                        "Winner": "2",
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "A",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T14:00:00+00:00",
                "Venue": {"name": "Center Court"},
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.flush()

        publish_repo.create(
            job_type="schedule_article",
            biz_key=f"schedule:{tournament.id}:2026-05-28",
            content_hash="existing-hash",
            payload={"matches": []},
            status="success",
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        result = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert result.schedule_changes == []
        assert len(result.result_changes) == 1
        assert len(jobs) == 1


def test_detect_and_queue_jobs_updates_schedule_when_status_returns_to_scheduled() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)
        publish_repo = PublishJobRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-rescheduled",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 14, 0, tzinfo=UTC),
                    court_name="Center Court",
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T14:00:00+00:00",
                        "Venue": {"name": "Center Court"},
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "D",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "A",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T14:00:00+00:00",
                "Venue": {"name": "Center Court"},
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.flush()

        publish_repo.create(
            job_type="schedule_article",
            biz_key=f"schedule:{tournament.id}:2026-05-28",
            content_hash="existing-hash",
            payload={"matches": []},
            status="success",
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        result = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(result.schedule_changes) == 1
        assert result.schedule_changes[0].change_types == ["status_changed"]
        assert len(jobs) == 2
        assert jobs[1].payload["is_update"] is True
        assert jobs[1].payload["release_version"] == 2


def test_detect_and_queue_jobs_is_idempotent_for_existing_content_hash() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                    player1_name="Qinwen Zheng",
                    player2_name="Player B",
                    player1_country="CHN",
                    player2_country="USA",
                    status="finished",
                    score_text="6-4,6-4",
                    winner_name="Qinwen Zheng",
                    is_key_match=True,
                    metadata={
                        "MatchState": "F",
                        "ScoreString": "6-4,6-4",
                        "Winner": "2",
                        "PlayerNameFirstA": "Qinwen",
                        "PlayerNameLastA": "Zheng",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "PlayerCountryA": "CHN",
                        "PlayerCountryB": "USA",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Qinwen",
                "PlayerNameLastA": "Zheng",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "PlayerCountryA": "CHN",
                "PlayerCountryB": "USA",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        first = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
        second = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 5, tzinfo=UTC))

        jobs = session.scalars(select(PublishJob)).all()

        assert len(first.created_job_ids) == 2
        assert second.created_job_ids == []
        assert len(jobs) == 2


def test_detect_and_queue_jobs_skips_non_key_match_results() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        match = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-1",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                    player1_name="Player A",
                    player2_name="Player B",
                    player1_country="USA",
                    player2_country="CAN",
                    status="finished",
                    score_text="6-4,6-4",
                    winner_name="Player A",
                    is_key_match=False,
                    metadata={
                        "MatchState": "F",
                        "ScoreString": "6-4,6-4",
                        "Winner": "2",
                        "PlayerNameFirstA": "Player",
                        "PlayerNameLastA": "A",
                        "PlayerNameFirstB": "Player",
                        "PlayerNameLastB": "B",
                        "PlayerCountryA": "USA",
                        "PlayerCountryB": "CAN",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
                    },
                )
            ]
        )[0]
        session.flush()

        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="old",
            payload={
                "MatchState": "S",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "A",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "PlayerCountryA": "USA",
                "PlayerCountryB": "CAN",
                "RoundID": "5",
                "MatchTimeStamp": "2026-05-28T10:00:00+00:00",
            },
        )
        match_repo.create_snapshot(
            match_id=match.id,
            snapshot_type="upstream_sync",
            snapshot_hash="new",
            payload=match.metadata_json,
        )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        result = service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(select(PublishJob)).all()

        assert len(result.result_changes) == 1
        assert len(jobs) == 1
        assert jobs[0].job_type == "schedule_article"
        assert jobs[0].biz_key == f"schedule:{tournament.id}:2026-05-28"


def test_detect_and_queue_jobs_skips_today_schedule_when_partial_and_far_away() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        matches = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-arranged",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 13, 30, tzinfo=UTC),
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T13:30:00+00:00",
                    },
                ),
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-unarranged",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=None,
                    player1_name="Player C",
                    player2_name="Player D",
                    status="scheduled",
                    metadata={
                        "MatchState": "U",
                        "MatchTimeStamp": "2026-05-28T17:00:00+00:00",
                        "Unscheduled": True,
                        "isEstimatedStartTime": True,
                        "RoundID": "5",
                    },
                ),
            ]
        )
        session.flush()

        for match in matches:
            match_repo.create_snapshot(
                match_id=match.id,
                snapshot_type="upstream_sync",
                snapshot_hash=f"snapshot-{match.id}",
                payload=match.metadata_json,
            )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 6, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert jobs == []


def test_detect_and_queue_jobs_creates_today_schedule_when_partial_and_near_start() -> None:
    session_factory = _build_service()

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournament = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="800:2026:2026-05-28:2026-06-02",
                    name="Roland Garros",
                    tour="grand_slam",
                    start_date=date(2026, 5, 28),
                    end_date=date(2026, 6, 2),
                )
            ]
        )[0]
        session.flush()

        matches = match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-arranged",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=datetime(2026, 5, 28, 13, 30, tzinfo=UTC),
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                    metadata={
                        "MatchState": "S",
                        "RoundID": "5",
                        "MatchTimeStamp": "2026-05-28T13:30:00+00:00",
                    },
                ),
                NormalizedMatch(
                    source="wta",
                    source_match_id="today-unarranged",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Quarterfinal",
                    scheduled_at_utc=None,
                    player1_name="Player C",
                    player2_name="Player D",
                    status="scheduled",
                    metadata={
                        "MatchState": "U",
                        "MatchTimeStamp": "2026-05-28T17:00:00+00:00",
                        "Unscheduled": True,
                        "isEstimatedStartTime": True,
                        "RoundID": "5",
                    },
                ),
            ]
        )
        session.flush()

        for match in matches:
            match_repo.create_snapshot(
                match_id=match.id,
                snapshot_type="upstream_sync",
                snapshot_hash=f"snapshot-{match.id}",
                payload=match.metadata_json,
            )
        session.commit()

        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 8, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(jobs) == 1
        assert jobs[0].payload["release_version"] == 1


def test_detect_and_queue_jobs_preserves_utc_match_times_after_sqlite_round_trip() -> None:
    session_factory = _build_service()

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
                    source_match_id="LS71563958",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Round 3",
                    scheduled_at_utc=datetime(2026, 5, 29, 9, 0, tzinfo=UTC),
                    court_name="Court 7",
                    player1_name="Xiyu Wang",
                    player2_name="Yuliia Starodubtseva",
                    player1_country="CHN",
                    player2_country="UKR",
                    status="scheduled",
                    is_key_match=True,
                    metadata={
                        "MatchState": "U",
                        "MatchTimeStamp": "2026-05-29T09:00:00+00:00",
                        "NotBefore": "Starting at 11:00 AM",
                        "NotBeforeISOTime": "11:00+0200",
                        "PlayerNameFirstA": "Xiyu",
                        "PlayerNameLastA": "Wang",
                        "PlayerNameFirstB": "Yuliia",
                        "PlayerNameLastB": "Starodubtseva",
                        "PlayerCountryA": "CHN",
                        "PlayerCountryB": "UKR",
                        "RoundID": "3",
                        "Venue": {"name": "Court 7"},
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

    with session_factory() as session:
        service = DiffService(settings=AppSettings(), session=session)
        service.detect_and_queue_jobs(now_utc=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

        jobs = session.scalars(
            select(PublishJob)
            .where(PublishJob.job_type == "schedule_article")
            .order_by(PublishJob.id.asc())
        ).all()

        assert len(jobs) == 1
        assert jobs[0].payload["matches"][0]["scheduled_at_utc"] == "2026-05-29T09:00:00+00:00"
        assert jobs[0].payload["matches"][0]["scheduled_at_local"] == "2026-05-29T17:00:00+08:00"
