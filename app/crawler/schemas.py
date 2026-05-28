from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class NormalizedTournament(BaseModel):
    source: str
    source_tournament_id: str
    name: str
    tour: str
    level: str | None = None
    surface: str | None = None
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedMatch(BaseModel):
    source: str
    source_match_id: str
    source_tournament_id: str
    tournament_id: int | None = None
    round_name: str | None = None
    scheduled_at_utc: datetime | None = None
    court_name: str | None = None
    player1_name: str | None = None
    player2_name: str | None = None
    player1_country: str | None = None
    player2_country: str | None = None
    player1_seed: int | None = None
    player2_seed: int | None = None
    status: str = "scheduled"
    score_text: str | None = None
    winner_name: str | None = None
    is_key_match: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrawlBundle(BaseModel):
    tournaments: list[NormalizedTournament] = Field(default_factory=list)
    matches: list[NormalizedMatch] = Field(default_factory=list)
