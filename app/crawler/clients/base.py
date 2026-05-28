from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class TennisDataClient(ABC):
    """Abstract client for upstream tennis data providers."""

    @abstractmethod
    async def fetch_tournaments(
        self,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_matches(self, tournament_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_order_of_play(self, tournament_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_match_result(self, match_id: str, tournament_id: str) -> dict[str, Any]:
        raise NotImplementedError
