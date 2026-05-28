from __future__ import annotations

from datetime import date

from app.crawler.clients.wta import parse_wta_datetime
from app.crawler.schemas import NormalizedMatch, NormalizedTournament

GRAND_SLAM_SLUGS = {
    "australian-open",
    "roland-garros",
    "wimbledon",
    "us-open",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


class WtaAdapter:
    """Transforms WTA API payloads into internal models."""

    source = "wta"

    def normalize_tournament(self, payload: dict) -> NormalizedTournament:
        tournament_group = payload.get("tournamentGroup") or {}
        source_id = self._build_tournament_source_id(payload)
        name = self._normalize_tournament_name(payload)
        city = payload.get("city")
        country = payload.get("country")
        location = ", ".join(part for part in (city, country) if part) or None
        level = payload.get("level") or tournament_group.get("level")

        return NormalizedTournament(
            source=self.source,
            source_tournament_id=source_id,
            name=name,
            tour=self._detect_tour(level, name),
            level=level,
            surface=payload.get("surface"),
            location=location,
            start_date=_parse_date(payload.get("startDate")),
            end_date=_parse_date(payload.get("endDate")),
            metadata=payload,
        )

    def normalize_match(self, payload: dict) -> NormalizedMatch:
        tournament = payload.get("Tournament") or {}
        source_tournament_id = self._build_tournament_source_id(tournament)

        player1_name = self._build_player_name(payload, "A")
        player2_name = self._build_player_name(payload, "B")
        winner_name = self._resolve_winner_name(payload, player1_name, player2_name)
        score_text = payload.get("ScoreString") or None

        return NormalizedMatch(
            source=self.source,
            source_match_id=str(payload.get("MatchID") or ""),
            source_tournament_id=source_tournament_id,
            round_name=self._map_round_name(payload.get("RoundID")),
            scheduled_at_utc=parse_wta_datetime(payload.get("MatchTimeStamp")),
            court_name=(payload.get("Venue") or {}).get("name"),
            player1_name=player1_name,
            player2_name=player2_name,
            player1_country=payload.get("PlayerCountryA") or None,
            player2_country=payload.get("PlayerCountryB") or None,
            player1_seed=self._to_int(payload.get("SeedA")),
            player2_seed=self._to_int(payload.get("SeedB")),
            status=self._map_status(payload.get("MatchState")),
            score_text=score_text,
            winner_name=winner_name,
            is_key_match=self._is_key_match(payload),
            metadata=payload,
        )

    def _build_tournament_source_id(self, payload: dict) -> str:
        tournament_group = payload.get("tournamentGroup") or {}
        group_id = str(tournament_group.get("id") or payload.get("EventID") or "")
        year = str(payload.get("year") or payload.get("EventYear") or "")
        start_date = str(payload.get("startDate") or "")
        end_date = str(payload.get("endDate") or "")
        return ":".join([group_id, year, start_date, end_date])

    def _normalize_tournament_name(self, payload: dict) -> str:
        title = payload.get("title") or ""
        if " - " in title:
            return title.split(" - ", maxsplit=1)[0]
        return title or (payload.get("tournamentGroup") or {}).get("name") or "Unknown tournament"

    def _detect_tour(self, level: str | None, name: str) -> str:
        combined = f"{level or ''} {name}".lower()
        has_grand_slam_slug = any(slug.replace("-", " ") in combined for slug in GRAND_SLAM_SLUGS)
        if has_grand_slam_slug or "grand slam" in combined:
            return "grand_slam"
        if "wta" in combined or level:
            return "wta"
        return "unknown"

    def _build_player_name(self, payload: dict, suffix: str) -> str | None:
        first = payload.get(f"PlayerNameFirst{suffix}") or ""
        last = payload.get(f"PlayerNameLast{suffix}") or ""
        name = f"{first} {last}".strip()
        return name or None

    def _resolve_winner_name(
        self,
        payload: dict,
        player1_name: str | None,
        player2_name: str | None,
    ) -> str | None:
        winner = str(payload.get("Winner") or "")
        if winner == "2":
            return player1_name
        if winner == "3":
            return player2_name
        return None

    def _map_status(self, value: str | None) -> str:
        mapping = {
            "F": "finished",
            "C": "cancelled",
            "S": "scheduled",
            "D": "delayed",
            "I": "in_progress",
            "L": "live",
        }
        return mapping.get((value or "").upper(), (value or "scheduled").lower())

    def _map_round_name(self, value: str | None) -> str | None:
        mapping = {
            "1": "Round 1",
            "2": "Round 2",
            "3": "Round 3",
            "4": "Round 4",
            "5": "Quarterfinal",
            "6": "Semifinal",
            "7": "Final",
        }
        if value is None:
            return None
        return mapping.get(str(value), f"Round {value}")

    def _is_key_match(self, payload: dict) -> bool:
        return any(
            [
                self._to_int(payload.get("SeedA")) is not None,
                self._to_int(payload.get("SeedB")) is not None,
                payload.get("PlayerCountryA") == "CHN",
                payload.get("PlayerCountryB") == "CHN",
            ]
        )

    def _to_int(self, value: str | int | None) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
