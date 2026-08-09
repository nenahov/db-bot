from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    sqlite_path: Path = Field(default=BASE_DIR / "data" / "bot.db", alias="SQLITE_PATH")
    query_preview_rows: int = Field(default=50, alias="QUERY_PREVIEW_ROWS")
    query_max_rows: int = Field(default=50_000, alias="QUERY_MAX_ROWS")
    query_timeout_sec: int = Field(default=60, alias="QUERY_TIMEOUT_SEC")
    result_cache_ttl_sec: int = Field(default=3600, alias="RESULT_CACHE_TTL_SEC")
    log_dir: Path = Field(default=BASE_DIR / "logs", alias="LOG_DIR")


@lru_cache
def get_settings() -> Settings:
    return Settings()
