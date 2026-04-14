from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NBA Playoff Pool"
    database_url: str = "sqlite:///./nba_pool.db"
    secret_key: str = "change-me"
    session_cookie_name: str = "nba_pool_session"
    session_cookie_max_age_days: int = 30
    nba_provider_base_url: str = "https://api.balldontlie.io/v1"
    nba_provider_api_key: str = ""
    scheduler_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
