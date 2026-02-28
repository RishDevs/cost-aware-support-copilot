"""
Cost-Aware Router — The Brain of the Copilot.

Decides model tier, retrieval depth, and operational policy for each request.
"""
from __future__ import annotations

import structlog

from app.core.config import settings
from app.schemas.chat import (
    ConfidenceBand,
    ModelTier,
    QueryClassification,
    RiskLevel,
    RouterDecision,
    SLAMode,
    SupportIntent,
)

log = structlog.get_logger()

# ── Cost per token (simplified lookup) ───────────────────────────────────────

TIER_MODEL_MAP: dict[ModelTier, str] = {
    ModelTier.CHEAP:    settings.TIER_A_MODEL,
    ModelTier.BALANCED: settings.TIER_B_MODEL,
    ModelTier.PREMIUM:  settings.TIER_C_MODEL,
}

# Intents that carry financial / legal risk → require stronger models
HIGH_RISK_INTENTS = {
    SupportIntent.REFUNDS,
    SupportIntent.PAYMENT,
}

MEDIUM_RISK_INTENTS = {
    SupportIntent.RETURNS,
    SupportIntent.WARRANTY,
    SupportIntent.SHIPPING,
}


class CostAwareRouter:
    """
    Determines the optimal model tier, retrieval depth, and policy controls
    for each incoming support request, balancing cost ↔ quality ↔ latency.

    Routing signals used:
      - Query classification (intent, risk, complexity, sentiment)
      - Retrieval confidence score
      - Current daily budget usage
      - Conversation complexity (turn count, multi-intent)
      - SLA mode preference
    """

    def route(
        self,
        classification: QueryClassification,
        retrieval_confidence: float,
        budget_usage_pct: float,
        conversation_turns: int = 1,
        sla_mode: SLAMode = SLAMode.BALANCED,
    ) -> RouterDecision:
        tier, reason = self._select_tier(
            classification=classification,
            retrieval_confidence=retrieval_confidence,
            budget_usage_pct=budget_usage_pct,
            conversation_turns=conversation_turns,
            sla_mode=sla_mode,
        )

        top_k = self._select_top_k(classification, retrieval_confidence, tier)
        max_tokens = self._select_max_tokens(tier, sla_mode, classification)
        use_reranker = self._should_rerank(tier, retrieval_confidence, classification)
        allow_tools = self._should_allow_tools(classification, budget_usage_pct)
        escalation_threshold = self._escalation_threshold(classification, budget_usage_pct)

        model_name = TIER_MODEL_MAP[tier]

        log.info(
            "router.decision",
            tier=tier,
            model=model_name,
            top_k=top_k,
            reason=reason,
            retrieval_conf=round(retrieval_confidence, 3),
            budget_pct=round(budget_usage_pct, 3),
        )

        return RouterDecision(
            model_tier=tier,
            model_name=model_name,
            top_k=top_k,
            use_reranker=use_reranker,
            max_output_tokens=max_tokens,
            allow_tools=allow_tools,
            escalation_threshold=escalation_threshold,
            decision_reason=reason,
            budget_usage_pct=budget_usage_pct,
        )

    # ── Internal Logic ────────────────────────────────────────────────────────

    def _select_tier(
        self,
        classification: QueryClassification,
        retrieval_confidence: float,
        budget_usage_pct: float,
        conversation_turns: int,
        sla_mode: SLAMode,
    ) -> tuple[ModelTier, str]:

        intent = classification.intent
        risk = classification.risk_level
        complexity = classification.complexity_score
        sentiment = classification.sentiment

        # Emergency budget mode — keep everything cheap
        if budget_usage_pct >= settings.EMERGENCY_CHEAP_MODE_PCT:
            return ModelTier.CHEAP, "budget_emergency_cheap_mode"

        # SLA override for quality mode
        if sla_mode == SLAMode.QUALITY:
            return ModelTier.PREMIUM, "sla_quality_mode_override"

        # Hard rules — financial/legal risk → always premium
        if risk == RiskLevel.HIGH or intent in HIGH_RISK_INTENTS:
            return ModelTier.PREMIUM, f"high_risk_intent={intent}"

        # Low retrieval confidence → stronger model to avoid hallucination
        if retrieval_confidence < settings.CONFIDENCE_LOW_THRESHOLD:
            return ModelTier.PREMIUM, f"low_retrieval_confidence={retrieval_confidence:.2f}"

        # Multi-intent or complex multi-turn → balanced at minimum
        if classification.is_multi_intent or conversation_turns > 4:
            if complexity > 0.7:
                return ModelTier.PREMIUM, "multi_intent_high_complexity"
            return ModelTier.BALANCED, "multi_intent_moderate"

        # Frustrated customer → bumped up for better empathy
        if sentiment == "frustrated":
            if risk == RiskLevel.MEDIUM or intent in MEDIUM_RISK_INTENTS:
                return ModelTier.BALANCED, "frustrated_customer_risk_medium"

        # Budget pressure — downgrade medium risk to cheap when budget is high
        if budget_usage_pct >= settings.BUDGET_ALERT_PCT:
            if risk == RiskLevel.LOW and retrieval_confidence >= settings.CONFIDENCE_HIGH_THRESHOLD:
                return ModelTier.CHEAP, "budget_pressure_low_risk_high_confidence"

        # High retrieval confidence + low complexity = cheap is fine
        if (
            retrieval_confidence >= settings.CONFIDENCE_HIGH_THRESHOLD
            and complexity < 0.35
            and risk == RiskLevel.LOW
        ):
            return ModelTier.CHEAP, "high_conf_low_complexity_faq"

        # SLA fast mode — try cheap when confidence is decent
        if sla_mode == SLAMode.FAST and retrieval_confidence >= 0.6:
            return ModelTier.CHEAP, "sla_fast_mode_acceptable_confidence"

        # Medium risk or moderate confidence → balanced
        if intent in MEDIUM_RISK_INTENTS or risk == RiskLevel.MEDIUM:
            return ModelTier.BALANCED, f"medium_risk_intent={intent}"

        # Default
        return ModelTier.BALANCED, "default_balanced"

    def _select_top_k(
        self,
        classification: QueryClassification,
        retrieval_confidence: float,
        tier: ModelTier,
    ) -> int:
        """Adaptive top-k based on confidence and tier."""
        if tier == ModelTier.CHEAP:
            return 3
        if tier == ModelTier.PREMIUM:
            return 8 if classification.is_multi_intent else 6
        # Balanced
        if retrieval_confidence >= settings.CONFIDENCE_HIGH_THRESHOLD:
            return 4
        return 6

    def _select_max_tokens(
        self,
        tier: ModelTier,
        sla_mode: SLAMode,
        classification: QueryClassification,
    ) -> int:
        base = {ModelTier.CHEAP: 200, ModelTier.BALANCED: 400, ModelTier.PREMIUM: 700}[tier]
        if sla_mode == SLAMode.FAST:
            return min(base, 180)
        if classification.is_multi_intent:
            return min(base + 150, 800)
        return base

    def _should_rerank(
        self,
        tier: ModelTier,
        retrieval_confidence: float,
        classification: QueryClassification,
    ) -> bool:
        if not settings.ENABLE_RERANKER:
            return False
        if tier == ModelTier.CHEAP:
            return False  # Skip to save latency
        if retrieval_confidence < 0.6 or classification.is_multi_intent:
            return True
        return tier == ModelTier.PREMIUM

    def _should_allow_tools(
        self,
        classification: QueryClassification,
        budget_usage_pct: float,
    ) -> bool:
        if not settings.ENABLE_TOOLS:
            return False
        if budget_usage_pct >= settings.EMERGENCY_CHEAP_MODE_PCT:
            return False
        return classification.requires_tool

    def _escalation_threshold(
        self,
        classification: QueryClassification,
        budget_usage_pct: float,
    ) -> float:
        base = settings.ESCALATION_THRESHOLD
        # Lower threshold (easier escalation) for high risk
        if classification.risk_level == RiskLevel.HIGH:
            return max(base - 0.10, 0.20)
        # Raise threshold when budget is strained (avoid expensive human escalations)
        if budget_usage_pct > 0.90:
            return min(base + 0.10, 0.60)
        return base


def get_confidence_band(score: float) -> ConfidenceBand:
    if score >= settings.CONFIDENCE_HIGH_THRESHOLD:
        return ConfidenceBand.HIGH
    if score >= settings.CONFIDENCE_LOW_THRESHOLD:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW
