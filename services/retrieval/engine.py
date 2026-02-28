"""
Retrieval Engine — Embeds queries, searches pgvector, and optionally reranks.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

import numpy as np
import structlog
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.chat import CitationChunk

log = structlog.get_logger()


class RetrievalEngine:
    """
    Hybrid retrieval pipeline:
      1. Embed query via OpenAI
      2. pgvector cosine similarity search
      3. Optional cross-encoder reranking
      4. Context compression to fit token budget
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # ── Public Interface ──────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = 6,
        filters: Optional[dict] = None,
        use_reranker: bool = False,
    ) -> tuple[list[CitationChunk], float, int]:
        """
        Returns: (chunks, top_confidence, embedding_tokens)
        """
        t0 = time.perf_counter()
        embedding, embed_tokens = await self._embed(query)

        # Vector search
        chunks_raw = await self._vector_search(embedding, top_k=top_k * 2, filters=filters)

        if not chunks_raw:
            return [], 0.0, embed_tokens

        # Optional reranking
        if use_reranker and settings.ENABLE_RERANKER:
            chunks_raw = self._simple_rerank(query, chunks_raw)

        # Take top-k after reranking
        chunks_raw = chunks_raw[:top_k]

        citations = [self._to_citation(c) for c in chunks_raw]
        top_confidence = chunks_raw[0]["score"] if chunks_raw else 0.0

        latency = (time.perf_counter() - t0) * 1000
        log.info(
            "retrieval.complete",
            top_k=len(citations),
            top_score=round(top_confidence, 3),
            latency_ms=round(latency, 1),
            reranker=use_reranker,
        )

        return citations, float(top_confidence), embed_tokens

    async def embed_text(self, text: str) -> tuple[list[float], int]:
        """Public wrapper for embedding single texts (ingestion pipeline)."""
        return await self._embed(text)

    # ── Private Methods ───────────────────────────────────────────────────────

    async def _embed(self, text: str) -> tuple[list[float], int]:
        resp = await self.openai.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=text,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        vector = resp.data[0].embedding
        tokens = resp.usage.total_tokens
        return vector, tokens

    async def _vector_search(
        self,
        embedding: list[float],
        top_k: int,
        filters: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """pgvector cosine similarity search."""
        # Build optional WHERE clause
        where_clauses = []
        params: dict[str, Any] = {
            "embedding": str(embedding),
            "top_k": top_k,
        }

        if filters:
            if "policy_type" in filters:
                where_clauses.append("d.policy_type = :policy_type")
                params["policy_type"] = filters["policy_type"]
            if "region" in filters:
                where_clauses.append("d.region IN (:region, 'global')")
                params["region"] = filters["region"]

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = text(f"""
            SELECT
                c.id::text          AS chunk_id,
                c.chunk_text        AS snippet,
                c.section_title,
                c.metadata_json,
                d.title             AS document_title,
                d.policy_type,
                d.region,
                1 - (c.embedding <=> :embedding::vector) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            {where_sql}
            ORDER BY c.embedding <=> :embedding::vector
            LIMIT :top_k
        """)

        result = await self.db.execute(sql, params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    def _simple_rerank(
        self, query: str, chunks: list[dict], alpha: float = 0.4
    ) -> list[dict]:
        """
        Lightweight BM25-style term overlap reranker (no heavy cross-encoder
        dependency). Blends with vector score using alpha weighting.

        For production: replace with a cross-encoder like ms-marco-MiniLM.
        """
        query_terms = set(query.lower().split())

        def term_overlap(chunk: dict) -> float:
            chunk_terms = set(chunk["snippet"].lower().split())
            if not chunk_terms:
                return 0.0
            return len(query_terms & chunk_terms) / len(query_terms)

        for chunk in chunks:
            overlap = term_overlap(chunk)
            chunk["rerank_score"] = (1 - alpha) * chunk["score"] + alpha * overlap

        return sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)

    @staticmethod
    def compress_context(
        chunks: list[CitationChunk], token_budget: int, approx_chars_per_token: int = 4
    ) -> list[CitationChunk]:
        """
        Trim retrieved chunks to fit within a token budget.
        Drops lowest-relevance chunks first.
        """
        sorted_chunks = sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
        selected: list[CitationChunk] = []
        used_chars = 0
        char_budget = token_budget * approx_chars_per_token

        for chunk in sorted_chunks:
            snippet_length = len(chunk.snippet)
            if used_chars + snippet_length <= char_budget:
                selected.append(chunk)
                used_chars += snippet_length
            else:
                # Try a truncated version
                remaining = char_budget - used_chars
                if remaining > 200:
                    truncated = chunk.model_copy(
                        update={"snippet": chunk.snippet[:remaining] + "..."}
                    )
                    selected.append(truncated)
                break

        return selected

    def _to_citation(self, raw: dict) -> CitationChunk:
        return CitationChunk(
            chunk_id=raw["chunk_id"],
            document_title=raw["document_title"],
            section_title=raw.get("section_title"),
            snippet=raw["snippet"][:600],  # hard cap
            relevance_score=round(float(raw["score"]), 4),
            policy_type=raw.get("policy_type"),
            source_url=None,
        )

    @staticmethod
    def cache_key_for_query(query: str, filters: Optional[dict] = None) -> str:
        payload = f"{query}|{str(filters or {})}"
        return hashlib.sha256(payload.encode()).hexdigest()
