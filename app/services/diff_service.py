from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.crawler.clients.wta import parse_wta_datetime
from app.logging import get_logger
from app.models import Match, Tournament
from app.settings import AppSettings
from app.storage.repositories import MatchRepository, PublishJobRepository, TournamentRepository

logger = get_logger(__name__)

SCHEDULE_JOB_TYPE = "schedule_article"
RESULT_JOB_TYPE = "result_article"
SYNC_SNAPSHOT_TYPE = "upstream_sync"
FINISHED_STATUSES = {"finished"}


@dataclass(slots=True)
class ScheduleChange:
    tournament_id: int
    tournament_name: str
    target_date: date
    match_id: int
    source_match_id: str
    change_types: list[str]


@dataclass(slots=True)
class ResultChange:
    tournament_id: int | None
    tournament_name: str | None
    target_date: date
    match_id: int
    source_match_id: str
    change_types: list[str]


@dataclass(slots=True)
class DiffRunResult:
    utc_today: date
    schedule_target_date: date
    schedule_target_dates: list[date] = field(default_factory=list)
    synced_tournament_ids: list[int] = field(default_factory=list)
    schedule_changes: list[ScheduleChange] = field(default_factory=list)
    result_changes: list[ResultChange] = field(default_factory=list)
    created_job_ids: list[int] = field(default_factory=list)


