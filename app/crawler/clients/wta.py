from __future__ import annotations

import asyncio
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

    async def fetch_match_result(self, match_id: str) -> dict[str, Any]:
        return {}

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
