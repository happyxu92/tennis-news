from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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

    async def sync_all(self, now_utc: datetime | None = None) -> CrawlBundle:
        tournament_payloads = await self.client.fetch_tournaments()
        utc_today = (now_utc or datetime.now(UTC)).date()
        sync_window_end = utc_today + timedelta(days=3)
        normalized_tournaments = [
            self.adapter.normalize_tournament(item)
            for item in tournament_payloads
            if item.get("tournamentGroup") and item.get("year")
        ]
        normalized_tournaments = [
            item
            for item in normalized_tournaments
            if item.end_date is not None
            and item.start_date is not None
            and item.end_date >= utc_today
            and item.start_date <= sync_window_end
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

            try:
                oop_payloads = await self.client.fetch_order_of_play(
                    tournament.source_tournament_id
                )
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                logger.exception(
                    "failed to fetch order of play for tournament %s",
                    tournament.source_tournament_id,
                )
                oop_payloads = []

            oop_match_map = {
                str(item.get("MatchId") or ""): item
                for item in oop_payloads
                if item.get("MatchId")
            }

            for payload in match_payloads:
                match_id = str(payload.get("MatchID") or "")
                detail_payload: dict = {}
                if match_id:
                    try:
                        detail_payload = await self.client.fetch_match_result(
                            match_id,
                            tournament.source_tournament_id,
                        )
                    except httpx.HTTPError:
                        logger.exception(
                            "failed to fetch match detail for %s in tournament %s",
                            match_id,
                            tournament.source_tournament_id,
                        )

                merged_payload = self.adapter.merge_match_payload(
                    payload,
                    oop_match_map.get(match_id),
                    detail_payload,
                )
                match = self.adapter.normalize_match(merged_payload)
                match.source_tournament_id = tournament.source_tournament_id
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
