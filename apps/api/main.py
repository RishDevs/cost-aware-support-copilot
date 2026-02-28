"""
Cost-Aware LLM Support Copilot — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.v1 import chat, documents, analytics, evaluation, health
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import init_db

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    configure_logging()
    log.info("Starting Cost-Aware Support Copilot API", version="1.0.0")
    await init_db()
    log.info("Database initialized successfully")
    yield
    log.info("Shutting down API — goodbye!")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cost-Aware LLM Support Copilot",
        description=(
            "AI-powered customer support assistant with dynamic model routing, "
            "RAG retrieval, cost tracking, and observability."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Routers ───────────────────────────────────────────────────────
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix, tags=["Health"])
    app.include_router(chat.router, prefix=prefix, tags=["Chat"])
    app.include_router(documents.router, prefix=prefix, tags=["Documents"])
    app.include_router(analytics.router, prefix=prefix, tags=["Analytics"])
    app.include_router(evaluation.router, prefix=prefix, tags=["Evaluation"])

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )
