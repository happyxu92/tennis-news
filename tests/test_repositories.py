from datetime import UTC, date, datetime

from sqlalchemy import create_engine

from app.crawler.schemas import NormalizedMatch, NormalizedTournament
from app.models import Base
from app.storage.database import create_session_factory
from app.storage.repositories import MatchRepository, TournamentRepository


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
