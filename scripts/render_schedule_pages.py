from __future__ import annotations

import argparse
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.crawler.clients.wta import parse_wta_datetime
from app.models import Match, Tournament
from app.publisher import ArticleRenderer
from app.settings import get_settings
from app.storage import create_engine_from_settings, create_session_factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render schedule preview pages")
    parser.add_argument(
        "--dates",
        nargs="*",
        help="UTC dates to render, defaults to today and tomorrow",
    )
    parser.add_argument(
        "--output-dir",
        default="data/rendered",
        help="Directory for rendered HTML files",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    renderer = ArticleRenderer(article_timezone=settings.article_timezone)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    target_dates = _resolve_target_dates(args.dates)

    with session_factory() as session:
        tournaments = list(session.scalars(select(Tournament).order_by(Tournament.id.asc())))
        matches = list(
            session.scalars(
                select(Match)
                .where(Match.tournament_id.is_not(None))
                .order_by(Match.tournament_id.asc(), Match.id.asc())
            )
        )

        matches_by_tournament_date: dict[tuple[int, date], list[Match]] = {}
        for match in matches:
            match_date = _match_date(match)
            if match.tournament_id is None or match_date not in target_dates:
                continue
            matches_by_tournament_date.setdefault(
                (match.tournament_id, match_date), []
            ).append(match)

        tournament_map = {item.id: item for item in tournaments}
        for target_date in target_dates:
            rendered_any = False
            for (
                tournament_id,
                match_date,
            ), tournament_matches in matches_by_tournament_date.items():
                if match_date != target_date:
                    continue
                tournament = tournament_map.get(tournament_id)
                if tournament is None:
                    continue
                payload = {
                    "tournament_id": tournament.id,
                    "tournament_name": tournament.name,
                    "target_utc_date": target_date.isoformat(),
                    "matches": [
                        _serialize_schedule_match(match, settings.article_timezone)
                        for match in tournament_matches
                    ],
                    "is_update": False,
                }
                rendered = renderer.render(
                    job_type="schedule_article",
                    payload=payload,
                    rendered_at=datetime.now(UTC),
                )
                file_name = f"{target_date.isoformat()}-{_slugify(tournament.name)}.html"
                file_path = output_dir / file_name
                file_path.write_text(rendered.html, encoding="utf-8")
                print(file_path)
                rendered_any = True

            if rendered_any:
                continue

            payload = {
                "tournament_name": "网球赛事",
                "target_utc_date": target_date.isoformat(),
                "matches": [],
                "is_update": False,
            }
            rendered = renderer.render(
                job_type="schedule_article",
                payload=payload,
                rendered_at=datetime.now(UTC),
            )
            file_path = output_dir / f"{target_date.isoformat()}-no-schedule.html"
            file_path.write_text(rendered.html, encoding="utf-8")
            print(file_path)


def _resolve_target_dates(raw_dates: list[str] | None) -> list[date]:
    if raw_dates:
        return [date.fromisoformat(item) for item in raw_dates]
    today = datetime.now(UTC).date()
    return [today, today + timedelta(days=1)]


def _match_date(match: Match) -> date | None:
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


def _serialize_schedule_match(match: Match, article_timezone: str) -> dict:
    return {
        "match_id": match.id,
        "source_match_id": match.source_match_id,
        "round_name": match.round_name,
        "scheduled_at_utc": (
            match.scheduled_at_utc.astimezone(UTC).isoformat()
            if match.scheduled_at_utc is not None
            else None
        ),
        "scheduled_at_local": _build_local_time(match, article_timezone),
        "court_name": match.court_name,
        "player1_name": match.player1_name,
        "player2_name": match.player2_name,
        "status": match.status,
        "is_key_match": match.is_key_match,
    }


def _build_local_time(match: Match, article_timezone: str) -> str | None:
    timezone = ZoneInfo(article_timezone)
    if match.scheduled_at_utc is not None:
        return match.scheduled_at_utc.astimezone(timezone).isoformat()
    metadata = match.metadata_json or {}
    raw_match_time = parse_wta_datetime(metadata.get("MatchTimeStamp"))
    if raw_match_time is None or metadata.get("Unscheduled") is True:
        return None
    return raw_match_time.astimezone(timezone).isoformat()


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return normalized.strip("-") or "schedule"


if __name__ == "__main__":
    main()
