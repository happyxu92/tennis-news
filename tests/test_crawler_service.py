from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine

from app.crawler.service import CrawlerService
from app.models import Base, Match
from app.settings import AppSettings
from app.storage.database import create_session_factory


class StubWtaClient:
    def __init__(self) -> None:
        self.detail_requests: list[tuple[str, str]] = []
        self.tournament_windows: list[tuple[date, date]] = []

    async def fetch_tournaments(self, from_date: date, to_date: date) -> list[dict]:
        self.tournament_windows.append((from_date, to_date))
        return [
            {
                "tournamentGroup": {"id": 800, "name": "BRISBANE", "level": "WTA 500"},
                "year": 2026,
                "title": "Brisbane - Brisbane, Australia",
                "startDate": "2026-01-04",
                "endDate": "2026-01-11",
                "surface": "Hard",
                "city": "Brisbane",
                "country": "AUS",
                "level": "WTA 500",
            }
        ]

    async def fetch_matches(self, tournament_id: str) -> list[dict]:
        assert tournament_id == "800:2026:2026-01-04:2026-01-11"
        return [
            {
                "MatchID": "LS038",
                "EventID": "0800",
                "EventYear": 2026,
                "MatchState": "S",
                "RoundID": "1",
                "PlayerNameFirstA": "Emiliana",
                "PlayerNameLastA": "Arango",
                "PlayerCountryA": "COL",
                "PlayerNameFirstB": "McCartney",
                "PlayerNameLastB": "Kessler",
                "PlayerCountryB": "USA",
                "Tournament": {
                    "tournamentGroup": {"id": 800, "name": "BRISBANE", "level": "WTA 500"},
                    "year": 2026,
                    "startDate": "2026-01-04",
                    "endDate": "2026-01-11",
                },
                "Venue": {},
            }
        ]

    async def fetch_order_of_play(self, tournament_id: str) -> list[dict]:
        assert tournament_id == "800:2026:2026-01-04:2026-01-11"
        return [
            {
                "MatchId": "LS038",
                "NotBeforeText": "NB 11:00",
                "_oop_day": {"iso_date": "2026-01-04", "date_seq": "1"},
                "_oop_court": {"court_name": "Grandstand", "court_id": "GS"},
            }
        ]

    async def fetch_match_result(self, match_id: str, tournament_id: str) -> dict:
        self.detail_requests.append((match_id, tournament_id))
        assert match_id == "LS038"
        assert tournament_id == "800:2026:2026-01-04:2026-01-11"
        return {
            "MatchID": "LS038",
            "MatchState": "F",
            "ScoreString": "6-1,6-3",
            "Winner": "3",
            "Venue": {"name": "Center Court"},
        }


@pytest.mark.asyncio
async def test_sync_all_merges_oop_and_match_detail_payloads() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        service = CrawlerService(settings=AppSettings(), session=session)
        service.client = StubWtaClient()

        bundle = await service.sync_all(now_utc=datetime(2026, 1, 5, 12, 0, tzinfo=UTC))

        assert service.client.tournament_windows == [(date(2025, 12, 15), date(2026, 1, 8))]
        assert service.client.detail_requests == [("LS038", "800:2026:2026-01-04:2026-01-11")]
        assert len(bundle.matches) == 1
        assert bundle.matches[0].status == "finished"
        assert bundle.matches[0].score_text == "6-1,6-3"
        assert bundle.matches[0].court_name == "Center Court"

        stored = session.query(Match).one()
        assert stored.court_name == "Center Court"
        assert stored.score_text == "6-1,6-3"
        assert stored.metadata_json["oop"]["court"]["court_name"] == "Grandstand"
        assert stored.metadata_json["NotBeforeText"] == "NB 11:00"


class FutureScheduledStubWtaClient(StubWtaClient):
    async def fetch_matches(self, tournament_id: str) -> list[dict]:
        assert tournament_id == "800:2026:2026-01-04:2026-01-11"
        return [
            {
                "MatchID": "LS039",
                "EventID": "0800",
                "EventYear": 2026,
                "MatchState": "S",
                "MatchTimeStamp": "2026-01-06T11:00:00+00:00",
                "RoundID": "1",
                "PlayerNameFirstA": "Player",
                "PlayerNameLastA": "A",
                "PlayerCountryA": "USA",
                "PlayerNameFirstB": "Player",
                "PlayerNameLastB": "B",
                "PlayerCountryB": "USA",
                "Tournament": {
                    "tournamentGroup": {"id": 800, "name": "BRISBANE", "level": "WTA 500"},
                    "year": 2026,
                    "startDate": "2026-01-04",
                    "endDate": "2026-01-11",
                },
                "Venue": {},
            }
        ]

    async def fetch_order_of_play(self, tournament_id: str) -> list[dict]:
        assert tournament_id == "800:2026:2026-01-04:2026-01-11"
        return [
            {
                "MatchId": "LS039",
                "NotBeforeText": "NB 11:00",
                "_oop_day": {"iso_date": "2026-01-06", "date_seq": "3"},
                "_oop_court": {"court_name": "Court 7", "court_id": "C7"},
            }
        ]

    async def fetch_match_result(self, match_id: str, tournament_id: str) -> dict:
        self.detail_requests.append((match_id, tournament_id))
        raise AssertionError("future scheduled matches should not fetch detail")


@pytest.mark.asyncio
async def test_sync_all_skips_match_detail_for_future_scheduled_match() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        service = CrawlerService(settings=AppSettings(), session=session)
        service.client = FutureScheduledStubWtaClient()

        bundle = await service.sync_all(now_utc=datetime(2026, 1, 5, 12, 0, tzinfo=UTC))

        assert service.client.detail_requests == []
        assert len(bundle.matches) == 1
        assert bundle.matches[0].status == "scheduled"
        assert bundle.matches[0].score_text is None
        assert bundle.matches[0].court_name == "Court 7"

        stored = session.query(Match).one()
        assert stored.court_name == "Court 7"
        assert stored.status == "scheduled"
        assert stored.score_text is None
        assert stored.metadata_json["oop"]["court"]["court_name"] == "Court 7"
