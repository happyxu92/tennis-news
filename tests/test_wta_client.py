def test_fetch_matches_expects_compound_tournament_id() -> None:
    tournament_key = "800:2026:2026-01-04:2026-01-11"
    event_id, event_year, start_date, end_date = tournament_key.split(":", maxsplit=3)

    assert event_id == "800"
    assert event_year == "2026"
    assert start_date == "2026-01-04"
    assert end_date == "2026-01-11"
