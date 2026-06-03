"""OpenAI embedding generation for RAG (text-embedding-3-small, 1536-dim)."""

from __future__ import annotations

import logging
import os
from typing import Sequence

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIM = 1536
_BATCH = 100


class EmbeddingService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI()
        self.dim = DIM

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            batch = list(texts[i : i + _BATCH])
            resp = await self._client.embeddings.create(
                model=os.getenv("OPENAI_EMBEDDING_MODEL", MODEL),
                input=batch,
            )
            for item in sorted(resp.data, key=lambda x: x.index):
                out.append(list(item.embedding))
        return out

    async def embed_query(self, text: str) -> list[float]:
        emb = await self.embed_batch([text])
        return emb[0] if emb else [0.0] * DIM
