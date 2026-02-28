"""
Query Classifier — Maps support queries to intent, risk, and complexity.

v1: Rule-based with keyword matching (fast, zero-cost).
Upgrade path: Replace _classify_intent() with a small LLM or fine-tuned classifier.
"""
from __future__ import annotations

import re

import structlog

from app.schemas.chat import QueryClassification, RiskLevel, SupportIntent

log = structlog.get_logger()

# ── Keyword Intent Maps ───────────────────────────────────────────────────────

INTENT_PATTERNS: dict[SupportIntent, list[str]] = {
    SupportIntent.RETURNS: [
        r"\breturn\b", r"\bsend back\b", r"\bexchange\b", r"\bswap\b",
        r"\breturn window\b", r"\breturn policy\b",
    ],
    SupportIntent.REFUNDS: [
        r"\brefund\b", r"\bget my money back\b", r"\bcharge.?back\b",
        r"\bovercharged\b", r"\bdouble.?charged\b", r"\bwrong amount\b",
    ],
    SupportIntent.SHIPPING: [
        r"\bshipping\b", r"\bdelivery\b", r"\btracking\b", r"\bshipped\b",
        r"\bin transit\b", r"\bdelayed\b", r"\bnot (yet )?arrived\b",
    ],
    SupportIntent.ORDER_STATUS: [
        r"\border status\b", r"\bwhere is my order\b", r"\bwhen will it arrive\b",
        r"\border number\b", r"\bconfirmation\b", r"\bpackage\b",
    ],
    SupportIntent.PAYMENT: [
        r"\bpayment\b", r"\bbilled\b", r"\bcharge\b", r"\bcredit card\b",
        r"\bpaypal\b", r"\binvoice\b", r"\breceipt\b", r"\bprice\b",
    ],
    SupportIntent.WARRANTY: [
        r"\bwarranty\b", r"\bguarantee\b", r"\bdefective\b", r"\bbroken\b",
        r"\bfaulty\b", r"\bdamaged\b", r"\bdoesn.?t work\b",
    ],
    SupportIntent.ACCOUNT: [
        r"\bpassword\b", r"\blogin\b", r"\baccount\b", r"\bsign.?in\b",
        r"\bemail\b", r"\bprofile\b",
    ],
    SupportIntent.PRODUCT: [
        r"\bproduct\b", r"\bitem\b", r"\bdescription\b", r"\bspecification\b",
        r"\bmodel\b", r"\bcolor\b", r"\bsize\b",
    ],
}

SENTIMENT_PATTERNS = {
    "frustrated": [
        r"\bunacceptable\b", r"\bterrible\b", r"\bfrustrated\b", r"\banger\b",
        r"\bwaste\b", r"\bscam\b", r"\bnever again\b", r"\bhorribleb",
        r"\bthis is ridiculous\b",
    ],
    "positive": [r"\bthank\b", r"\bgreat\b", r"\bexcellent\b", r"\bwonderful\b"],
}

HIGH_COMPLEXITY_PATTERNS = [
    r"\bexception\b", r"\bspecial case\b", r"\bbut\b.{5,30}\b(also|and)\b",
    r"\b(30|45|60|90) days?\b", r"\bused\b.{3,20}\breturn\b",
    r"\bpolicy\b.{5,20}\bexception\b", r"\bwhy (is|was|were|did)\b",
]


class QueryClassifier:
    """
    Classifies a user query into intent, risk level, and complexity score.
    Uses regex keyword matching as a fast tier-0 classifier.
    """

    def classify(self, query: str) -> QueryClassification:
        q = query.lower()

        intent = self._classify_intent(q)
        risk = self._assess_risk(intent, q)
        complexity = self._estimate_complexity(q)
        sentiment = self._detect_sentiment(q)
        requires_tool = self._requires_tool(intent, q)
        requires_order_id = self._requires_order_id(intent, q)
        is_multi_intent = self._is_multi_intent(q)
        conf = self._classification_confidence(q, intent)

        log.debug(
            "classifier.result",
            intent=intent,
            risk=risk,
            complexity=round(complexity, 2),
            sentiment=sentiment,
        )

        return QueryClassification(
            intent=intent,
            risk_level=risk,
            complexity_score=complexity,
            requires_tool=requires_tool,
            requires_order_id=requires_order_id,
            is_multi_intent=is_multi_intent,
            sentiment=sentiment,
            confidence=conf,
        )

    # ── Private Methods ───────────────────────────────────────────────────────

    def _classify_intent(self, q: str) -> SupportIntent:
        scores: dict[SupportIntent, int] = {}
        for intent, patterns in INTENT_PATTERNS.items():
            score = sum(1 for p in patterns if re.search(p, q, re.IGNORECASE))
            if score:
                scores[intent] = score

        if not scores:
            return SupportIntent.GENERAL

        return max(scores, key=scores.get)  # type: ignore[arg-type]

    def _assess_risk(self, intent: SupportIntent, q: str) -> RiskLevel:
        if intent in (SupportIntent.REFUNDS, SupportIntent.PAYMENT):
            return RiskLevel.HIGH
        if intent in (SupportIntent.RETURNS, SupportIntent.WARRANTY, SupportIntent.SHIPPING):
            return RiskLevel.MEDIUM
        # Check for financial keywords even in general queries
        financial = [r"\bmoney\b", r"\bcost\b", r"\bcompensation\b", r"\bexception\b"]
        if any(re.search(p, q, re.IGNORECASE) for p in financial):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _estimate_complexity(self, q: str) -> float:
        """Score 0-1 based on heuristics."""
        score = 0.0
        # Length heuristic
        word_count = len(q.split())
        if word_count > 50:
            score += 0.3
        elif word_count > 25:
            score += 0.15

        # Complex patterns
        for p in HIGH_COMPLEXITY_PATTERNS:
            if re.search(p, q, re.IGNORECASE):
                score += 0.15

        return min(score, 1.0)

    def _detect_sentiment(self, q: str) -> str:
        for sentiment, patterns in SENTIMENT_PATTERNS.items():
            if any(re.search(p, q, re.IGNORECASE) for p in patterns):
                return sentiment
        return "neutral"

    def _requires_tool(self, intent: SupportIntent, q: str) -> bool:
        tool_intents = {SupportIntent.ORDER_STATUS, SupportIntent.REFUNDS, SupportIntent.SHIPPING}
        if intent in tool_intents:
            return True
        # Order ID pattern
        if re.search(r"\b(order|#)\s*\d{4,}\b", q, re.IGNORECASE):
            return True
        return False

    def _requires_order_id(self, intent: SupportIntent, q: str) -> bool:
        order_intents = {SupportIntent.ORDER_STATUS, SupportIntent.SHIPPING, SupportIntent.REFUNDS}
        return intent in order_intents

    def _is_multi_intent(self, q: str) -> bool:
        """Detect if query contains multiple distinct support topics."""
        matched_intents = set()
        for intent, patterns in INTENT_PATTERNS.items():
            if any(re.search(p, q, re.IGNORECASE) for p in patterns):
                matched_intents.add(intent)
        return len(matched_intents) >= 2

    def _classification_confidence(self, q: str, intent: SupportIntent) -> float:
        if intent == SupportIntent.UNKNOWN or intent == SupportIntent.GENERAL:
            return 0.4
        # Count how many patterns matched for the assigned intent
        matched = sum(
            1 for p in INTENT_PATTERNS.get(intent, [])
            if re.search(p, q, re.IGNORECASE)
        )
        return min(0.5 + matched * 0.15, 0.98)
