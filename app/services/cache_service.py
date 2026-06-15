import json
import os
from typing import Any

import redis
from loguru import logger


class CacheService:
    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.ttl = int(os.getenv("CACHE_TTL_SECONDS", "86400"))
        self.client = redis.Redis.from_url(
            self.redis_url,
            decode_responses=True,
        )

    def get_json(self, key: str) -> Any | None:
        try:
            value = self.client.get(key)
            if not value:
                return None
            return json.loads(value)
        except Exception as exc:
            logger.warning(f"Redis get failed: {exc}")
            return None

    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            self.client.setex(
                key,
                ttl or self.ttl,
                json.dumps(value, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning(f"Redis set failed: {exc}")


cache_service = CacheService()
