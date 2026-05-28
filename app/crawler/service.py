from __future__ import annotations

import json
from hashlib import sha256

import httpx
from sqlalchemy.orm import Session

from app.crawler.adapters import WtaAdapter
from app.crawler.clients import WtaClient
from app.crawler.schemas import CrawlBundle, NormalizedMatch
from app.logging import get_logger
from app.settings import AppSettings
from app.storage.repositories import MatchRepository, TournamentRepository

logger = get_logger(__name__)


class CrawlerService:
    """Coordinates fetching, normalization, and persistence for tennis data."""

    def __init__(self, settings: AppSettings, session: Session) -> None:
        self.settings = settings
        self.session = session
        self.client = WtaClient(
            base_url=settings.source_base_url,
            timeout_seconds=settings.source_timeout_seconds,
        )
        self.adapter = WtaAdapter()
        self.tournaments = TournamentRepository(session)
        self.matches = MatchRepository(session)

    async def sync_all(self) -> CrawlBundle:
        tournament_payloads = await self.client.fetch_tournaments()
        normalized_tournaments = [
            self.adapter.normalize_tournament(item)
            for item in tournament_payloads
            if item.get("tournamentGroup") and item.get("year")
        ]

        stored_tournaments = self.tournaments.upsert_many(normalized_tournaments)
        tournament_id_map = {
            item.source_tournament_id: entity.id
            for item, entity in zip(normalized_tournaments, stored_tournaments, strict=False)
        }

        normalized_matches: list[NormalizedMatch] = []
        for tournament in normalized_tournaments:
            try:
                match_payloads = await self.client.fetch_matches(tournament.source_tournament_id)
            except httpx.HTTPError:
                logger.exception(
                    "failed to fetch matches for tournament %s",
                    tournament.source_tournament_id,
                )
                continue

            for payload in match_payloads:
                match = self.adapter.normalize_match(payload)
                match.tournament_id = tournament_id_map.get(match.source_tournament_id)
                normalized_matches.append(match)

        stored_matches = self.matches.upsert_many(normalized_matches)
        for entity, normalized in zip(stored_matches, normalized_matches, strict=False):
            snapshot_hash = self._build_snapshot_hash(normalized.metadata)
            self.matches.create_snapshot(
                match_id=entity.id,
                snapshot_type="upstream_sync",
                snapshot_hash=snapshot_hash,
                payload=normalized.metadata,
            )

        self.session.commit()
        logger.info(
            "sync completed: %s tournaments, %s matches",
            len(normalized_tournaments),
            len(normalized_matches),
        )
        return CrawlBundle(tournaments=normalized_tournaments, matches=normalized_matches)

    def _build_snapshot_hash(self, payload: dict) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()
