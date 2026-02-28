"""Document ingestion and management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()


@router.post("/documents/ingest", summary="Ingest a document into the knowledge base")
async def ingest_document(
    title: str,
    policy_type: str,
    region: str = "global",
    version: str = "1.0",
    file: UploadFile = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a document file (markdown/txt) and runs the ingestion pipeline:
    chunking → embedding → pgvector upsert.
    """
    if file is None:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    text = content.decode("utf-8")

    from services.ingestion.pipeline import IngestionPipeline
    pipeline = IngestionPipeline(db)
    result = await pipeline.ingest(
        title=title,
        text=text,
        policy_type=policy_type,
        region=region,
        version=version,
        source_type=file.content_type or "text/markdown",
    )
    return result


@router.get("/documents", summary="List documents in the knowledge base")
async def list_documents(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, text
    sql = text("SELECT id, title, policy_type, region, version, created_at FROM documents ORDER BY created_at DESC LIMIT 50")
    result = await db.execute(sql)
    rows = result.mappings().all()
    return {"documents": [dict(r) for r in rows]}
