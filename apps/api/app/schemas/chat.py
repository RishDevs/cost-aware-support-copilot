"""Pydantic schemas for the chat/copilot API."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class SupportIntent(str, Enum):
    RETURNS = "returns"
    REFUNDS = "refunds"
    SHIPPING = "shipping"
    ORDER_STATUS = "order_status"
    PAYMENT = "payment"
    ACCOUNT = "account"
    PRODUCT = "product"
    WARRANTY = "warranty"
    GENERAL = "general"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelTier(str, Enum):
    CHEAP = "cheap"        # Tier A — fast, low cost
    BALANCED = "balanced"  # Tier B — moderate
    PREMIUM = "premium"    # Tier C — high quality


class SLAMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Request Models ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., description="user | assistant | system")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    conversation_id: Optional[str] = Field(default=None)
    history: List[ChatMessage] = Field(default_factory=list)
    sla_mode: SLAMode = Field(default=SLAMode.BALANCED)
    debug: bool = Field(default=False)


# ── Citation / Chunk ──────────────────────────────────────────────────────────

class CitationChunk(BaseModel):
    chunk_id: str
    document_title: str
    section_title: Optional[str]
    snippet: str
    relevance_score: float
    policy_type: Optional[str]
    source_url: Optional[str]


# ── Router Decision ───────────────────────────────────────────────────────────

class RouterDecision(BaseModel):
    model_tier: ModelTier
    model_name: str
    top_k: int
    use_reranker: bool
    max_output_tokens: int
    allow_tools: bool
    escalation_threshold: float
    decision_reason: str
    budget_usage_pct: float


# ── Token / Cost Usage ────────────────────────────────────────────────────────

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


# ── Tool Call ─────────────────────────────────────────────────────────────────

class ToolCall(BaseModel):
    tool_name: str
    input_data: dict
    output_data: dict
    success: bool
    latency_ms: float


# ── Main Chat Response ────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    answer: str
    citations: List[CitationChunk] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    needs_human: bool = False
    escalation_reason: Optional[str] = None
    follow_up_question: Optional[str] = None

    # Operational metadata
    model_used: str
    model_tier: ModelTier
    latency_ms: float
    token_usage: TokenUsage
    cache_hit: bool = False
    cache_type: Optional[str] = None  # "exact" | "semantic" | None
    tool_calls: List[ToolCall] = Field(default_factory=list)

    # Debug data (only populated when debug=True)
    debug: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Classification ────────────────────────────────────────────────────────────

class QueryClassification(BaseModel):
    intent: SupportIntent
    risk_level: RiskLevel
    complexity_score: float = Field(ge=0.0, le=1.0)
    requires_tool: bool = False
    requires_order_id: bool = False
    is_multi_intent: bool = False
    sentiment: str = "neutral"  # positive | neutral | negative | frustrated
    confidence: float = Field(ge=0.0, le=1.0)
