"""Health check endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", summary="Service health check")
async def health():
    return {"status": "ok", "service": "cost-aware-support-copilot", "version": "1.0.0"}


@router.get("/health/ready", summary="Readiness probe")
async def ready():
    return {"ready": True}