class DiffService:
    """Detects schedule/result changes and creates publish jobs."""

    def __init__(self, settings: AppSettings, session: Session) -> None:
        self.settings = settings
        self.session = session
        self.tournaments = TournamentRepository(session)
        self.matches = MatchRepository(session)
        self.publish_jobs = PublishJobRepository(session)
        self.article_timezone = ZoneInfo(settings.article_timezone)

    def detect_and_queue_jobs(self, now_utc: datetime | None = None) -> DiffRunResult:
        current_time = now_utc or datetime.now(UTC)
        utc_today = current_time.date()
        schedule_target_date = utc_today + timedelta(days=1)
        schedule_target_dates = [utc_today, schedule_target_date]

        tournaments = self.tournaments.list_in_sync_window(utc_today, future_days=3)
        tournament_ids = [item.id for item in tournaments]
        matches = self.matches.list_by_tournament_ids(tournament_ids)
        snapshots_by_match_id = self.matches.list_recent_snapshots(
            [item.id for item in matches],
            snapshot_type=SYNC_SNAPSHOT_TYPE,
            limit_per_match=2,
        )
        tournament_map = {item.id: item for item in tournaments}

        result = DiffRunResult(
            utc_today=utc_today,
            schedule_target_date=schedule_target_date,
            schedule_target_dates=schedule_target_dates,
            synced_tournament_ids=tournament_ids,
        )

        schedule_matches_by_tournament: dict[tuple[int, date], list[Match]] = {}
        for match in matches:
            match_date = self._match_date(match)
            if match.tournament_id is not None and match_date in schedule_target_dates:
                schedule_matches_by_tournament.setdefault(
                    (match.tournament_id, match_date), []
                ).append(match)

            previous_payload = self._get_previous_snapshot_payload(
                snapshots_by_match_id.get(match.id, [])
            )
            if match_date == utc_today:
                if self._detect_result_change(match, previous_payload):
                    tournament = (
                        tournament_map.get(match.tournament_id)
                        if match.tournament_id
                        else None
                    )
                    result.result_changes.append(
                        ResultChange(
                            tournament_id=match.tournament_id,
                            tournament_name=tournament.name if tournament else None,
                            target_date=utc_today,
                            match_id=match.id,
                            source_match_id=match.source_match_id,
                            change_types=["first_finished"],
                        )
                    )
                    self._queue_result_job(match, tournament, utc_today, result)

            if match.tournament_id is not None and match_date in schedule_target_dates:
                change_types = self._detect_schedule_change_types(match, previous_payload)
                if change_types:
                    tournament = tournament_map.get(match.tournament_id)
                    if tournament is not None:
                        result.schedule_changes.append(
                            ScheduleChange(
                                tournament_id=tournament.id,
                                tournament_name=tournament.name,
                                target_date=match_date,
                                match_id=match.id,
                                source_match_id=match.source_match_id,
                                change_types=change_types,
                            )
                        )

        for (
            tournament_id,
            target_date,
        ), schedule_matches in schedule_matches_by_tournament.items():
            tournament = tournament_map.get(tournament_id)
            if tournament is None:
                continue
            self._queue_schedule_job(
                tournament=tournament,
                matches=schedule_matches,
                target_date=target_date,
                current_time=current_time,
                result=result,
            )

        self.session.commit()
        logger.info(
            "diff completed: %s schedule changes, %s result changes, %s jobs created",
            len(result.schedule_changes),
            len(result.result_changes),
            len(result.created_job_ids),
        )
        return result

    def _queue_schedule_job(
        self,
        tournament: Tournament,
        matches: list[Match],
        target_date: date,
        current_time: datetime,
        result: DiffRunResult,
    ) -> None:
        if not matches:
            return

        if not self._should_queue_schedule_job(matches, target_date, current_time):
            return

        normalized_matches = sorted(matches, key=self._schedule_sort_key)
        biz_key = f"schedule:{tournament.id}:{target_date.isoformat()}"
        release_version = self.publish_jobs.count_by_biz_key(SCHEDULE_JOB_TYPE, biz_key) + 1
        payload = {
            "source": tournament.source,
            "tournament_id": tournament.id,
            "tournament_name": tournament.name,
            "target_utc_date": target_date.isoformat(),
            "matches": [self._serialize_schedule_match(item) for item in normalized_matches],
            "is_update": False,
            "release_version": release_version,
        }
        content_hash = self._build_hash(payload["matches"])
        if self.publish_jobs.get_by_biz_key_and_content_hash(
            SCHEDULE_JOB_TYPE,
            biz_key,
            content_hash,
        ):
            return

        latest_job = self.publish_jobs.get_latest_by_biz_key(SCHEDULE_JOB_TYPE, biz_key)
        if latest_job is not None:
            payload["is_update"] = True
            payload["previous_job_id"] = latest_job.id

        job = self.publish_jobs.create(
            job_type=SCHEDULE_JOB_TYPE,
            biz_key=biz_key,
            content_hash=content_hash,
            payload=payload,
        )
        result.created_job_ids.append(job.id)

    def _should_queue_schedule_job(
        self,
        matches: list[Match],
        target_date: date,
        current_time: datetime,
    ) -> bool:
        if self._all_matches_truly_scheduled(matches):
            return True

        if target_date != current_time.date():
            return False

        earliest_start = min(
            (item.scheduled_at_utc for item in matches if item.scheduled_at_utc is not None),
            default=None,
        )
        if earliest_start is None:
            return False

        return earliest_start - current_time < timedelta(hours=6)

    def _all_matches_truly_scheduled(self, matches: list[Match]) -> bool:
        return all(item.scheduled_at_utc is not None for item in matches)

    def _queue_result_job(
        self,
        match: Match,
        tournament: Tournament | None,
        target_date: date,
        result: DiffRunResult,
    ) -> None:
        if not self._is_key_match(match):
            return

        payload = {
            "match_id": match.id,
            "source_match_id": match.source_match_id,
            "tournament_id": match.tournament_id,
            "tournament_name": tournament.name if tournament else None,
            "target_utc_date": target_date.isoformat(),
            "round_name": match.round_name,
            "scheduled_at_utc": self._serialize_datetime(match.scheduled_at_utc),
            "scheduled_at_local": (
                match.scheduled_at_utc.astimezone(self.article_timezone).isoformat()
                if match.scheduled_at_utc is not None
                else None
            ),
            "court_name": match.court_name,
            "player1_name": match.player1_name,
            "player2_name": match.player2_name,
            "score_text": match.score_text,
            "winner_name": match.winner_name,
            "status": match.status,
        }
        biz_key = f"result:{match.id}"
        content_hash = self._build_hash(payload)
        if self.publish_jobs.get_by_biz_key_and_content_hash(
            RESULT_JOB_TYPE,
            biz_key,
            content_hash,
        ):
            return

        job = self.publish_jobs.create(
            job_type=RESULT_JOB_TYPE,
            biz_key=biz_key,
            content_hash=content_hash,
            payload=payload,
        )
        result.created_job_ids.append(job.id)

    def _detect_schedule_change_types(
        self,
        match: Match,
        previous_payload: dict | None,
    ) -> list[str]:
        if previous_payload is None:
            return ["new_match"]

        change_types: list[str] = []
        if self._payload_value(previous_payload, "round_name") != match.round_name:
            change_types.append("round_changed")
        if self._payload_value(previous_payload, "scheduled_at_utc") != self._serialize_datetime(
            match.scheduled_at_utc
        ):
            change_types.append("time_changed")
        if self._payload_value(previous_payload, "court_name") != match.court_name:
            change_types.append("court_changed")
        if (
            self._payload_value(previous_payload, "player1_name") != match.player1_name
            or self._payload_value(previous_payload, "player2_name") != match.player2_name
        ):
            change_types.append("players_changed")
        if self._payload_value(previous_payload, "status") != match.status:
            change_types.append("status_changed")
        return change_types

    def _detect_result_change(self, match: Match, previous_payload: dict | None) -> bool:
        if match.status not in FINISHED_STATUSES or not match.score_text or not match.winner_name:
            return False

        if previous_payload is None:
            return True

        previous_status = self._payload_value(previous_payload, "status")
        return previous_status not in FINISHED_STATUSES

    def _get_previous_snapshot_payload(self, snapshots: list) -> dict | None:
        if len(snapshots) < 2:
            return None
        return snapshots[1].payload

    def _match_date(self, match: Match) -> date | None:
        if match.scheduled_at_utc is not None:
            return match.scheduled_at_utc.astimezone(UTC).date()

        metadata = match.metadata_json or {}
        oop_day = metadata.get("oop", {}).get("day", {})
        iso_date = oop_day.get("iso_date")
        if iso_date:
            return date.fromisoformat(iso_date)

        raw_match_time = parse_wta_datetime(metadata.get("MatchTimeStamp"))
        if raw_match_time is not None:
            return raw_match_time.astimezone(UTC).date()
        return None

    def _is_key_match(self, match: Match) -> bool:
        if match.is_key_match:
            return True

        focus_countries = {country.upper() for country in self.settings.focus_countries}
        player_countries = {
            (match.player1_country or "").upper(),
            (match.player2_country or "").upper(),
        }
        return any(
            [
                match.player1_seed is not None,
                match.player2_seed is not None,
                bool(focus_countries.intersection(player_countries)),
            ]
        )

    def _serialize_schedule_match(self, match: Match) -> dict:
        local_time = None
        if match.scheduled_at_utc is not None:
            local_time = match.scheduled_at_utc.astimezone(self.article_timezone).isoformat()

        return {
            "match_id": match.id,
            "source_match_id": match.source_match_id,
            "round_name": match.round_name,
            "scheduled_at_utc": self._serialize_datetime(match.scheduled_at_utc),
            "scheduled_at_local": local_time,
            "court_name": match.court_name,
            "player1_name": match.player1_name,
            "player2_name": match.player2_name,
            "status": match.status,
            "is_key_match": self._is_key_match(match),
        }

    def _schedule_sort_key(self, match: Match) -> tuple:
        return (
            match.scheduled_at_utc or datetime.max.replace(tzinfo=UTC),
            match.round_name or "",
            match.source_match_id,
        )

    def _payload_value(self, payload: dict, field: str):
        if field == "round_name":
            round_id = payload.get("RoundID")
            if round_id is None:
                return None
            mapping = {
                "1": "Round 1",
                "2": "Round 2",
                "3": "Round 3",
                "4": "Round 4",
                "5": "Quarterfinal",
                "6": "Semifinal",
                "7": "Final",
            }
            return mapping.get(str(round_id), f"Round {round_id}")
        if field == "scheduled_at_utc":
            value = parse_wta_datetime(payload.get("MatchTimeStamp"))
            return self._serialize_datetime(value)
        if field == "court_name":
            return (payload.get("Venue") or {}).get("name")
        if field == "player1_name":
            return self._build_player_name(payload, "A")
        if field == "player2_name":
            return self._build_player_name(payload, "B")
        if field == "status":
            mapping = {
                "F": "finished",
                "C": "cancelled",
                "S": "scheduled",
                "U": "scheduled",
                "D": "delayed",
                "I": "in_progress",
                "L": "live",
                "P": "in_progress",
            }
            value = payload.get("MatchState")
            return mapping.get((value or "").upper(), (value or "scheduled").lower())
        if field == "score_text":
            return payload.get("ScoreString") or None
        if field == "winner_name":
            winner = str(payload.get("Winner") or "")
            if winner == "2":
                return self._build_player_name(payload, "A")
            if winner == "3":
                return self._build_player_name(payload, "B")
            return None
        return None

    def _build_player_name(self, payload: dict, suffix: str) -> str | None:
        first = payload.get(f"PlayerNameFirst{suffix}") or ""
        last = payload.get(f"PlayerNameLast{suffix}") or ""
        name = f"{first} {last}".strip()
        return name or None

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat()

    def _build_hash(self, payload: object) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()
