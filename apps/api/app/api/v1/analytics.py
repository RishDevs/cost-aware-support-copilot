"""Analytics and observability endpoints."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.orm import LLMCall, RouterDecisionLog
from services.analytics.budget import BudgetTracker

router = APIRouter()


@router.get("/analytics/budget", summary="Daily budget status")
async def get_budget():
    tracker = BudgetTracker()
    return await tracker.get_summary()


@router.get("/analytics/cost-breakdown", summary="Cost by model tier (last 7 days)")
async def cost_breakdown(db: AsyncSession = Depends(get_db)):
    sql = text("""
        SELECT
            model_tier,
            model_name,
            COUNT(*)            AS call_count,
            SUM(input_tokens)   AS total_input_tokens,
            SUM(output_tokens)  AS total_output_tokens,
            SUM(cost_usd)       AS total_cost_usd,
            AVG(latency_ms)     AS avg_latency_ms,
            SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) AS cache_hits
        FROM llm_calls
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY model_tier, model_name
        ORDER BY total_cost_usd DESC
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    return {"period": "last_7_days", "breakdown": [dict(r) for r in rows]}


@router.get("/analytics/routing-decisions", summary="Router decision distribution")
async def routing_decisions(db: AsyncSession = Depends(get_db)):
    sql = text("""
        SELECT
            intent,
            model_tier,
            COUNT(*) AS count,
            AVG(retrieval_confidence) AS avg_retrieval_confidence
        FROM router_decisions
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY intent, model_tier
        ORDER BY count DESC
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    return {"period": "last_7_days", "decisions": [dict(r) for r in rows]}


@router.get("/analytics/latency", summary="P50/P95 latency by tier")
async def latency_stats(db: AsyncSession = Depends(get_db)):
    sql = text("""
        SELECT
            model_tier,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
            AVG(latency_ms) AS avg_ms,
            COUNT(*) AS count
        FROM llm_calls
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY model_tier
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    return {"period": "last_7_days", "latency": [dict(r) for r in rows]}


@router.get("/analytics/escalation-rate", summary="Escalation rate by intent")
async def escalation_rate(db: AsyncSession = Depends(get_db)):
    sql = text("""
        SELECT
            intent,
            COUNT(*) AS total,
            SUM(CASE WHEN escalation_threshold > retrieval_confidence THEN 1 ELSE 0 END) AS escalated
        FROM router_decisions
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY intent
        ORDER BY escalated DESC
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    data = [
        {
            **dict(r),
            "escalation_rate_pct": round(r["escalated"] / max(r["total"], 1) * 100, 1),
        }
        for r in rows
    ]
    return {"period": "last_7_days", "escalation": data}
