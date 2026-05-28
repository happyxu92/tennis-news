from __future__ import annotations

from datetime import UTC, datetime

from app.publisher.renderer import ArticleRenderer


def test_render_schedule_article_groups_matches_by_court() -> None:
    renderer = ArticleRenderer()

    rendered = renderer.render(
        job_type="schedule_article",
        payload={
            "source": "wta",
            "tournament_name": "Roland Garros",
            "target_utc_date": "2026-05-29",
            "is_update": True,
            "release_version": 2,
            "matches": [
                {
                    "source_match_id": "m2",
                    "round_name": "Semifinal",
                    "scheduled_at_local": "2026-05-29T19:30:00+08:00",
                    "court_name": "Court Suzanne Lenglen",
                    "player1_name": "Player C",
                    "player2_name": "Player D",
                    "status": "scheduled",
                    "is_key_match": False,
                },
                {
                    "source_match_id": "m1",
                    "round_name": "Quarterfinal",
                    "scheduled_at_local": "2026-05-29T17:00:00+08:00",
                    "court_name": "Court Philippe-Chatrier",
                    "player1_name": "Qinwen Zheng",
                    "player2_name": "Player B",
                    "status": "scheduled",
                    "is_key_match": True,
                },
                {
                    "source_match_id": "m3",
                    "round_name": "Round 2",
                    "scheduled_at_local": None,
                    "scheduled_at_utc": None,
                    "court_name": None,
                    "player1_name": "Player E",
                    "player2_name": "Player F",
                    "status": "delayed",
                    "is_key_match": False,
                },
            ],
        },
        rendered_at=datetime.fromisoformat("2026-05-28T12:30:00+08:00"),
    )

    assert rendered.title == "WTA｜Roland Garros05月29日赛程第1次更新"
    assert "共 3 个场地" in rendered.summary
    assert "Court Philippe-Chatrier" in rendered.html
    assert "Court Suzanne Lenglen" in rendered.html
    assert "待定场地" in rendered.html
    assert "焦点" in rendered.html
    assert "更新时间（北京时间）：2026-05-28 12:30" in rendered.html
    assert "<html" not in rendered.html
    assert "<style" not in rendered.html
    assert "class=\"court\"" not in rendered.html

    philippe_index = rendered.html.index("Court Philippe-Chatrier")
    suzanne_index = rendered.html.index("Court Suzanne Lenglen")
    undecided_index = rendered.html.index("待定场地")
    assert philippe_index < suzanne_index < undecided_index


def test_render_schedule_article_converts_match_times_to_beijing_time() -> None:
    renderer = ArticleRenderer()

    rendered = renderer.render(
        job_type="schedule_article",
        payload={
            "source": "wta",
            "tournament_name": "Roland Garros",
            "target_utc_date": "2026-05-29",
            "release_version": 1,
            "is_update": False,
            "matches": [
                {
                    "source_match_id": "m1",
                    "round_name": "Quarterfinal",
                    "scheduled_at_local": "2026-05-29T09:00:00+00:00",
                    "court_name": "Court Philippe-Chatrier",
                    "player1_name": "Qinwen Zheng",
                    "player2_name": "Player B",
                    "status": "scheduled",
                    "is_key_match": True,
                }
            ],
        },
        rendered_at=datetime(2026, 5, 28, 4, 30, tzinfo=UTC),
    )

    assert "更新时间（北京时间）：2026-05-28 12:30" in rendered.html
    assert "时间（北京时间）：05月29日 17:00 ｜ 场地：Court Philippe-Chatrier" in rendered.html


def test_render_schedule_article_marks_first_release_clearly() -> None:
    renderer = ArticleRenderer()

    rendered = renderer.render(
        job_type="schedule_article",
        payload={
            "source": "wta",
            "tournament_name": "Roland Garros",
            "target_utc_date": "2026-05-29",
            "release_version": 1,
            "is_update": False,
            "matches": [],
        },
    )

    assert rendered.title == "WTA｜Roland Garros05月29日赛程首发"
    assert rendered.html.startswith("<section")


def test_render_result_article_uses_requested_title_style() -> None:
    renderer = ArticleRenderer()

    rendered = renderer.render(
        job_type="result_article",
        payload={
            "tournament_name": "Roland Garros",
            "round_name": "Quarterfinal",
            "scheduled_at_utc": "2026-05-28T10:00:00+00:00",
            "court_name": "Court Philippe-Chatrier",
            "player1_name": "Qinwen Zheng",
            "player2_name": "Player B",
            "score_text": "6-4,6-4",
            "winner_name": "Qinwen Zheng",
            "status": "finished",
        },
    )

    assert rendered.title == "法网战报｜Qinwen Zheng 2-0 击败Player B 晋级四强"
    assert "最终比分 6-4,6-4" in rendered.summary
    assert "Court Philippe-Chatrier" in rendered.html
    assert "时间（北京时间）" in rendered.html
    assert "05月28日 18:00" in rendered.html
    assert "已完赛" in rendered.html
    assert "<style" not in rendered.html


def test_render_result_article_handles_missing_optional_fields() -> None:
    renderer = ArticleRenderer()

    rendered = renderer.render(
        job_type="result_article",
        payload={
            "tournament_name": "Unknown Open",
            "round_name": None,
            "target_utc_date": "2026-05-28",
            "player1_name": "Player A",
            "player2_name": "Player B",
            "score_text": None,
            "winner_name": None,
            "status": "scheduled",
        },
    )

    assert rendered.title == "Unknown Open战报｜球员 取胜 击败对手"
    assert "最终比分 待更新" in rendered.summary
    assert "待定场地" in rendered.html
    assert "待开赛" in rendered.html
