"""Upstash Redis client for rate limiting and caching.

Returns a no-op stub when Redis is not configured or the URL is a placeholder.
"""

from typing import Optional

from app.config import settings

_redis: Optional["Redis"] = None


def _is_valid_url(url: str) -> bool:
    """Check if the URL looks like a real Upstash endpoint (not a placeholder)."""
    return bool(url) and "xxxx" not in url and url.startswith("https://")


def get_redis():
    """Get the Redis client (or a no-op stub if not configured)."""
    global _redis
    if _redis is None:
        if _is_valid_url(settings.upstash_redis_rest_url) and settings.upstash_redis_rest_token:
            from upstash_redis import Redis
            _redis = Redis(
                url=settings.upstash_redis_rest_url,
                token=settings.upstash_redis_rest_token,
            )
        else:
            _redis = _NoopRedis()
    return _redis


class _NoopRedis:
    """Fallback stub when Upstash Redis is not configured."""

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def get(self, key: str) -> Optional[str]:
        return None

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass
