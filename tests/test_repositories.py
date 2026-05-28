from datetime import UTC, datetime

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
