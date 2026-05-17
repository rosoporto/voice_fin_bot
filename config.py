from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(min_length=10)
    allowed_user_ids: str = ""

    openrouter_api_key: str = Field(min_length=10)
    openrouter_chat_model: str = "openai/gpt-4o-mini"
    openrouter_whisper_model: str = "openai/whisper-large-v3"
    openrouter_transcription_language: str | None = "ru"
    openrouter_base_url: HttpUrl = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "Voice Finance Bot"

    google_service_account_file: Path
    google_spreadsheet_id: str = Field(min_length=5)
    google_transactions_sheet: str = "Транзакции"
    google_categories_sheet: str = "Справочник"

    redis_url: str = "redis://localhost:6379/0"
    redis_categories_key: str = "finance:categories"

    log_level: str = "INFO"
    log_file: Path = Path("logs/bot.log")
    analytics_db_file: Path = Path("data/analytics.db")

    @computed_field
    @property
    def allowed_user_id_set(self) -> set[int]:
        if not self.allowed_user_ids.strip():
            return set()
        return {
            int(user_id.strip())
            for user_id in self.allowed_user_ids.split(",")
            if user_id.strip()
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
