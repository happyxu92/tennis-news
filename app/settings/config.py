from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="TENNIS_NEWS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "tennis-news"
    environment: Literal["local", "dev", "test", "prod"] = "local"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/tennis_news.db"

    source_provider: Literal["wta"] = "wta"
    source_api_key: str = ""
    source_base_url: str = "https://www.wtatennis.com"
    source_timeout_seconds: float = 20.0

    sync_enabled: bool = True
    sync_tours: tuple[str, ...] = ("grand_slam", "atp", "wta")
    focus_countries: tuple[str, ...] = ("CHN",)
    wechat_publish_enabled: bool = False
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_author: str = "happy"
    wechat_default_cover_media_id: str = ""
    wechat_default_cover_image_path: str = ""
    wechat_timeout_seconds: float = 20.0
    wechat_publish_poll_interval_seconds: float = 5.0
    wechat_publish_poll_timeout_seconds: float = 120.0
    wechat_publish_max_retries: int = 3

    article_timezone: str = "Asia/Shanghai"
    media_storage_dir: str = "data/media"
    state_dir: str = "data"
    default_source: str = Field(default="wta")


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
