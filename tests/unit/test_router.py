"""Unit tests for the cost-aware router."""
import pytest

from app.schemas.chat import (
    ModelTier,
    QueryClassification,
    RiskLevel,
    SLAMode,
    SupportIntent,
)
from services.router.classifier import QueryClassifier
from services.router.router import CostAwareRouter, get_confidence_band


# ── Classifier Tests ──────────────────────────────────────────────────────────

class TestQueryClassifier:
    clf = QueryClassifier()

    def test_returns_intent(self):
        r = self.clf.classify("I want to return my shoes")
        assert r.intent == SupportIntent.RETURNS

    def test_refund_intent_high_risk(self):
        r = self.clf.classify("I need a refund for my order")
        assert r.intent == SupportIntent.REFUNDS
        assert r.risk_level == RiskLevel.HIGH

    def test_shipping_intent(self):
        r = self.clf.classify("My package is delayed and tracking shows no updates")
        assert r.intent == SupportIntent.SHIPPING

    def test_payment_intent(self):
        r = self.clf.classify("I was charged twice for the same order")
        assert r.intent in (SupportIntent.PAYMENT, SupportIntent.REFUNDS)
        assert r.risk_level == RiskLevel.HIGH

    def test_frustrated_sentiment(self):
        r = self.clf.classify("This is unacceptable! I never got my package!")
        assert r.sentiment == "frustrated"

    def test_multi_intent(self):
        r = self.clf.classify("I want a refund and also need to know about returning items")
        assert r.is_multi_intent is True

    def test_complexity_long_query(self):
        long_q = "I purchased a laptop 20 days ago and it was working fine initially but then it started showing display issues after 15 days. I opened it to check if the RAM was properly seated. But now the display is completely broken. Can I return it?"
        r = self.clf.classify(long_q)
        assert r.complexity_score > 0.3

    def test_simple_faq_low_complexity(self):
        r = self.clf.classify("What is your return window?")
        assert r.complexity_score < 0.4


# ── Router Tests ──────────────────────────────────────────────────────────────

class TestCostAwareRouter:
    router = CostAwareRouter()

    def _classify(self, intent=SupportIntent.RETURNS, risk=RiskLevel.LOW, complexity=0.2,
                  multi=False, sentiment="neutral", requires_tool=False):
        return QueryClassification(
            intent=intent, risk_level=risk, complexity_score=complexity,
            is_multi_intent=multi, sentiment=sentiment, requires_tool=requires_tool,
            confidence=0.85
        )

    # ── Tier selection

    def test_tier_a_simple_faq(self):
        clf = self._classify()
        d = self.router.route(clf, retrieval_confidence=0.88, budget_usage_pct=0.1)
        assert d.model_tier == ModelTier.CHEAP

    def test_tier_c_high_risk_refund(self):
        clf = self._classify(intent=SupportIntent.REFUNDS, risk=RiskLevel.HIGH)
        d = self.router.route(clf, retrieval_confidence=0.8, budget_usage_pct=0.2)
        assert d.model_tier == ModelTier.PREMIUM

    def test_tier_c_payment_risk(self):
        clf = self._classify(intent=SupportIntent.PAYMENT, risk=RiskLevel.HIGH)
        d = self.router.route(clf, retrieval_confidence=0.5, budget_usage_pct=0.3)
        assert d.model_tier == ModelTier.PREMIUM

    def test_tier_c_low_retrieval_confidence(self):
        clf = self._classify(intent=SupportIntent.GENERAL, risk=RiskLevel.LOW)
        d = self.router.route(clf, retrieval_confidence=0.20, budget_usage_pct=0.1)
        assert d.model_tier == ModelTier.PREMIUM

    def test_tier_c_quality_sla_mode(self):
        clf = self._classify()
        d = self.router.route(clf, retrieval_confidence=0.9, budget_usage_pct=0.1, sla_mode=SLAMode.QUALITY)
        assert d.model_tier == ModelTier.PREMIUM

    def test_emergency_budget_forces_cheap(self):
        clf = self._classify(intent=SupportIntent.GENERAL)
        d = self.router.route(clf, retrieval_confidence=0.9, budget_usage_pct=0.96)
        assert d.model_tier == ModelTier.CHEAP

    def test_budget_pressure_low_risk_cheap(self):
        clf = self._classify(intent=SupportIntent.GENERAL, risk=RiskLevel.LOW)
        d = self.router.route(clf, retrieval_confidence=0.85, budget_usage_pct=0.85)
        assert d.model_tier == ModelTier.CHEAP

    def test_fast_sla_mode_reduces_max_tokens(self):
        clf = self._classify()
        d = self.router.route(clf, retrieval_confidence=0.9, budget_usage_pct=0.1, sla_mode=SLAMode.FAST)
        assert d.max_output_tokens <= 180

    # ── Top-K

    def test_top_k_cheap_is_small(self):
        clf = self._classify()
        d = self.router.route(clf, retrieval_confidence=0.9, budget_usage_pct=0.1)
        assert d.top_k == 3

    def test_top_k_premium_multi_intent(self):
        clf = self._classify(intent=SupportIntent.REFUNDS, risk=RiskLevel.HIGH, multi=True)
        d = self.router.route(clf, retrieval_confidence=0.5, budget_usage_pct=0.1)
        assert d.top_k == 8

    # ── Reranker

    def test_no_reranker_for_cheap_tier(self):
        clf = self._classify()
        d = self.router.route(clf, retrieval_confidence=0.9, budget_usage_pct=0.1)
        assert d.use_reranker is False

    def test_reranker_for_low_confidence(self):
        clf = self._classify(risk=RiskLevel.MEDIUM)
        d = self.router.route(clf, retrieval_confidence=0.45, budget_usage_pct=0.1)
        assert d.use_reranker is True

    # ── Tools

    def test_tools_allowed_when_required(self):
        clf = self._classify(intent=SupportIntent.ORDER_STATUS, requires_tool=True)
        d = self.router.route(clf, retrieval_confidence=0.8, budget_usage_pct=0.2)
        assert d.allow_tools is True

    def test_tools_disabled_in_emergency_budget(self):
        clf = self._classify(requires_tool=True)
        d = self.router.route(clf, retrieval_confidence=0.8, budget_usage_pct=0.96)
        assert d.allow_tools is False

    # ── Escalation threshold

    def test_low_escalation_threshold_high_risk(self):
        clf = self._classify(risk=RiskLevel.HIGH, intent=SupportIntent.REFUNDS)
        d = self.router.route(clf, retrieval_confidence=0.8, budget_usage_pct=0.2)
        assert d.escalation_threshold <= 0.35


# ── Confidence Band Tests ─────────────────────────────────────────────────────

def test_confidence_band_high():
    from app.schemas.chat import ConfidenceBand
    assert get_confidence_band(0.80) == ConfidenceBand.HIGH

def test_confidence_band_medium():
    from app.schemas.chat import ConfidenceBand
    assert get_confidence_band(0.55) == ConfidenceBand.MEDIUM

def test_confidence_band_low():
    from app.schemas.chat import ConfidenceBand
    assert get_confidence_band(0.30) == ConfidenceBand.LOW
