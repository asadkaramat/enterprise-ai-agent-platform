import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.metrics import embedding_duration_seconds

logger = logging.getLogger(__name__)


class LongTermMemory:
    def __init__(self):
        self.client = QdrantClient(url=settings.QDRANT_URL)
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self.vector_size = 384  # all-MiniLM-L6-v2 output dimension

    def _collection_name(self, tenant_id: str) -> str:
        # Qdrant collection names must not contain dashes
        return f"memory_{tenant_id.replace('-', '')}"

    def _embed(self, text: str) -> List[float]:
        start = time.perf_counter()
        vector = self.model.encode(text).tolist()
        embedding_duration_seconds.observe(time.perf_counter() - start)
        return vector

    async def ensure_collection(self, tenant_id: str) -> None:
        collection_name = self._collection_name(tenant_id)
        loop = asyncio.get_event_loop()

        def _create():
            try:
                self.client.get_collection(collection_name)
            except Exception:
                logger.info("Creating Qdrant collection: %s", collection_name)
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size, distance=Distance.COSINE
                    ),
                )

        await loop.run_in_executor(None, _create)

    async def store_memory(
        self,
        tenant_id: str,
        session_id: str,
        agent_id: str,
        content: str,
        metadata: dict = {},
    ) -> None:
        await self.ensure_collection(tenant_id)
        collection_name = self._collection_name(tenant_id)
        loop = asyncio.get_event_loop()

        def _store():
            embedding = self._embed(content)
            # Deterministic ID: same content in same session upserts rather than duplicates
            point_id = str(
                uuid.UUID(
                    hashlib.md5(f"{session_id}:{content}".encode()).hexdigest()
                )
            )
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "session_id": session_id,
                            "agent_id": agent_id,
                            "tenant_id": tenant_id,
                            "content": content,
                            "timestamp": datetime.utcnow().isoformat(),
                            **metadata,
                        },
                    )
                ],
            )
            logger.debug(
                "Stored long-term memory point=%s tenant=%s session=%s",
                point_id,
                tenant_id,
                session_id,
            )

        await loop.run_in_executor(None, _store)

    async def retrieve_similar(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.4,
    ) -> List[dict]:
        await self.ensure_collection(tenant_id)
        collection_name = self._collection_name(tenant_id)
        loop = asyncio.get_event_loop()

        def _search():
            embedding = self._embed(query)
            results = self.client.search(
                collection_name=collection_name,
                query_vector=embedding,
                limit=top_k,
                score_threshold=score_threshold,
            )
            return [
                {
                    "content": r.payload.get("content", ""),
                    "score": r.score,
                    "session_id": r.payload.get("session_id", ""),
                    "timestamp": r.payload.get("timestamp", ""),
                }
                for r in results
            ]

        try:
            return await loop.run_in_executor(None, _search)
        except Exception as exc:
            logger.error(
                "Qdrant search failed for tenant=%s: %s", tenant_id, exc, exc_info=True
            )
            return []

    async def delete_session_memories(
        self, tenant_id: str, session_id: str
    ) -> None:
        await self.ensure_collection(tenant_id)
        collection_name = self._collection_name(tenant_id)
        loop = asyncio.get_event_loop()

        def _delete():
            self.client.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="session_id", match=MatchValue(value=session_id)
                        )
                    ]
                ),
            )
            logger.info(
                "Deleted long-term memories for tenant=%s session=%s",
                tenant_id,
                session_id,
            )

        try:
            await loop.run_in_executor(None, _delete)
        except Exception as exc:
            logger.error(
                "Qdrant delete failed for tenant=%s session=%s: %s",
                tenant_id,
                session_id,
                exc,
                exc_info=True,
            )
