from app.crawler.adapters import WtaAdapter


def test_normalize_tournament_from_wta_api() -> None:
    adapter = WtaAdapter()

    normalized = adapter.normalize_tournament(
        {
            "tournamentGroup": {"id": 903, "name": "ROLAND GARROS", "level": "Grand Slam"},
            "year": 2026,
            "title": "Roland Garros - Paris, France",
            "startDate": "2026-01-18",
            "endDate": "2026-02-01",
            "surface": "Clay",
            "city": "PARIS",
            "country": "FRA",
            "level": "Grand Slam",
        }
    )

    assert normalized.source == "wta"
    assert normalized.source_tournament_id == "903:2026:2026-01-18:2026-02-01"
    assert normalized.name == "Roland Garros"
    assert normalized.tour == "grand_slam"
    assert normalized.surface == "Clay"
    assert normalized.start_date is not None


def test_normalize_match_from_wta_api() -> None:
    adapter = WtaAdapter()

    normalized = adapter.normalize_match(
        {
            "MatchID": "LS038",
            "EventID": "0800",
            "EventYear": 2026,
            "MatchState": "F",
            "MatchTimeStamp": "2026-01-04T00:43:29.347+00:00",
            "RoundID": "1",
            "PlayerNameFirstA": "Emiliana",
            "PlayerNameLastA": "Arango",
            "PlayerCountryA": "COL",
            "PlayerNameFirstB": "McCartney",
            "PlayerNameLastB": "Kessler",
            "PlayerCountryB": "USA",
            "SeedB": "11",
            "ScoreString": "6-1,6-3",
            "Winner": "3",
            "Tournament": {
                "tournamentGroup": {"id": 800, "name": "BRISBANE", "level": "WTA 500"},
                "year": 2026,
                "startDate": "2026-01-04",
                "endDate": "2026-01-11",
            },
            "Venue": {"name": "Center Court"},
        }
    )

    assert normalized.source_match_id == "LS038"
    assert normalized.source_tournament_id == "800:2026:2026-01-04:2026-01-11"
    assert normalized.player1_name == "Emiliana Arango"
    assert normalized.player2_name == "McCartney Kessler"
    assert normalized.winner_name == "McCartney Kessler"
    assert normalized.status == "finished"
    assert normalized.score_text == "6-1,6-3"
    assert normalized.is_key_match is True


def test_merge_match_payload_prefers_oop_court_and_deep_detail_values() -> None:
    adapter = WtaAdapter()

    merged = adapter.merge_match_payload(
        {
            "MatchID": "LS038",
            "MatchState": "S",
            "Venue": {},
            "Tournament": {
                "tournamentGroup": {"id": 800, "name": "BRISBANE", "level": "WTA 500"},
                "year": 2026,
                "startDate": "2026-01-04",
                "endDate": "2026-01-11",
            },
        },
        {
            "Status": "OOP",
            "NotBeforeText": "NB 11:00",
            "_oop_day": {"iso_date": "2026-01-04"},
            "_oop_court": {"court_name": "Grandstand", "court_id": "GS"},
        },
        {
            "MatchState": "F",
            "ScoreString": "7-5,6-4",
            "Venue": {"name": "Center Court"},
        },
    )

    normalized = adapter.normalize_match(merged)

    assert normalized.status == "finished"
    assert normalized.score_text == "7-5,6-4"
    assert normalized.court_name == "Center Court"
    assert normalized.metadata["oop"]["court"]["court_name"] == "Grandstand"
    assert normalized.metadata["NotBeforeText"] == "NB 11:00"


def test_normalize_match_clears_placeholder_time_for_unscheduled_estimate() -> None:
    adapter = WtaAdapter()

    normalized = adapter.normalize_match(
        {
            "MatchID": "LS71563960",
            "EventID": "0903",
            "EventYear": 2026,
            "MatchState": "U",
            "MatchTimeStamp": "2026-05-29T23:59+00:00",
            "Unscheduled": True,
            "isEstimatedStartTime": True,
            "NotBefore": "Starting at 9:00 AM",
            "NotBeforeISOTime": "09:00Z",
            "RoundID": "3",
            "PlayerNameFirstA": "Solana",
            "PlayerNameLastA": "Sierra",
            "PlayerNameFirstB": "Sorana",
            "PlayerNameLastB": "Cirstea",
            "Tournament": {
                "tournamentGroup": {"id": 903, "name": "ROLAND GARROS", "level": "Grand Slam"},
                "year": 2026,
                "startDate": "2026-05-24",
                "endDate": "2026-06-07",
            },
        }
    )

    assert normalized.scheduled_at_utc is None
    assert normalized.status == "scheduled"
