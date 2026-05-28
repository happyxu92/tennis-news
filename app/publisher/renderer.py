from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape


@dataclass(slots=True)
class RenderedArticle:
    title: str
    summary: str
    html: str


@dataclass(slots=True)
class CourtGroup:
    name: str
    matches: list[dict]
    match_count: int
    key_match_count: int


class ArticleRenderer:
    """Renders article payloads into WeChat-friendly HTML."""

    def __init__(self, article_timezone: str = "Asia/Shanghai") -> None:
        template_dir = Path(__file__).with_name("templates")
        self.timezone_label = (
            "北京时间" if article_timezone == "Asia/Shanghai" else article_timezone
        )
        self.article_timezone = ZoneInfo(article_timezone)
        self.environment = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(enabled_extensions=("html", "xml", "j2")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        job_type: str,
        payload: dict,
        rendered_at: datetime | None = None,
    ) -> RenderedArticle:
        current_time = rendered_at or datetime.now(self.article_timezone)
        if job_type == "schedule_article":
            return self._render_schedule_article(payload, current_time)
        if job_type == "result_article":
            return self._render_result_article(payload)
        raise ValueError(f"Unsupported job type: {job_type}")

    def _render_schedule_article(self, payload: dict, rendered_at: datetime) -> RenderedArticle:
        target_date = payload.get("target_utc_date") or ""
        title = self._build_schedule_title(
            tournament_name=payload.get("tournament_name"),
            target_date=target_date,
            source=payload.get("source"),
            release_version=int(payload.get("release_version") or 1),
            is_update=bool(payload.get("is_update")),
        )
        courts = self._group_matches_by_court(payload.get("matches", []))
        total_matches = sum(item.match_count for item in courts)
        key_matches = sum(item.key_match_count for item in courts)
        summary = self._build_schedule_summary(total_matches, len(courts), key_matches)
        template = self.environment.get_template("schedule_article.html.j2")
        html = template.render(
            title=title,
            summary=summary,
            article_label="赛程更新" if payload.get("is_update") else "赛事赛程",
            timezone_label=self.timezone_label,
            updated_at_text=rendered_at.astimezone(self.article_timezone).strftime(
                "%Y-%m-%d %H:%M"
            ),
            courts=[
                {
                    "name": item.name,
                    "matches": item.matches,
                    "match_count": item.match_count,
                    "key_match_count": item.key_match_count,
                }
                for item in courts
            ],
        )
        return RenderedArticle(title=title, summary=summary, html=self._compact_html(html))

    def _render_result_article(self, payload: dict) -> RenderedArticle:
        player1_name = payload.get("player1_name")
        player2_name = payload.get("player2_name")
        winner_name = payload.get("winner_name")
        loser_name = self._get_loser_name(player1_name, player2_name, winner_name)
        title = self._build_result_title(
            tournament_name=payload.get("tournament_name"),
            winner_name=winner_name,
            loser_name=loser_name,
            score_text=payload.get("score_text"),
            round_name=payload.get("round_name"),
        )
        summary = self._build_result_summary(
            tournament_name=payload.get("tournament_name"),
            player1_name=player1_name,
            player2_name=player2_name,
            score_text=payload.get("score_text"),
            winner_name=winner_name,
        )
        lead_text = self._build_result_lead(
            winner_name=winner_name,
            loser_name=loser_name,
            score_text=payload.get("score_text"),
            tournament_name=payload.get("tournament_name"),
            round_name=payload.get("round_name"),
        )
        template = self.environment.get_template("result_article.html.j2")
        html = template.render(
            title=title,
            summary=summary,
            timezone_label=self.timezone_label,
            player1_name=player1_name,
            player2_name=player2_name,
            score_text=payload.get("score_text"),
            winner_name=winner_name,
            tournament_name=payload.get("tournament_name"),
            round_name=payload.get("round_name"),
            time_text=self._format_match_time(payload),
            court_name=payload.get("court_name"),
            status_label=self._status_label(payload.get("status")),
            lead_text=lead_text,
        )
        return RenderedArticle(title=title, summary=summary, html=self._compact_html(html))

    def _compact_html(self, html: str) -> str:
        compact = re.sub(r">\s+<", "><", html)
        return compact.strip()

    def _group_matches_by_court(self, matches: list[dict]) -> list[CourtGroup]:
        grouped: dict[str, list[dict]] = {}
        for match in matches:
            court_name = (match.get("court_name") or "").strip() or "待定场地"
            normalized = {
                **match,
                "court_name": court_name,
                "time_text": self._format_schedule_time(match),
                "status_label": self._status_label(match.get("status")),
            }
            grouped.setdefault(court_name, []).append(normalized)

        courts: list[CourtGroup] = []
        for name, items in grouped.items():
            sorted_matches = sorted(items, key=self._schedule_match_sort_key)
            courts.append(
                CourtGroup(
                    name=name,
                    matches=sorted_matches,
                    match_count=len(sorted_matches),
                    key_match_count=sum(1 for item in sorted_matches if item.get("is_key_match")),
                )
            )

        return sorted(courts, key=lambda item: (item.name == "待定场地", item.name.casefold()))

    def _schedule_match_sort_key(self, match: dict) -> tuple[int, str, str, str]:
        local_time = match.get("scheduled_at_local") or ""
        return (
            1 if not local_time else 0,
            local_time,
            match.get("round_name") or "",
            match.get("source_match_id") or "",
        )

    def _build_schedule_title(
        self,
        tournament_name: str | None,
        target_date: str,
        source: str | None,
        release_version: int,
        is_update: bool,
    ) -> str:
        prefix = self._source_label(source)
        if release_version > 1:
            suffix = f"赛程第{release_version - 1}次更新"
        elif is_update:
            suffix = "赛程更新"
        else:
            suffix = "赛程首发"
        date_text = self._format_target_date(target_date)
        return f"{prefix}{tournament_name or '网球赛事'}{date_text}{suffix}"

    def _build_schedule_summary(
        self,
        total_matches: int,
        court_count: int,
        key_matches: int,
    ) -> str:
        parts = [f"共 {court_count} 个场地", f"{total_matches} 场比赛安排"]
        if key_matches:
            parts.append(f"其中焦点战 {key_matches} 场")
        return "，".join(parts) + "。"

    def _build_result_title(
        self,
        tournament_name: str | None,
        winner_name: str | None,
        loser_name: str | None,
        score_text: str | None,
        round_name: str | None,
    ) -> str:
        event_name = self._short_tournament_name(tournament_name)
        winner = winner_name or "球员"
        opponent = loser_name or "对手"
        score = self._format_title_score(score_text)
        stage = self._round_outcome_label(round_name)
        if stage:
            return f"{event_name}战报｜{winner} {score} 击败{opponent} {stage}"
        return f"{event_name}战报｜{winner} {score} 击败{opponent}"

    def _build_result_summary(
        self,
        tournament_name: str | None,
        player1_name: str | None,
        player2_name: str | None,
        score_text: str | None,
        winner_name: str | None,
    ) -> str:
        return (
            f"{tournament_name or '赛事战报'}，"
            f"{player1_name or '待定选手'} 对阵 {player2_name or '待定选手'}，"
            f"最终比分 {score_text or '待更新'}，胜者为 {winner_name or '待确认'}。"
        )

    def _build_result_lead(
        self,
        winner_name: str | None,
        loser_name: str | None,
        score_text: str | None,
        tournament_name: str | None,
        round_name: str | None,
    ) -> str:
        winner = winner_name or "球员"
        loser = loser_name or "对手"
        event_name = tournament_name or "本站赛事"
        round_text = round_name or "本轮比赛"
        return (
            f"{event_name}{round_text}结束，{winner}以 {score_text or '比分待更新'} "
            f"击败{loser}，拿下这场关键胜利。"
        )

    def _format_schedule_time(self, match: dict) -> str:
        if match.get("scheduled_at_local"):
            return self._format_iso_datetime(match["scheduled_at_local"])
        if match.get("scheduled_at_utc"):
            return self._format_iso_datetime(match["scheduled_at_utc"])
        return "时间待定"

    def _format_match_time(self, payload: dict) -> str:
        if payload.get("scheduled_at_local"):
            return self._format_iso_datetime(payload["scheduled_at_local"])
        if payload.get("scheduled_at_utc"):
            return self._format_iso_datetime(payload["scheduled_at_utc"])
        if payload.get("target_utc_date"):
            return self._format_target_date(payload["target_utc_date"])
        return "时间待定"

    def _format_iso_datetime(self, value: str) -> str:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.article_timezone)
        else:
            dt = dt.astimezone(self.article_timezone)
        return dt.strftime("%m月%d日 %H:%M")

    def _format_target_date(self, value: str) -> str:
        if not value:
            return ""
        dt = datetime.fromisoformat(f"{value}T00:00:00")
        return dt.strftime("%m月%d日")

    def _status_label(self, status: str | None) -> str:
        mapping = {
            "scheduled": "待开赛",
            "finished": "已完赛",
            "in_progress": "进行中",
            "live": "直播中",
            "delayed": "已延期",
            "cancelled": "已取消",
            "u": "待开赛",
            "p": "进行中",
        }
        return mapping.get((status or "").lower(), status or "状态待定")

    def _short_tournament_name(self, tournament_name: str | None) -> str:
        mapping = {
            "Roland Garros": "法网",
            "Australian Open": "澳网",
            "Wimbledon": "温网",
            "US Open": "美网",
        }
        if tournament_name in mapping:
            return mapping[tournament_name]
        return tournament_name or "网球"

    def _source_label(self, source: str | None) -> str:
        mapping = {
            "wta": "WTA｜",
            "atp": "ATP｜",
        }
        return mapping.get((source or "").lower(), "")

    def _round_outcome_label(self, round_name: str | None) -> str | None:
        mapping = {
            "Round 1": "晋级次轮",
            "Round 2": "晋级第三轮",
            "Round 3": "晋级16强",
            "Round 4": "晋级八强",
            "Quarterfinal": "晋级四强",
            "Semifinal": "晋级决赛",
            "Final": "夺得冠军",
        }
        return mapping.get(round_name or "")

    def _format_title_score(self, score_text: str | None) -> str:
        if not score_text:
            return "取胜"
        sets = [item for item in score_text.split(",") if item.strip()]
        if not sets:
            return "取胜"
        winner_sets = (len(sets) // 2) + 1
        loser_sets = len(sets) - winner_sets
        return f"{winner_sets}-{loser_sets}"

    def _get_loser_name(
        self,
        player1_name: str | None,
        player2_name: str | None,
        winner_name: str | None,
    ) -> str | None:
        if not winner_name:
            return None
        if winner_name == player1_name:
            return player2_name
        if winner_name == player2_name:
            return player1_name
        return player2_name or player1_name
