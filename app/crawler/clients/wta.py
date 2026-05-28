from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.crawler.clients.base import TennisDataClient


class WtaClient(TennisDataClient):
    """WTA client backed by the site's internal tennis API."""

    account_key = "9e821d4e7fcc40d7bcb0a20ac9344fe8"

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_base_url = "https://api.wtatennis.com/tennis"
        self.timeout_seconds = timeout_seconds

    async def fetch_tournaments(self) -> list[dict[str, Any]]:
        today = date.today()
        lookback = today - timedelta(days=180)
        horizon = today + timedelta(days=365)
        payload = await self._get_json(
            "/tournaments/",
            params={
                "page": 0,
                "pageSize": 200,
                "excludeLevels": "ITF",
                "from": lookback.isoformat(),
                "to": horizon.isoformat(),
            },
        )
        return payload.get("content", [])

    async def fetch_matches(self, tournament_id: str) -> list[dict[str, Any]]:
        event_id, event_year, start_date, end_date = tournament_id.split(":", maxsplit=3)
        payload = await self._get_json(
            f"/tournaments/{int(event_id)}/{event_year}/matches",
            params={"from": start_date, "to": end_date},
        )
        return payload.get("matches", [])

    async def fetch_order_of_play(self, tournament_id: str) -> list[dict[str, Any]]:
        event_id, event_year, _, _ = tournament_id.split(":", maxsplit=3)
        payload = await self._get_json(f"/tournaments/{int(event_id)}/{event_year}/oop")
        order_of_play = payload.get("orderOfPlay")
        if not order_of_play:
            return []

        if isinstance(order_of_play, str):
            parsed = json.loads(order_of_play)
        elif isinstance(order_of_play, dict):
            parsed = order_of_play
        elif isinstance(order_of_play, list):
            parsed = {"OOP": {"Schedule": {"Day": order_of_play}}}
        else:
            return []

        schedule = (parsed.get("OOP") or {}).get("Schedule") or {}
        days = _ensure_mapping_list(schedule.get("Day"))

        matches: list[dict[str, Any]] = []
        for day in days:
            day_context = {
                "display_date": day.get("DisplayDate"),
                "iso_date": day.get("ISODate"),
                "date_seq": day.get("Seq"),
            }
            for court in _ensure_mapping_list(day.get("Court")):
                court_context = {
                    "court_id": court.get("CourtId"),
                    "court_name": court.get("CourtName"),
                    "display_time": court.get("DisplayTime"),
                    "utc_offset": court.get("UTCOffset"),
                }
                for match in _ensure_mapping_list((court.get("Matches") or {}).get("Match")):
                    matches.append(
                        {
                            **match,
                            "_oop_day": day_context,
                            "_oop_court": court_context,
                        }
                    )

        return matches

    async def fetch_match_result(self, match_id: str, tournament_id: str) -> dict[str, Any]:
        event_id, event_year, _, _ = tournament_id.split(":", maxsplit=3)
        payload = await self._get_json(
            f"/tournaments/{int(event_id)}/{event_year}/matches/{match_id}/score"
        )
        if isinstance(payload, list):
            return payload[0] if payload else {}
        if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
            matches = payload.get("matches") or []
            return matches[0] if matches else {}
        return payload if isinstance(payload, dict) else {}

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "accept": "application/json,text/plain,*/*",
            "account": self.account_key,
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
        }

        def run_request() -> dict[str, Any]:
            with httpx.Client(
                base_url=self.api_base_url,
                timeout=self.timeout_seconds,
                headers=headers,
            ) as client:
                response = client.get(path, params=params)
                response.raise_for_status()
                return response.json()

        return await asyncio.to_thread(run_request)


def parse_wta_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ensure_mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in _ensure_list(value) if isinstance(item, dict)]
