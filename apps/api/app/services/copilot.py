"""
Main Chat Service — Orchestrates the full copilot pipeline:
  classifier → budget → cache → retrieval → router → generator → guardrails → logging
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CitationChunk,
    ConfidenceBand,
    ModelTier,
    RouterDecision,
    ToolCall,
    TokenUsage,
)
from services.analytics.budget import BudgetTracker, CacheManager
from services.analytics.tools import ToolOrchestrator
from services.guardrails.guardrails import GuardrailService
from services.retrieval.engine import RetrievalEngine
from services.retrieval.generator import AnswerGenerator, ConfidenceEstimator, build_prompt
from services.router.classifier import QueryClassifier
from services.router.router import CostAwareRouter, get_confidence_band

log = structlog.get_logger()


class CopilotService:
    """Main orchestrator — wires all subsystems together per request."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.classifier = QueryClassifier()
        self.router = CostAwareRouter()
        self.retrieval = RetrievalEngine(db)
        self.generator = AnswerGenerator()
        self.confidence_estimator = ConfidenceEstimator()
        self.guardrails = GuardrailService()
        self.budget = BudgetTracker()
        self.cache = CacheManager()
        self.tools = ToolOrchestrator()

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        t_start = time.perf_counter()
        request_id = str(uuid.uuid4())
        conversation_id = request.conversation_id or str(uuid.uuid4())

        log.info(
            "copilot.request",
            request_id=request_id,
            conversation_id=conversation_id,
            sla_mode=request.sla_mode,
        )

        # ── Step 1: Guardrail input check ────────────────────────────────────
        guard = self.guardrails.check_input(request.message)
        if guard["blocked"]:
            return self._blocked_response(request_id, conversation_id, guard["reason"], t_start)

        # ── Step 2: Check for unsupported action ─────────────────────────────
        unsupported = self.guardrails.check_for_unsupported_action(request.message)
        if unsupported:
            return self._unsupported_response(
                request_id, conversation_id, unsupported, t_start
            )

        # ── Step 3: Classify query ────────────────────────────────────────────
        classification = self.classifier.classify(request.message)

        # ── Step 4: Budget state ──────────────────────────────────────────────
        budget_pct = await self.budget.get_budget_usage_pct()

        # ── Step 5: Exact cache lookup ────────────────────────────────────────
        cache_key = self._build_cache_key(request.message)
        if settings.ENABLE_CACHING:
            cached = await self.cache.get_exact(cache_key)
            if cached:
                log.info("copilot.cache_hit", type="exact", request_id=request_id)
                return self._from_cache(cached, request_id, conversation_id, "exact", t_start)

        # ── Step 6: Retrieve relevant context ────────────────────────────────
        citations, retrieval_confidence, embed_tokens = await self.retrieval.retrieve(
            query=request.message,
            top_k=settings.TOP_K_DEFAULT,
        )

        # ── Step 7: Route — select model tier and policy ─────────────────────
        route = self.router.route(
            classification=classification,
            retrieval_confidence=retrieval_confidence,
            budget_usage_pct=budget_pct,
            conversation_turns=len(request.history) // 2 + 1,
            sla_mode=request.sla_mode,
        )

        # ── Step 8: Refine retrieval depth based on route ────────────────────
        if route.top_k != settings.TOP_K_DEFAULT:
            citations, retrieval_confidence, embed_tokens2 = await self.retrieval.retrieve(
                query=request.message,
                top_k=route.top_k,
                use_reranker=route.use_reranker,
            )
            embed_tokens += embed_tokens2

        # Compress context to fit token budget
        context_budget = min(route.max_output_tokens * 4, 3000)
        citations = RetrievalEngine.compress_context(citations, token_budget=context_budget)

        # ── Step 9: Tool calls ────────────────────────────────────────────────
        tool_calls: list[ToolCall] = []
        tool_results: list[dict] = []

        if route.allow_tools and classification.requires_tool:
            tool_result = await self._run_tool(request.message, classification)
            if tool_result:
                tool_calls.append(tool_result)
                tool_results.append({"tool": tool_result.tool_name, "summary": str(tool_result.output_data.get("summary", ""))})

        # ── Step 10: Generate answer ──────────────────────────────────────────
        history = [{"role": m.role, "content": m.content} for m in request.history]
        messages = build_prompt(
            query=request.message,
            citations=citations,
            history=history,
            classification=classification,
            tool_results=tool_results or None,
        )
        answer, token_usage = await self.generator.generate(messages, route)
        token_usage.embedding_tokens = embed_tokens
        token_usage.total_tokens += embed_tokens

        # ── Step 11: Output guardrail ─────────────────────────────────────────
        output_check = self.guardrails.validate_output(answer)
        if not output_check["safe"]:
            log.warning("copilot.output_violation", issues=output_check["issues"])
            answer = (
                "I apologize, but I'm not able to complete that request directly. "
                "Please contact our support team for further assistance."
            )

        # ── Step 12: Confidence + escalation ─────────────────────────────────
        confidence = self.confidence_estimator.estimate(
            citations=citations,
            answer=answer,
            classification_confidence=classification.confidence,
        )
        confidence_band = get_confidence_band(confidence)
        needs_human, escalation_reason = self._escalation_check(
            confidence, route, classification, retrieval_confidence
        )
        follow_up = self._suggest_follow_up(classification, citations, confidence) if not needs_human else None

        # ── Step 13: Budget tracking ──────────────────────────────────────────
        await self.budget.record_cost(token_usage.estimated_cost_usd)

        # ── Step 14: Cache store ──────────────────────────────────────────────
        total_latency = (time.perf_counter() - t_start) * 1000
        response = ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            answer=answer,
            citations=citations,
            confidence=confidence,
            confidence_band=confidence_band,
            needs_human=needs_human,
            escalation_reason=escalation_reason,
            follow_up_question=follow_up,
            model_used=route.model_name,
            model_tier=route.model_tier,
            latency_ms=round(total_latency, 1),
            token_usage=token_usage,
            cache_hit=False,
            tool_calls=tool_calls,
            debug=self._build_debug(request, classification, route, citations, retrieval_confidence) if request.debug else None,
        )

        if settings.ENABLE_CACHING and not needs_human and confidence >= settings.CONFIDENCE_HIGH_THRESHOLD:
            await self.cache.set_exact(cache_key, response.model_dump(mode="json"))

        log.info(
            "copilot.complete",
            request_id=request_id,
            latency_ms=round(total_latency, 1),
            model_tier=route.model_tier,
            confidence=confidence,
            needs_human=needs_human,
            cost_usd=round(token_usage.estimated_cost_usd, 6),
        )

        return response

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _run_tool(self, query: str, classification) -> Optional[ToolCall]:
        import re
        order_match = re.search(r"\bORD[-\s]?\d{5,}\b", query, re.IGNORECASE)
        if order_match:
            order_id = order_match.group(0).replace(" ", "-").upper()
            result = await self.tools.dispatch("order_lookup", {"order_id": order_id})
            return ToolCall(
                tool_name="order_lookup",
                input_data={"order_id": order_id},
                output_data=result,
                success=result.get("success", False),
                latency_ms=result.get("latency_ms", 0),
            )
        return None

    def _escalation_check(self, confidence, route, classification, retrieval_confidence):
        if confidence < route.escalation_threshold:
            return True, f"low_confidence={confidence:.2f}"
        if retrieval_confidence < 0.3 and not classification.requires_tool:
            return True, "insufficient_retrieval"
        return False, None

    def _suggest_follow_up(self, classification, citations, confidence) -> Optional[str]:
        if classification.requires_order_id and all("order" not in c.snippet.lower() for c in citations):
            return "Could you please provide your order number so I can look into this for you?"
        if confidence < settings.CONFIDENCE_LOW_THRESHOLD + 0.15:
            return "Could you share more details about your situation so I can assist you better?"
        return None

    def _build_cache_key(self, query: str) -> str:
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()

    def _from_cache(self, cached: dict, request_id, conversation_id, cache_type, t_start) -> ChatResponse:
        resp = ChatResponse(**cached)
        resp.request_id = request_id
        resp.conversation_id = conversation_id
        resp.cache_hit = True
        resp.cache_type = cache_type
        resp.latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
        return resp

    def _blocked_response(self, request_id, conversation_id, reason, t_start) -> ChatResponse:
        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            answer="I'm sorry, I cannot process that request.",
            confidence=0.0,
            confidence_band=ConfidenceBand.LOW,
            needs_human=True,
            escalation_reason=reason,
            model_used="none",
            model_tier=ModelTier.CHEAP,
            latency_ms=round((time.perf_counter() - t_start) * 1000, 1),
            token_usage=TokenUsage(),
        )

    def _unsupported_response(self, request_id, conversation_id, answer, t_start) -> ChatResponse:
        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            answer=answer,
            confidence=0.95,
            confidence_band=ConfidenceBand.HIGH,
            needs_human=False,
            model_used="guardrail",
            model_tier=ModelTier.CHEAP,
            latency_ms=round((time.perf_counter() - t_start) * 1000, 1),
            token_usage=TokenUsage(),
        )

    def _build_debug(self, request, classification, route, citations, retrieval_confidence) -> dict:
        return {
            "classification": classification.model_dump(),
            "router_decision": route.model_dump(),
            "retrieval_confidence": retrieval_confidence,
            "retrieved_chunks": [
                {
                    "doc": c.document_title,
                    "section": c.section_title,
                    "score": c.relevance_score,
                    "snippet_preview": c.snippet[:120] + "...",
                }
                for c in citations
            ],
        }
