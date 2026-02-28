"""
Guardrails — PII redaction, unsupported action detection, and prompt injection mitigation.
"""
from __future__ import annotations

import re

import structlog

log = structlog.get_logger()

# ── PII Detection Patterns ────────────────────────────────────────────────────

PII_PATTERNS = {
    "email":       (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[EMAIL]"),
    "phone_us":    (r"\b(\+1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b", "[PHONE]"),
    "ssn":         (r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", "[SSN]"),
    "credit_card": (r"\b(?:\d[ -]?){13,16}\b", "[CARD]"),
    "ip_address":  (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]"),
}

# ── Unsupported Action Phrases ────────────────────────────────────────────────

UNSUPPORTED_ACTIONS = [
    r"\bdelete my account\b",
    r"\bissue (a )?refund\b",
    r"\bprocess (the )?refund\b",
    r"\bcancel (my )?order\b",       # Copilot can recommend but not execute
    r"\bchange (my )?password\b",
    r"\bmodify (my )?order\b",
    r"\bupdate (my )?address\b",
]

UNSUPPORTED_RESPONSE_TEMPLATE = (
    "I understand your concern, but I'm not able to {action} directly. "
    "Please contact our support team at support@example.com or call 1-800-SUPPORT, "
    "and they'll be happy to help you with that right away."
)

# ── Prompt Injection Patterns ─────────────────────────────────────────────────

INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"disregard (your|the) (system )?prompt",
    r"you are now",
    r"pretend (that )?you",
    r"act as (a|an)",
    r"jailbreak",
    r"DAN mode",
]


class GuardrailService:
    """
    Runs safety checks on both input queries and output answers.
    """

    # ── Input Guards ──────────────────────────────────────────────────────────

    def check_input(self, query: str) -> dict:
        """
        Returns:
            {
                "blocked": bool,
                "reason": str | None,
                "sanitized_query": str,
            }
        """
        result = {
            "blocked": False,
            "reason": None,
            "sanitized_query": query,
        }

        # Prompt injection check
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                log.warning("guardrail.prompt_injection", pattern=pattern)
                result["blocked"] = True
                result["reason"] = "prompt_injection_detected"
                return result

        # PII redaction in log-safe copy (don't block; just redact for logging)
        result["sanitized_query"] = self.redact_pii(query)

        return result

    def check_for_unsupported_action(self, query: str) -> str | None:
        """Returns a canned response if the query asks for an unsupported action."""
        for pattern in UNSUPPORTED_ACTIONS:
            m = re.search(pattern, query, re.IGNORECASE)
            if m:
                action_phrase = m.group(0).replace("please", "").strip()
                log.info("guardrail.unsupported_action", action=action_phrase)
                return UNSUPPORTED_RESPONSE_TEMPLATE.format(action=action_phrase)
        return None

    # ── Output Guards ─────────────────────────────────────────────────────────

    def validate_output(self, answer: str) -> dict:
        """
        Validates LLM output for safety:
          - no harmful compensation promises
          - no claimed capabilities the system doesn't have
        """
        issues = []

        # Dangerous compensation language
        dangerous = [
            r"\bI will (refund|credit|compensate)\b",
            r"\bI can cancel\b",
            r"\bI'll (issue|process|send)\b",
        ]
        for p in dangerous:
            if re.search(p, answer, re.IGNORECASE):
                issues.append(f"dangerous_commitment: {p}")
                log.warning("guardrail.output_violation", pattern=p)

        return {
            "safe": len(issues) == 0,
            "issues": issues,
            "redacted_answer": self.redact_pii(answer),
        }

    # ── PII Redaction ─────────────────────────────────────────────────────────

    @staticmethod
    def redact_pii(text: str) -> str:
        """Replace PII patterns with placeholder tokens."""
        for name, (pattern, placeholder) in PII_PATTERNS.items():
            text = re.sub(pattern, placeholder, text)
        return text
