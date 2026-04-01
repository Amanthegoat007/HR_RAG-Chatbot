import asyncio
import json
import os
import sys

os.environ.setdefault("JWT_SECRET", "test_secret_key_at_least_256_bits_long_for_testing")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("EMBEDDING_SVC_URL", "http://localhost:8004")
os.environ.setdefault("RERANKER_SVC_URL", "http://localhost:8005")
os.environ.setdefault("LLM_SERVER_URL", "http://localhost:8080")
os.environ.setdefault("QDRANT_COLLECTION", "hr_documents")

sys.path.insert(0, "/home/ubuntu/hr-rag-chatbot/services/rag-pipeline")


class FakeRedis:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, name, time, value):
        self.store[name] = value.encode("utf-8") if isinstance(value, str) else value

    async def scan(self, cursor=0, match=None, count=100):
        prefix = (match or "").rstrip("*")
        keys = [key for key in self.store if key.startswith(prefix)]
        return 0, keys


def test_semantic_cache_is_scoped_by_generation_snapshot():
    from app.cache import SemanticCache

    async def scenario():
        redis_client = FakeRedis()
        cache = SemanticCache(redis_client=redis_client, similarity_threshold=0.8, ttl_seconds=60)
        vector = [1.0, 0.0]

        await cache.set(
            query_embedding=vector,
            answer="cached answer",
            sources=[{"filename": "policy.pdf"}],
            partition="fast",
            library_generation=3,
            conversation_generation=7,
        )

        hit = await cache.get(
            vector,
            partition="fast",
            library_generation=3,
            conversation_generation=7,
        )
        miss = await cache.get(
            vector,
            partition="fast",
            library_generation=4,
            conversation_generation=7,
        )

        assert hit is not None
        assert hit["answer"] == "cached answer"
        assert miss is None

    asyncio.run(scenario())


def test_semantic_cache_reads_library_and_conversation_generations():
    from app.cache import SemanticCache, LIBRARY_GENERATION_KEY, conversation_generation_key

    async def scenario():
        redis_client = FakeRedis()
        redis_client.store[LIBRARY_GENERATION_KEY] = b"5"
        redis_client.store[conversation_generation_key("conv-1")] = b"2"

        cache = SemanticCache(redis_client=redis_client, similarity_threshold=0.8, ttl_seconds=60)
        library_generation, conversation_generation = await cache.get_generation_snapshot("conv-1")

        assert library_generation == 5
        assert conversation_generation == 2

    asyncio.run(scenario())
