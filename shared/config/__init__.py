"""Single source of configuration. Standing rule 5: environments differ in
these values only, never in code paths."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ingestion
    news_feeds: str = Field(
        default="https://feeds.bbci.co.uk/news/world/rss.xml,https://techcrunch.com/feed/",
        description="Comma-separated RSS feed URLs",
    )

    # Kafka / Redpanda
    kafka_bootstrap: str = "127.0.0.1:19092"
    kafka_topic: str = "news.raw"
    pandaproxy_url: str = "http://localhost:8082"
    ingest_api_key: str = "change-me"

    # Storage
    duckdb_path: str = "data/news.duckdb"

    # Scheduler
    cycle_interval_s: int = 300

    # LLM
    groq_api_key: str = ""
    gemini_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.5-flash"
    llm_daily_call_budget: int = 200   # gemini-2.5-flash free tier: 250 RPD
    ai_max_per_cycle: int = 10         # bounds cycle time and spreads quota use
    ai_call_interval_s: float = 13.0   # free tier is 5 RPM; ~4.6/min stays under

    # LangSmith (spec requirement; free tier)
    langchain_tracing_v2: str = "false"
    langchain_api_key: str = ""
    langchain_project: str = "news-ai-platform"
    langchain_endpoint: str = "https://api.smith.langchain.com"  # EU: https://eu.api.smith.langchain.com

    # Misc
    log_level: str = "INFO"

    @property
    def feed_urls(self) -> list[str]:
        return [u.strip() for u in self.news_feeds.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
