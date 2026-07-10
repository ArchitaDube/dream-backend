"""Rate limiting via Upstash Redis."""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.redis import get_redis

# Rate limit config: {endpoint_key: (requests_per_window, window_seconds)}
LIMITS: dict[str, tuple[int, int]] = {
    "dialogue": (50, 86400),    # 50 turns/day free tier
    "analyze":  (5, 86400),     # 5 analyses/day free tier
    "image":    (5, 86400),     # 5 images/day (pro only)
    "sync_init": (1, 86400),    # 1 backup/day free tier
}

# Pro tier gets higher limits
PRO_LIMITS: dict[str, tuple[int, int]] = {
    "dialogue": (100, 86400),
    "analyze":  (10, 86400),
    "image":    (20, 86400),
    "sync_init": (100, 86400),
}


async def check_rate_limit(
    client_id: UUID,
    endpoint_key: str,
    is_pro: bool = False,
) -> None:
    """
    Check rate limit for a client on a given endpoint.
    Raises HTTPException(429) if exceeded.
    """
    limits = PRO_LIMITS if is_pro else LIMITS
    if endpoint_key not in limits:
        return

    max_requests, window = limits[endpoint_key]
    redis = get_redis()
    key = f"rl:{endpoint_key}:{client_id}"

    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)

    if count > max_requests:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(window)},
        )


class RateLimitMiddleware:
    """
    ASGI middleware for rate limiting.
    Maps request paths to endpoint keys.
    """

    ENDPOINT_MAP: dict[str, str] = {
        "/dreams/": "dialogue",     # catches /dreams/{id}/dialogue
        "/analyze": "analyze",
        "/image": "image",
        "/sync/init": "sync_init",
    }

    async def __call__(self, request: Request, call_next):
        response: Response = await call_next(request)
        return response
