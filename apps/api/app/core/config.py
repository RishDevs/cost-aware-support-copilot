"""Application configuration via Pydantic Settings."""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = True
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "change-me"
    DEBUG_MODE: bool = False
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── LLM Models ────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    TIER_A_MODEL: str = "gpt-3.5-turbo"       # cheap-fast
    TIER_B_MODEL: str = "gpt-4o-mini"          # balanced
    TIER_C_MODEL: str = "gpt-4o"               # premium

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "copilot"
    POSTGRES_PASSWORD: str = "copilot"
    POSTGRES_DB: str = "copilot_db"

    # ── Redis ─────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TTL_SECONDS: int = 3600
    SEMANTIC_CACHE_THRESHOLD: float = 0.92

    # ── Vector DB ─────────────────────────────────────────────────────
    VECTOR_COLLECTION: str = "support_chunks"
    VECTOR_DIM: int = 1536
    TOP_K_DEFAULT: int = 6
    RERANKER_TOP_K: int = 3

    # ── Cost / Budget ─────────────────────────────────────────────────
    DAILY_BUDGET_USD: float = 50.0
    BUDGET_ALERT_PCT: float = 0.80
    EMERGENCY_CHEAP_MODE_PCT: float = 0.95

    # ── Router Thresholds ─────────────────────────────────────────────
    CONFIDENCE_HIGH_THRESHOLD: float = 0.75
    CONFIDENCE_LOW_THRESHOLD: float = 0.40
    ESCALATION_THRESHOLD: float = 0.35

    # ── Feature Flags ─────────────────────────────────────────────────
    ENABLE_CACHING: bool = True
    ENABLE_RERANKER: bool = True
    ENABLE_TOOLS: bool = True
    ENABLE_GUARDRAILS: bool = True
    ENABLE_PII_REDACTION: bool = True

    # ── Observability ─────────────────────────────────────────────────
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ── Model Pricing (USD per 1k tokens) ─────────────────────────────
    MODEL_PRICING: dict = {
        "gpt-3.5-turbo":   {"input": 0.0005, "output": 0.0015},
        "gpt-4o-mini":     {"input": 0.00015, "output": 0.0006},
        "gpt-4o":          {"input": 0.005,  "output": 0.015},
        "text-embedding-3-small": {"input": 0.00002, "output": 0.0},
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
