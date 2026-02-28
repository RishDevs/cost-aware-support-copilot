"""
Tool Orchestrator — Simulated business tools for order lookup and refund eligibility.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()

# ── Simulated Order Database ──────────────────────────────────────────────────

_FAKE_ORDERS = {
    "ORD-10001": {
        "order_id": "ORD-10001",
        "status": "delivered",
        "delivery_date": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        "items": [{"name": "Wireless Headphones", "category": "electronics", "qty": 1, "price": 89.99}],
        "payment_amount": 89.99,
        "payment_date": (datetime.utcnow() - timedelta(days=7)).isoformat(),
        "return_window_days": 30,
        "region": "US",
    },
    "ORD-10002": {
        "order_id": "ORD-10002",
        "status": "in_transit",
        "estimated_delivery": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        "items": [{"name": "Running Shoes", "category": "apparel", "qty": 1, "price": 120.00}],
        "payment_amount": 120.00,
        "payment_date": (datetime.utcnow() - timedelta(days=4)).isoformat(),
        "return_window_days": 60,
        "region": "US",
    },
    "ORD-10003": {
        "order_id": "ORD-10003",
        "status": "delivered",
        "delivery_date": (datetime.utcnow() - timedelta(days=45)).isoformat(),
        "items": [{"name": "Coffee Maker", "category": "appliances", "qty": 1, "price": 149.99}],
        "payment_amount": 149.99,
        "payment_date": (datetime.utcnow() - timedelta(days=50)).isoformat(),
        "return_window_days": 30,
        "region": "US",
    },
}

# ── Return Eligibility Rules ──────────────────────────────────────────────────

RETURN_RULES = {
    "electronics":  {"window_days": 30,  "condition": "unopened_or_defective"},
    "apparel":      {"window_days": 60,  "condition": "unworn"},
    "appliances":   {"window_days": 30,  "condition": "unused"},
    "perishable":   {"window_days": 0,   "condition": "non_returnable"},
    "software":     {"window_days": 0,   "condition": "non_returnable"},
    "default":      {"window_days": 30,  "condition": "any"},
}


class ToolOrchestrator:
    """
    Validates and executes safe business tool calls.
    """

    ALLOWED_TOOLS = {"order_lookup", "refund_eligibility", "ticket_history"}

    async def dispatch(self, tool_name: str, inputs: dict) -> dict[str, Any]:
        if tool_name not in self.ALLOWED_TOOLS:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        t0 = time.perf_counter()
        if tool_name == "order_lookup":
            result = await self._order_lookup(inputs)
        elif tool_name == "refund_eligibility":
            result = await self._refund_eligibility(inputs)
        elif tool_name == "ticket_history":
            result = await self._ticket_history(inputs)
        else:
            result = {"success": False, "error": "Unhandled tool"}

        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return result

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def _order_lookup(self, inputs: dict) -> dict:
        order_id = inputs.get("order_id", "").upper()
        log.info("tool.order_lookup", order_id=order_id)

        if not order_id:
            return {
                "success": False,
                "error": "order_id is required",
                "prompt": "Could you please share your order number? It starts with ORD-",
            }

        order = _FAKE_ORDERS.get(order_id)
        if not order:
            return {
                "success": False,
                "error": "not_found",
                "summary": f"No order found with ID {order_id}. Please check your order number.",
            }

        return {
            "success": True,
            "tool": "order_lookup",
            "order_id": order_id,
            "status": order["status"],
            "items": order["items"],
            "payment_amount": order["payment_amount"],
            "delivery_date": order.get("delivery_date"),
            "estimated_delivery": order.get("estimated_delivery"),
            "return_window_days": order["return_window_days"],
            "region": order["region"],
            "summary": self._format_order_summary(order),
        }

    async def _refund_eligibility(self, inputs: dict) -> dict:
        order_id = inputs.get("order_id", "").upper()
        condition = inputs.get("condition", "good")  # good | damaged | used | unopened
        log.info("tool.refund_eligibility", order_id=order_id, condition=condition)

        order = _FAKE_ORDERS.get(order_id)
        if not order:
            return {"success": False, "error": "order_not_found"}

        # Check against items
        results = []
        for item in order["items"]:
            category = item.get("category", "default")
            rule = RETURN_RULES.get(category, RETURN_RULES["default"])
            window = rule["window_days"]

            delivered = order.get("delivery_date")
            days_since = 0
            if delivered:
                delta = datetime.utcnow() - datetime.fromisoformat(delivered)
                days_since = delta.days

            eligible = window > 0 and days_since <= window
            if condition in ("used", "opened") and rule["condition"] in ("unopened_or_defective", "unworn"):
                eligible = False

            results.append({
                "item": item["name"],
                "eligible": eligible,
                "reason": (
                    f"Within {window}-day return window ({days_since} days elapsed)."
                    if eligible
                    else f"Outside {window}-day return window ({days_since} days elapsed) or condition not met."
                ),
                "policy_reference": f"returns-policy/{category}",
            })

        all_eligible = all(r["eligible"] for r in results)
        return {
            "success": True,
            "tool": "refund_eligibility",
            "order_id": order_id,
            "overall_eligible": all_eligible,
            "items": results,
            "summary": (
                "All items appear eligible for return. Our team will review and process your request."
                if all_eligible
                else "Some or all items may not be eligible for return. Please see details below."
            ),
        }

    async def _ticket_history(self, inputs: dict) -> dict:
        # Simulated — returns last few interactions
        return {
            "success": True,
            "tool": "ticket_history",
            "recent_tickets": [
                {"id": "T-9001", "subject": "Delivery delay inquiry", "status": "resolved", "days_ago": 14},
            ],
            "summary": "Customer has 1 previous support interaction in the last 30 days.",
        }

    @staticmethod
    def _format_order_summary(order: dict) -> str:
        items_str = ", ".join(f"{i['name']} (x{i['qty']})" for i in order["items"])
        status_map = {
            "delivered": "delivered",
            "in_transit": "currently in transit",
            "processing": "being processed",
            "cancelled": "cancelled",
        }
        status = status_map.get(order["status"], order["status"])
        date = order.get("delivery_date") or order.get("estimated_delivery", "unknown")[:10]
        return (
            f"Order {order['order_id']} ({items_str}) — "
            f"Status: {status}. "
            f"{'Delivered on' if order['status'] == 'delivered' else 'Estimated delivery'}: {date[:10]}. "
            f"Total: ${order['payment_amount']:.2f}."
        )
