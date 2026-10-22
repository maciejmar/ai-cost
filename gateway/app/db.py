"""Pula połączeń asyncpg + klient Redis, współdzielone przez całą aplikację."""
from __future__ import annotations

import asyncpg
import redis.asyncio as aioredis

from .config import get_settings

_pool:  asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


async def init() -> None:
    global _pool, _redis
    s = get_settings()
    _pool  = await asyncpg.create_pool(s.database_url, min_size=1, max_size=10)
    _redis = aioredis.from_url(s.redis_url, decode_responses=True)

    # Advisory lock — kilka workerów/replik nie wykona migracji równolegle
    async with _pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(727274)")
        try:
            await conn.execute(s.gateway_schema_path.read_text(encoding="utf-8"))
        finally:
            await conn.execute("SELECT pg_advisory_unlock(727274)")


async def close() -> None:
    if _pool:
        await _pool.close()
    if _redis:
        await _redis.aclose()


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database not initialised")
    return _pool


def redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised")
    return _redis
