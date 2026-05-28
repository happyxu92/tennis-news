import json

import pytest

from app.crawler.clients.wta import WtaClient


def test_fetch_matches_expects_compound_tournament_id() -> None:
    tournament_key = "800:2026:2026-01-04:2026-01-11"
    event_id, event_year, start_date, end_date = tournament_key.split(":", maxsplit=3)

    assert event_id == "800"
    assert event_year == "2026"
    assert start_date == "2026-01-04"
    assert end_date == "2026-01-11"


@pytest.mark.asyncio
async def test_fetch_order_of_play_flattens_day_court_match_structure(monkeypatch) -> None:
    client = WtaClient(base_url="https://www.wtatennis.com")

    async def fake_get_json(path: str, params=None):
        assert path == "/tournaments/800/2026/oop"
        assert params is None
        return {
            "orderOfPlay": json.dumps(
                {
                    "OOP": {
                        "Schedule": {
                            "Day": {
                                "DisplayDate": "Sunday",
                                "ISODate": "2026-01-04",
                                "Seq": "1",
                                "Court": {
                                    "CourtId": "CC",
                                    "CourtName": "Center Court",
                                    "Matches": {
                                        "Match": {
                                            "MatchId": "LS038",
                                            "Status": "S",
                                        }
                                    },
                                },
                            }
                        }
                    }
                }
            )
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    matches = await client.fetch_order_of_play("800:2026:2026-01-04:2026-01-11")

    assert matches == [
        {
            "MatchId": "LS038",
            "Status": "S",
            "_oop_day": {
                "display_date": "Sunday",
                "iso_date": "2026-01-04",
                "date_seq": "1",
            },
            "_oop_court": {
                "court_id": "CC",
                "court_name": "Center Court",
                "display_time": None,
                "utc_offset": None,
            },
        }
    ]


@pytest.mark.asyncio
async def test_fetch_match_result_uses_score_endpoint(monkeypatch) -> None:
    client = WtaClient(base_url="https://www.wtatennis.com")

    async def fake_get_json(path: str, params=None):
        assert path == "/tournaments/800/2026/matches/LS019/score"
        assert params is None
        return [{"MatchID": "LS019", "ScoreString": "6-1,6-3"}]

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    payload = await client.fetch_match_result("LS019", "800:2026:2026-01-04:2026-01-11")

    assert payload == {"MatchID": "LS019", "ScoreString": "6-1,6-3"}


@pytest.mark.asyncio
async def test_fetch_order_of_play_accepts_list_payload(monkeypatch) -> None:
    client = WtaClient(base_url="https://www.wtatennis.com")

    async def fake_get_json(path: str, params=None):
        assert path == "/tournaments/800/2026/oop"
        assert params is None
        return {
            "orderOfPlay": [
                {
                    "DisplayDate": "Sunday",
                    "ISODate": "2026-01-04",
                    "Seq": "1",
                    "Court": [
                        {
                            "CourtId": "GS",
                            "CourtName": "Grandstand",
                            "Matches": {"Match": [{"MatchId": "LS099", "Status": "S"}]},
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    matches = await client.fetch_order_of_play("800:2026:2026-01-04:2026-01-11")

    assert matches == [
        {
            "MatchId": "LS099",
            "Status": "S",
            "_oop_day": {
                "display_date": "Sunday",
                "iso_date": "2026-01-04",
                "date_seq": "1",
            },
            "_oop_court": {
                "court_id": "GS",
                "court_name": "Grandstand",
                "display_time": None,
                "utc_offset": None,
            },
        }
    ]


@pytest.mark.asyncio
async def test_fetch_order_of_play_ignores_non_mapping_nodes(monkeypatch) -> None:
    client = WtaClient(base_url="https://www.wtatennis.com")

    async def fake_get_json(path: str, params=None):
        assert path == "/tournaments/800/2026/oop"
        assert params is None
        return {
            "orderOfPlay": {
                "OOP": {
                    "Schedule": {
                        "Day": [
                            "header",
                            {
                                "DisplayDate": "Sunday",
                                "ISODate": "2026-01-04",
                                "Seq": "1",
                                "Court": [
                                    "banner",
                                    {
                                        "CourtId": "GS",
                                        "CourtName": "Grandstand",
                                        "Matches": {
                                            "Match": [
                                                "promo",
                                                {"MatchId": "LS100", "Status": "S"},
                                            ]
                                        },
                                    },
                                ],
                            },
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    matches = await client.fetch_order_of_play("800:2026:2026-01-04:2026-01-11")

    assert [match["MatchId"] for match in matches] == ["LS100"]
