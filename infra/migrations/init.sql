-- ================================================================
-- Cost-Aware LLM Support Copilot — Database Initialization
-- ================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Documents ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           VARCHAR(512) NOT NULL,
    source_type     VARCHAR(64),
    policy_type     VARCHAR(128),
    version         VARCHAR(32) DEFAULT '1.0',
    region          VARCHAR(64) DEFAULT 'global',
    effective_date  TIMESTAMP,
    content_hash    VARCHAR(64),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── Chunks with pgvector embedding ────────────────────────────────

CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    chunk_text      TEXT NOT NULL,
    embedding       VECTOR(1536),      -- OpenAI text-embedding-3-small
    section_title   VARCHAR(256),
    token_count     INTEGER,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

-- ── Conversations ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(256),
    status          VARCHAR(32) DEFAULT 'active',
    total_cost_usd  FLOAT DEFAULT 0.0,
    total_tokens    INTEGER DEFAULT 0,
    message_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- ── Messages ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL,
    content         TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── Router Decisions ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS router_decisions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id              VARCHAR(64) NOT NULL,
    conversation_id         UUID,
    intent                  VARCHAR(64),
    risk_level              VARCHAR(16),
    retrieval_confidence    FLOAT,
    model_tier              VARCHAR(16),
    model_name              VARCHAR(128),
    top_k                   INTEGER,
    use_reranker            BOOLEAN,
    max_output_tokens       INTEGER,
    allow_tools             BOOLEAN,
    escalation_threshold    FLOAT,
    decision_reason         TEXT,
    budget_usage_pct        FLOAT,
    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_router_decisions_request_id ON router_decisions(request_id);
CREATE INDEX IF NOT EXISTS idx_router_decisions_created_at ON router_decisions(created_at);

-- ── LLM Calls ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS llm_calls (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          VARCHAR(64) NOT NULL,
    conversation_id     UUID REFERENCES conversations(id),
    provider            VARCHAR(64),
    model_name          VARCHAR(128),
    model_tier          VARCHAR(16),
    call_type           VARCHAR(32),
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    embedding_tokens    INTEGER DEFAULT 0,
    cost_usd            FLOAT DEFAULT 0.0,
    latency_ms          FLOAT,
    cache_hit           BOOLEAN DEFAULT FALSE,
    cache_type          VARCHAR(16),
    success             BOOLEAN DEFAULT TRUE,
    error_type          VARCHAR(128),
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_request_id ON llm_calls(request_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model_tier ON llm_calls(model_tier);

-- ── Tool Calls ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tool_calls (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      VARCHAR(64) NOT NULL,
    tool_name       VARCHAR(64),
    input_data      JSONB,
    output_data     JSONB,
    success         BOOLEAN DEFAULT TRUE,
    error_message   TEXT,
    latency_ms      FLOAT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── Retrieval Logs ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS retrieval_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      VARCHAR(64) NOT NULL,
    query_text      TEXT,
    top_k           INTEGER,
    chunk_ids       JSONB,
    scores          JSONB,
    reranker_used   BOOLEAN DEFAULT FALSE,
    latency_ms      FLOAT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── Cache Entries ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cache_entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cache_key       VARCHAR(256) UNIQUE NOT NULL,
    cache_type      VARCHAR(16),
    query_text      TEXT,
    response_json   JSONB,
    hit_count       INTEGER DEFAULT 0,
    cost_saved_usd  FLOAT DEFAULT 0.0,
    created_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP
);

-- ── Feedback ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS feedback (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      VARCHAR(64) NOT NULL,
    conversation_id UUID,
    rating          INTEGER CHECK (rating BETWEEN 1 AND 5),
    was_helpful     BOOLEAN,
    was_accurate    BOOLEAN,
    comment         TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── Evaluation ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eval_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_name            VARCHAR(256),
    config_snapshot     JSONB,
    total_samples       INTEGER,
    groundedness_score  FLOAT,
    factual_accuracy    FLOAT,
    retrieval_hit_rate  FLOAT,
    avg_cost_usd        FLOAT,
    avg_latency_ms      FLOAT,
    escalation_rate     FLOAT,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- ── Analytics View ─────────────────────────────────────────────────

CREATE OR REPLACE VIEW daily_cost_summary AS
SELECT
    DATE(created_at) AS date,
    model_tier,
    COUNT(*) AS call_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cost_usd) AS total_cost_usd,
    AVG(latency_ms) AS avg_latency_ms,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::FLOAT / COUNT(*) AS cache_hit_rate
FROM llm_calls
GROUP BY DATE(created_at), model_tier
ORDER BY date DESC, total_cost_usd DESC;
