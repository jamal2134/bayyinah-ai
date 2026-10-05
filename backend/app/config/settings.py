from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_timeout_seconds: float = Field(default=45, gt=0)
    anthropic_max_retries: int = Field(default=2, ge=0, le=5)
    log_level: str = "INFO"
    http_connect_timeout: float = Field(default=5, gt=0)
    http_read_timeout: float = Field(default=20, gt=0)
    max_provider_query_attempts: int = Field(default=3, ge=1, le=5)
    quranpedia_base_url: str = "https://api.quranpedia.net/v1"
    hadeethenc_base_url: str = "https://hadeethenc.com/api/v1"
    dorar_enabled: bool = False
    dorar_base_url: str = "https://dorar.net"
    dorar_hadith_enabled: bool = True
    dorar_hadith_explanation_enabled: bool = True
    dorar_tafseer_enabled: bool = True
    dorar_feqhia_enabled: bool = True
    dorar_aqeeda_enabled: bool = True
    dorar_history_enabled: bool = True
    dorar_hadith_max_queries: int = Field(default=2, ge=1, le=3)
    dorar_tafseer_max_queries: int = Field(default=2, ge=1, le=3)
    dorar_feqhia_max_queries: int = Field(default=2, ge=1, le=3)
    dorar_aqeeda_max_queries: int = Field(default=2, ge=1, le=3)
    dorar_history_max_queries: int = Field(default=2, ge=1, le=3)
    dorar_hadith_max_results: int = Field(default=15, ge=1, le=50)
    dorar_feqhia_max_results: int = Field(default=15, ge=1, le=50)
    dorar_aqeeda_max_results: int = Field(default=15, ge=1, le=50)
    bayan_base_url: str = "https://www.byenah.com"
    quranpedia_max_concurrency: int = Field(default=2, ge=1, le=10)
    hadeethenc_max_concurrency: int = Field(default=2, ge=1, le=10)
    dorar_max_concurrency: int = Field(default=2, ge=1, le=10)
    bayan_max_concurrency: int = Field(default=1, ge=1, le=10)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

