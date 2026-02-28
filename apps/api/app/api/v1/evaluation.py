"""Evaluation endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()


@router.post("/eval/run", summary="Run an evaluation batch")
async def run_evaluation(run_name: str, db: AsyncSession = Depends(get_db)):
    """Trigger an offline evaluation run over the gold evaluation dataset."""
    from services.evaluator.evaluator import EvaluationPipeline
    pipeline = EvaluationPipeline(db)
    result = await pipeline.run(run_name=run_name)
    return result


@router.get("/eval/runs", summary="List past evaluation runs")
async def list_eval_runs(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    sql = text("""
        SELECT id, run_name, total_samples, groundedness_score,
               avg_cost_usd, avg_latency_ms, created_at
        FROM eval_runs
        ORDER BY created_at DESC
        LIMIT 20
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    return {"runs": [dict(r) for r in rows]}
