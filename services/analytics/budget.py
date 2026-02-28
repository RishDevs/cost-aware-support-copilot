"""
Budget Tracker — Tracks daily LLM spend and returns budget usage percentage.
Uses Redis for fast atomic increments; Postgres for persistence.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

import redis.asyncio as aioredis
import structlog

from app.core.config import settings

log = structlog.get_logger()


class BudgetTracker:
    """Thread-safe daily budget tracker backed by Redis."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
        return self._redis

    def _today_key(self) -> str:
        return f"budget:{date.today().isoformat()}"

    async def record_cost(self, cost_usd: float) -> None:
        r = await self._get_redis()
        key = self._today_key()
        await r.incrbyfloat(key, cost_usd)
        await r.expire(key, 86400 * 3)   # keep 3 days retention

    async def get_today_spend(self) -> float:
        r = await self._get_redis()
        val = await r.get(self._today_key())
        return float(val) if val else 0.0

    async def get_budget_usage_pct(self) -> float:
        spend = await self.get_today_spend()
        pct = spend / max(settings.DAILY_BUDGET_USD, 0.01)
        if pct >= settings.BUDGET_ALERT_PCT:
            log.warning(
                "budget.alert",
                spend_usd=round(spend, 4),
                budget_usd=settings.DAILY_BUDGET_USD,
                pct=round(pct, 3),
            )
        return round(pct, 4)

    async def is_budget_exceeded(self) -> bool:
        return await self.get_budget_usage_pct() >= 1.0

    async def get_summary(self) -> dict:
        spend = await self.get_today_spend()
        pct = spend / max(settings.DAILY_BUDGET_USD, 0.01)
        return {
            "date": date.today().isoformat(),
            "spend_usd": round(spend, 4),
            "budget_usd": settings.DAILY_BUDGET_USD,
            "usage_pct": round(pct * 100, 1),
            "alert": pct >= settings.BUDGET_ALERT_PCT,
            "emergency_mode": pct >= settings.EMERGENCY_CHEAP_MODE_PCT,
        }


# ── Cache Manager ─────────────────────────────────────────────────────────────

class CacheManager:
    """Exact and semantic cache for LLM responses."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
        return self._redis

    async def get_exact(self, key: str) -> Optional[dict]:
        r = await self._get_redis()
        raw = await r.get(f"exact:{key}")
        return json.loads(raw) if raw else None

    async def set_exact(self, key: str, value: dict) -> None:
        r = await self._get_redis()
        await r.setex(f"exact:{key}", settings.REDIS_TTL_SECONDS, json.dumps(value))

    async def get_retrieval(self, key: str) -> Optional[list]:
        r = await self._get_redis()
        raw = await r.get(f"retrieval:{key}")
        return json.loads(raw) if raw else None

    async def set_retrieval(self, key: str, value: list) -> None:
        r = await self._get_redis()
        await r.setex(f"retrieval:{key}", settings.REDIS_TTL_SECONDS // 2, json.dumps(value))

    async def increment_hit(self, key: str) -> None:
        r = await self._get_redis()
        await r.incr(f"hits:{key}")

    async def get_stats(self) -> dict:
        r = await self._get_redis()
        exact_keys = await r.keys("exact:*")
        return {"exact_cache_size": len(exact_keys)}
