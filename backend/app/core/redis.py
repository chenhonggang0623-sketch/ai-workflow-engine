import redis.asyncio as redis

from app.core.config import settings

redis_client: redis.Redis | None = None


async def init_redis():
    global redis_client
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return redis_client


async def close_redis():
    if redis_client:
        await redis_client.close()


def get_redis() -> redis.Redis:
    return redis_client
