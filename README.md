<div align="center">

# 🧠 Cost-Aware LLM Support Copilot

**A production-grade AI customer support assistant that dynamically routes queries to the cheapest model capable of answering accurately.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat-square&logo=openai&logoColor=white)](https://openai.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

<br/>

> Unlike a basic chatbot, this system makes **dynamic decisions** about which model to use, how much context to retrieve, whether to call a tool, and when to escalate to a human — all while tracking cost, latency, and quality in real time.

</div>

---

## 📸 Preview

| Support Chat | Analytics Dashboard |
|---|---|
| ![Chat](https://placehold.co/540x340/111113/6366f1?text=Chat+View&font=inter) | ![Analytics](https://placehold.co/540x340/111113/22c55e?text=Analytics+View&font=inter) |

<sub>Open `apps/web/index.html` to see the real UI — no server required for the demo.</sub>

---

## ✨ What Sets This Apart

Most LLM demos optimize only for output quality. This system explicitly balances **4 competing objectives**:

| Objective | Mechanism |
|-----------|-----------|
| **💰 Cost** | 3-tier dynamic routing (GPT-3.5 → GPT-4o-mini → GPT-4o) |
| **🎯 Quality** | RAG retrieval + confidence estimation + optional reranking |
| **⚡ Latency** | Exact + retrieval caching, adaptive top-k |
| **🔒 Safety** | PII redaction, prompt injection detection, output validation |

---

## 🏗️ Architecture

```
┌─────────────┐      ┌──────────────────────────────────────────────────────┐
│  Web UI     │─────▶│                    FastAPI API                        │
│  (Browser)  │◀─────│  /chat  /analytics  /documents  /eval  /health       │
└─────────────┘      └─────────────────────┬────────────────────────────────┘
                                           │
               ┌───────────────────────────┼──────────────────────────────┐
               │                           │                              │
    ┌──────────▼──────────┐   ┌────────────▼──────────┐   ┌─────────────▼──────┐
    │  Query Classifier   │   │  Cost-Aware Router     │   │  Retrieval Engine  │
    │  • 9 intent types   │   │  • Tier A/B/C select   │   │  pgvector search   │
    │  • Risk assessment  │   │  • Budget awareness    │   │  BM25 reranker     │
    │  • Complexity score │   │  • SLA mode support    │   │  Context compress  │
    │  • Sentiment detect │   └────────────────────────┘   └────────────────────┘
    └─────────────────────┘
               │
    ┌──────────▼──────────┐   ┌────────────────────────┐   ┌────────────────────┐
    │  Answer Generator   │   │  Tool Orchestrator     │   │  Guardrails        │
    │  • Prompt builder   │   │  • Order lookup        │   │  • PII redaction   │
    │  • LLM call + retry │   │  • Refund eligibility  │   │  • Injection block │
    │  • Token cost track │   │  • Ticket history      │   │  • Output validate │
    └─────────────────────┘   └────────────────────────┘   └────────────────────┘

    Storage:  PostgreSQL + pgvector (documents, chunks, logs)
              Redis (exact cache, retrieval cache, daily budget)
```

---

## 📁 Project Structure

```
cost-aware-support-copilot/
├── apps/
│   ├── api/                        # FastAPI backend
│   │   ├── main.py                 # App entry point & lifespan
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── api/v1/             # Endpoints: chat, docs, analytics, eval, health
│   │       ├── core/               # Config (Pydantic Settings), logging
│   │       ├── db/                 # Async SQLAlchemy session
│   │       ├── models/             # ORM: 11 tables
│   │       ├── schemas/            # Pydantic schemas (request/response)
│   │       └── services/           # CopilotService — main orchestrator
│   └── web/                        # Frontend (zero-dependency SPA)
│       ├── index.html              # 4-view app: Chat, Analytics, Evaluation, KB
│       ├── style.css               # Premium dark-mode design system
│       └── app.js                  # All app logic + offline demo simulation
│
├── services/                       # Reusable backend services
│   ├── router/
│   │   ├── classifier.py           # Intent / risk / sentiment classifier
│   │   └── router.py               # ⭐ Cost-aware routing engine
│   ├── retrieval/
│   │   ├── engine.py               # pgvector search, reranking, compression
│   │   └── generator.py            # Prompt builder, LLM caller, confidence
│   ├── ingestion/
│   │   └── pipeline.py             # Doc → chunk → embed → pgvector
│   ├── guardrails/
│   │   └── guardrails.py           # PII, injection, unsupported actions
│   └── analytics/
│       ├── budget.py               # Redis budget tracker + cache manager
│       └── tools.py                # Simulated order / refund tools
│
├── data/
│   ├── raw/                        # Policy docs (Markdown)
│   │   ├── returns_policy.md
│   │   ├── refund_policy.md
│   │   └── shipping_policy.md
│   └── eval/
│       └── gold_eval_set.json      # 15 labeled evaluation queries
│
├── infra/
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   └── nginx.conf
│   └── migrations/
│       └── init.sql                # Full schema + pgvector HNSW index
│
├── tests/
│   ├── unit/
│   │   ├── test_router.py          # 16 router tests
│   │   └── test_guardrails.py      # 10 guardrail tests
│   └── integration/
│
├── docker-compose.yml              # Full stack: Postgres, Redis, API, Nginx
├── .env.example                    # All env var documentation
└── README.md
```

---

## 🔀 Cost-Aware Routing Logic

The router (`services/router/router.py`) selects the cheapest viable model tier per request using **7 signals**:

```
Signal                              → Decision
─────────────────────────────────────────────────────────────────
High-risk intent (refund/payment)   → Tier C (GPT-4o)
Retrieval confidence < 0.40         → Tier C (avoid hallucination)
Quality SLA mode                    → Tier C (explicit override)
Budget ≥ 95% (emergency)            → Tier A (GPT-3.5-turbo)
High confidence + low complexity    → Tier A (simple FAQ)
Budget ≥ 80% + low risk            → Tier A (budget pressure)
Medium risk (returns/shipping)      → Tier B (GPT-4o-mini)
Default                             → Tier B
```

### Model Tiers

| Tier | Model | Top-K | Max Tokens | Use Case |
|------|-------|-------|------------|----------|
| **A — Cheap** | `gpt-3.5-turbo` | 3 | 200 | Simple FAQs, high-confidence answers |
| **B — Balanced** | `gpt-4o-mini` | 4–6 | 400 | Returns, shipping, moderate complexity |
| **C — Premium** | `gpt-4o` | 6–8 | 700 | Refunds, disputes, multi-intent |

---

## 🔁 Request Pipeline (13 Steps)

```
1.  Input guardrail check (injection / unsupported action)
2.  Query classification (intent, risk, complexity, sentiment)
3.  Budget state lookup (Redis)
4.  Exact cache check (Redis SHA-256 key)
5.  Initial vector retrieval (pgvector cosine similarity)
6.  Cost-aware routing decision
7.  Refined retrieval (adjusted top-k + optional reranker)
8.  Context compression (fit to token budget)
9.  Tool calls (order lookup / refund eligibility)
10. Prompt build + LLM generation (with exponential retry)
11. Output guardrail validation
12. Confidence scoring + escalation decision
13. Budget record + cache store
```

---

## 🚀 Quick Start

### Option 1 — Browser Demo (No Setup)

```bash
open apps/web/index.html
```

The frontend runs in **simulation mode** when the API is offline — perfect for demoing the UI.

### Option 2 — Full Stack with Docker

```bash
# 1. Clone
git clone https://github.com/RishDevs/cost-aware-support-copilot.git
cd cost-aware-support-copilot

# 2. Configure
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (required)

# 3. Launch
docker compose up --build

# UI  → http://localhost:3000
# API → http://localhost:8000/docs
```

### Option 3 — Local Dev (No Docker)

```bash
# Backend
cd apps/api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend — just open in browser
open ../../apps/web/index.html
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and set the following:

```env
# Required
OPENAI_API_KEY=sk-...

# Model Tiers (defaults shown)
TIER_A_MODEL=gpt-3.5-turbo
TIER_B_MODEL=gpt-4o-mini
TIER_C_MODEL=gpt-4o

# Budget Controls
DAILY_BUDGET_USD=50.00
EMERGENCY_CHEAP_MODE_PCT=0.95   # Force Tier A above 95% usage

# Router Thresholds
CONFIDENCE_HIGH_THRESHOLD=0.75
CONFIDENCE_LOW_THRESHOLD=0.40
ESCALATION_THRESHOLD=0.35

# Feature Flags
ENABLE_CACHING=true
ENABLE_RERANKER=true
ENABLE_TOOLS=true
ENABLE_GUARDRAILS=true
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/chat` | Send a support message → grounded answer |
| `POST` | `/api/v1/chat/feedback` | Submit thumbs-up/down feedback |
| `POST` | `/api/v1/documents/ingest` | Ingest a policy document |
| `GET`  | `/api/v1/documents` | List indexed documents |
| `GET`  | `/api/v1/analytics/budget` | Daily budget status |
| `GET`  | `/api/v1/analytics/cost-breakdown` | Cost by model tier (7 days) |
| `GET`  | `/api/v1/analytics/latency` | P50/P95 latency by tier |
| `GET`  | `/api/v1/analytics/escalation-rate` | Escalation rate by intent |
| `POST` | `/api/v1/eval/run` | Trigger an evaluation run |
| `GET`  | `/api/v1/eval/runs` | Evaluation run history |
| `GET`  | `/api/v1/health` | Health check |

### Chat Request

```json
POST /api/v1/chat
{
  "message": "Can I return a used laptop after 35 days?",
  "conversation_id": null,
  "sla_mode": "balanced",
  "debug": true
}
```

### Chat Response

```json
{
  "answer": "Electronics must be returned within 30 days...",
  "citations": [{ "document_title": "Returns Policy", "relevance_score": 0.94, "snippet": "..." }],
  "confidence": 0.87,
  "confidence_band": "high",
  "needs_human": false,
  "model_used": "gpt-4o-mini",
  "model_tier": "balanced",
  "latency_ms": 1120,
  "token_usage": { "input_tokens": 320, "output_tokens": 180, "estimated_cost_usd": 0.000045 },
  "cache_hit": false,
  "debug": { "classification": {}, "router_decision": {}, "retrieved_chunks": [] }
}
```

---

## 🎬 Demo Scenarios

| Query | Expected Tier | Why |
|-------|--------------|-----|
| `"What's the return window for unopened electronics?"` | **A — Cheap** | Simple FAQ, high retrieval confidence |
| `"I was charged twice on order ORD-10001"` | **C — Premium** | Payment risk + tool call |
| `"My package says delivered but I never got it"` | **B — Balanced** | Shipping — medium risk |
| `"Can you make an exception after 90 days?"` | **C + Escalate** | Edge case, low retrieval confidence |
| `"What is your holiday return policy?"` | **A — Cheap** | Simple FAQ |

---

## 🧪 Tests

```bash
cd apps/api
pip install -r requirements.txt
pytest tests/ -v

# 26 tests:
#  ✅ 16 router tests (tier selection, budgets, SLA modes, tools)
#  ✅ 10 guardrail tests (PII, injection, unsupported actions)
```

---

## 📊 Observability

Every request emits a structured log with:

- Intent classification + reason
- Router decision + tier + reason
- Retrieved chunks (IDs + scores)
- Model used + token counts + cost (USD)
- Latency breakdown
- Cache hit/miss
- Confidence score + escalation flag

The Analytics dashboard visualises:
- Model tier distribution
- Cost breakdown by model (7-day)
- P50/P95 latency by tier
- Escalation rate by intent

---

## 🗺️ Roadmap

- [ ] Cross-encoder reranker (ms-marco-MiniLM)
- [ ] Semantic caching (cosine similarity on cached query embeddings)
- [ ] Langfuse tracing integration
- [ ] LLM-based query classifier upgrade
- [ ] A/B experiment framework (routing ON vs OFF)
- [ ] Policy versioning support
- [ ] Human feedback learning loop
- [ ] Synthetic ticket generator for larger eval datasets

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.11, SQLAlchemy (async), Pydantic v2 |
| Database | PostgreSQL 16 + pgvector (HNSW index) |
| Cache | Redis 7 |
| LLM | OpenAI GPT-3.5-turbo / GPT-4o-mini / GPT-4o |
| Embeddings | OpenAI text-embedding-3-small |
| Logging | structlog (JSON) |
| Frontend | Vanilla HTML/CSS/JS (zero dependencies) |
| Container | Docker Compose + Nginx |

---

## 📄 License

MIT © 2026 [RishDevs](https://github.com/RishDevs)
