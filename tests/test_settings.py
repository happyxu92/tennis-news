from app.settings import AppSettings


def test_settings_defaults() -> None:
    settings = AppSettings()

    assert settings.app_name == "tennis-news"
    assert settings.source_provider == "wta"
    assert settings.database_url.startswith("sqlite:///")
