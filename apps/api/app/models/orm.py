"""SQLAlchemy ORM models for the copilot database."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Documents ─────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(512), nullable=False)
    source_type = Column(String(64))     # markdown | pdf | html | csv
    policy_type = Column(String(128))    # returns | refunds | shipping | ...
    version = Column(String(32), default="1.0")
    region = Column(String(64), default="global")
    effective_date = Column(DateTime, nullable=True)
    content_hash = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    section_title = Column(String(256))
    token_count = Column(Integer)
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")


# ── Conversations ─────────────────────────────────────────────────────────────

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(256), nullable=True)
    status = Column(String(32), default="active")  # active | resolved | escalated
    total_cost_usd = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="conversation")
    llm_calls = relationship("LLMCall", back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(16))  # user | assistant | system
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


# ── Router Decisions ──────────────────────────────────────────────────────────

class RouterDecisionLog(Base):
    __tablename__ = "router_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(64), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    intent = Column(String(64))
    risk_level = Column(String(16))
    retrieval_confidence = Column(Float)
    model_tier = Column(String(16))
    model_name = Column(String(128))
    top_k = Column(Integer)
    use_reranker = Column(Boolean)
    max_output_tokens = Column(Integer)
    allow_tools = Column(Boolean)
    escalation_threshold = Column(Float)
    decision_reason = Column(Text)
    budget_usage_pct = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── LLM Calls ─────────────────────────────────────────────────────────────────

class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(64), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True)
    provider = Column(String(64))            # openai | anthropic | google
    model_name = Column(String(128))
    model_tier = Column(String(16))
    call_type = Column(String(32))           # chat | embedding | rerank
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    embedding_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Float)
    cache_hit = Column(Boolean, default=False)
    cache_type = Column(String(16), nullable=True)
    success = Column(Boolean, default=True)
    error_type = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="llm_calls")


# ── Tool Calls ────────────────────────────────────────────────────────────────

class ToolCallLog(Base):
    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(64))
    input_data = Column(JSON)
    output_data = Column(JSON)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    latency_ms = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Retrieval Logs ────────────────────────────────────────────────────────────

class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(64), nullable=False, index=True)
    query_text = Column(Text)
    top_k = Column(Integer)
    chunk_ids = Column(JSON)           # list of chunk UUIDs
    scores = Column(JSON)              # corresponding scores
    reranker_used = Column(Boolean, default=False)
    latency_ms = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Cache Entries ─────────────────────────────────────────────────────────────

class CacheEntry(Base):
    __tablename__ = "cache_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key = Column(String(256), unique=True, nullable=False)
    cache_type = Column(String(16))    # exact | semantic | retrieval
    query_text = Column(Text)
    response_json = Column(JSON)
    hit_count = Column(Integer, default=0)
    cost_saved_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


# ── Feedback ──────────────────────────────────────────────────────────────────

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(64), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    rating = Column(Integer, nullable=True)         # 1-5
    was_helpful = Column(Boolean, nullable=True)
    was_accurate = Column(Boolean, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Evaluation ────────────────────────────────────────────────────────────────

class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_name = Column(String(256))
    config_snapshot = Column(JSON)
    total_samples = Column(Integer)
    groundedness_score = Column(Float)
    factual_accuracy = Column(Float)
    retrieval_hit_rate = Column(Float)
    avg_cost_usd = Column(Float)
    avg_latency_ms = Column(Float)
    escalation_rate = Column(Float)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
