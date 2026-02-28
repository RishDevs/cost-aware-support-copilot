"""
Document Ingestion Pipeline — chunks, embeds, and stores documents.
"""
from __future__ import annotations

import hashlib
import textwrap
import uuid
from typing import Optional

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.orm import Chunk, Document

log = structlog.get_logger()


class IngestionPipeline:
    """
    Transforms raw text documents into retrievable chunks stored in pgvector.

    Pipeline: text → clean → chunk → embed → store
    """

    CHUNK_SIZE = 600        # tokens (approx chars / 4)
    CHUNK_OVERLAP = 100     # tokens overlap between adjacent chunks
    CHARS_PER_TOKEN = 4

    def __init__(self, db: AsyncSession):
        self.db = db
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def ingest(
        self,
        title: str,
        text: str,
        policy_type: str,
        region: str = "global",
        version: str = "1.0",
        source_type: str = "markdown",
        effective_date=None,
    ) -> dict:
        """Full end-to-end ingestion of a single document."""
        log.info("ingestion.start", title=title, policy_type=policy_type)

        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        text_clean = self._clean_text(text)
        chunks_text = self._chunk_text(text_clean)

        # Upsert document record
        doc = Document(
            id=uuid.uuid4(),
            title=title,
            source_type=source_type,
            policy_type=policy_type,
            version=version,
            region=region,
            effective_date=effective_date,
            content_hash=content_hash,
        )
        self.db.add(doc)
        await self.db.flush()

        # Embed and store each chunk
        embedded_count = 0
        for idx, chunk_text in enumerate(chunks_text):
            section_title = self._extract_section_title(chunk_text)
            embedding, _ = await self._embed(chunk_text)
            token_count = len(chunk_text) // self.CHARS_PER_TOKEN

            chunk = Chunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=idx,
                chunk_text=chunk_text,
                section_title=section_title,
                token_count=token_count,
                metadata_json={
                    "policy_type": policy_type,
                    "region": region,
                    "version": version,
                },
            )
            # pgvector: set embedding as a column update after flush
            self.db.add(chunk)
            await self.db.flush()

            # Update embedding via raw SQL (pgvector column)
            from sqlalchemy import text
            await self.db.execute(
                text("UPDATE chunks SET embedding = :emb WHERE id = :id"),
                {"emb": str(embedding), "id": str(chunk.id)},
            )
            embedded_count += 1

        await self.db.commit()
        log.info(
            "ingestion.complete",
            title=title,
            chunk_count=embedded_count,
            doc_id=str(doc.id),
        )

        return {
            "document_id": str(doc.id),
            "title": title,
            "chunk_count": embedded_count,
            "status": "success",
        }

    # ── Private Methods ───────────────────────────────────────────────────────

    def _clean_text(self, text: str) -> str:
        """Remove boilerplate, normalize whitespace."""
        import re
        # Remove HTML tags if any
        text = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping chunks. Prefers splitting on paragraph
        boundaries; falls back to character sliding window.
        """
        max_chars = self.CHUNK_SIZE * self.CHARS_PER_TOKEN
        overlap_chars = self.CHUNK_OVERLAP * self.CHARS_PER_TOKEN

        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) + 2 <= max_chars:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(current)
                # Start new chunk with overlap from previous
                overlap_text = current[-overlap_chars:] if current else ""
                current = (overlap_text + "\n\n" + para).strip()

        if current:
            chunks.append(current)

        return [c for c in chunks if len(c) > 50]  # filter trivially small chunks

    def _extract_section_title(self, chunk_text: str) -> Optional[str]:
        """Try to extract the first heading from a chunk."""
        import re
        m = re.search(r"^(#{1,3})\s+(.+)", chunk_text, re.MULTILINE)
        return m.group(2).strip() if m else None

    async def _embed(self, text: str) -> tuple[list[float], int]:
        resp = await self.openai.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=text[:8000],  # safety trim
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        return resp.data[0].embedding, resp.usage.total_tokens
