"""Chat API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.copilot import CopilotService

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="Send a support message")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Main copilot endpoint. Accepts a customer support message and returns
    a grounded answer with citations, confidence, and routing metadata.
    """
    try:
        service = CopilotService(db)
        return await service.handle_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/feedback", summary="Submit feedback on a response")
async def submit_feedback(
    request_id: str,
    rating: int,
    was_helpful: bool,
    comment: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Record user feedback on a copilot response for future evaluation."""
    from app.models.orm import Feedback

    fb = Feedback(
        request_id=request_id,
        rating=max(1, min(5, rating)),
        was_helpful=was_helpful,
        comment=comment[:2000],
    )
    db.add(fb)
    await db.flush()
    return {"status": "recorded", "request_id": request_id}
