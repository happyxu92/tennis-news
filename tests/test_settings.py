import os

from app.settings import AppSettings


def test_settings_defaults(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("TENNIS_NEWS_"):
            monkeypatch.delenv(key, raising=False)

    settings = AppSettings(_env_file=None)

    assert settings.app_name == "tennis-news"
    assert settings.source_provider == "wta"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.scheduler_interval_minutes == 15
    assert settings.wechat_publish_enabled is False
    assert settings.wechat_author == "happy"
    assert settings.wechat_default_cover_media_id == ""
    assert settings.wechat_publish_max_retries == 3
