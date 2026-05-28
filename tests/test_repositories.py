from datetime import UTC, date, datetime

from sqlalchemy import create_engine

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Base
from app.storage.database import create_session_factory
from app.storage.repositories import (
    MatchRepository,
    PublishedArticleRepository,
    PublishJobRepository,
    TournamentRepository,
)


def test_upsert_tournament_and_match() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        match_repo = MatchRepository(session)

        tournaments = tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="sportradar",
                    source_tournament_id="sr:competition:1",
                    name="Australian Open",
                    tour="grand_slam",
                )
            ]
        )
        match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="sportradar",
                    source_match_id="sr:sport_event:1",
                    source_tournament_id="sr:competition:1",
                    tournament_id=tournaments[0].id,
                    round_name="Final",
                    scheduled_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
                    player1_name="Player A",
                    player2_name="Player B",
                    status="scheduled",
                )
            ]
        )
        session.commit()

        stored = tournament_repo.get_by_source_id("sportradar", "sr:competition:1")
        assert stored is not None
        assert stored.name == "Australian Open"


def test_match_repository_restores_utc_tzinfo_after_sqlite_round_trip() -> None:
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
                )
            ]
        )[0]
        match_repo.upsert_many(
            [
                NormalizedMatch(
                    source="wta",
                    source_match_id="LS71563958",
                    source_tournament_id=tournament.source_tournament_id,
                    tournament_id=tournament.id,
                    round_name="Round 3",
                    scheduled_at_utc=datetime(2026, 5, 29, 9, 0, tzinfo=UTC),
                    player1_name="Xiyu Wang",
                    player2_name="Yuliia Starodubtseva",
                    status="scheduled",
                )
            ]
        )
        tournament_id = tournament.id
        session.commit()

    with session_factory() as session:
        match_repo = MatchRepository(session)
        stored = match_repo.list_by_tournament_ids([tournament_id])[0]

        assert stored.scheduled_at_utc is not None
        assert stored.scheduled_at_utc.tzinfo == UTC
        assert stored.scheduled_at_utc.isoformat() == "2026-05-29T09:00:00+00:00"


def test_list_tournaments_in_sync_window() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        tournament_repo = TournamentRepository(session)
        tournament_repo.upsert_many(
            [
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="active",
                    name="Active Event",
                    tour="wta",
                    start_date=date(2026, 5, 26),
                    end_date=date(2026, 5, 29),
                ),
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="future-in-window",
                    name="Soon Event",
                    tour="wta",
                    start_date=date(2026, 5, 31),
                    end_date=date(2026, 6, 7),
                ),
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="future-outside-window",
                    name="Later Event",
                    tour="wta",
                    start_date=date(2026, 6, 2),
                    end_date=date(2026, 6, 9),
                ),
                NormalizedTournament(
                    source="wta",
                    source_tournament_id="ended",
                    name="Ended Event",
                    tour="wta",
                    start_date=date(2026, 5, 20),
                    end_date=date(2026, 5, 27),
                ),
            ]
        )
        session.commit()

        tournaments = tournament_repo.list_in_sync_window(date(2026, 5, 28), future_days=3)

        assert [item.source_tournament_id for item in tournaments] == ["active", "future-in-window"]


def test_publish_job_repository_lists_and_updates_jobs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        publish_repo = PublishJobRepository(session)
        first = publish_repo.create(
            job_type="schedule_article",
            biz_key="schedule:1:2026-05-29",
            content_hash="hash-1",
            payload={"matches": []},
        )
        publish_repo.create(
            job_type="result_article",
            biz_key="result:1",
            content_hash="hash-2",
            payload={"match_id": 1},
            status="publishing",
        )
        session.commit()

        pending = publish_repo.list_by_statuses(["pending"])
        assert [item.id for item in pending] == [first.id]

        publish_repo.update(
            first,
            status="retryable",
            payload_updates={"publish_id": "pub-1"},
            error_message="temporary failure",
            increment_retry=True,
        )
        session.commit()

        stored = publish_repo.get_by_id(first.id)
        assert stored is not None
        assert stored.status == "retryable"
        assert stored.payload["publish_id"] == "pub-1"
        assert stored.error_message == "temporary failure"
        assert stored.retry_count == 1


def test_published_article_repository_upserts_by_job_id() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        publish_repo = PublishJobRepository(session)
        article_repo = PublishedArticleRepository(session)
        job = publish_repo.create(
            job_type="schedule_article",
            biz_key="schedule:1:2026-05-29",
            content_hash="hash-1",
            payload={"matches": []},
        )
        session.flush()

        article_repo.upsert(
            job_id=job.id,
            title="first title",
            content_hash="hash-1",
            wechat_media_id="draft-1",
            publish_id=None,
        )
        article_repo.upsert(
            job_id=job.id,
            title="updated title",
            content_hash="hash-1",
            wechat_media_id="draft-2",
            publish_id="publish-1",
            article_url="https://example.com/article",
            published_at=datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        )
        session.commit()

        stored = article_repo.get_by_job_id(job.id)
        assert stored is not None
        assert stored.title == "updated title"
        assert stored.wechat_media_id == "draft-2"
        assert stored.publish_id == "publish-1"
        assert stored.article_url == "https://example.com/article"
