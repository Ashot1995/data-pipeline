"""
Caching module for the Real-Time Data Collection and Monitoring System.

Provides Redis-based caching for frequently accessed data.
"""

import os
import json
import logging
import time
from typing import Optional, Any, Dict, List
from datetime import timedelta
import redis.asyncio as redis

logger = logging.getLogger(__name__)


def _record_cache_metric(operation: str, status: str, duration_sec: float) -> None:
    """Record cache operation metric (deferred import to avoid circular dependency)."""
    try:
        from metrics import record_cache_operation
        record_cache_operation(operation, status, duration_sec)
    except Exception:
        pass

# Redis connection
_redis_client: Optional[redis.Redis] = None


async def get_redis_client() -> Optional[redis.Redis]:
    """
    Get or create Redis client.

    Returns:
        Redis client or None if Redis is not available
    """
    global _redis_client

    if _redis_client is not None:
        # Verify the existing connection is still alive before returning it
        try:
            await _redis_client.ping()
            return _redis_client
        except Exception:
            logger.warning("Redis connection lost; attempting reconnect")
            _redis_client = None

    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_db = int(os.getenv("REDIS_DB", "0"))

    try:
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        # Test connection
        await client.ping()
        _redis_client = client
        logger.info("Connected to Redis cache")
        return _redis_client
    except Exception as e:
        logger.warning(f"Could not connect to Redis: {e}. Caching disabled.")
        return None


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis connection closed")


class Cache:
    """Cache wrapper for Redis operations."""

    def __init__(self, default_ttl: int = 300):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds
        """
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        client = await get_redis_client()
        if client is None:
            return None

        try:
            value = await client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return None

    async def set(
        self, key: str, value: Any, ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)

        Returns:
            True if successful, False otherwise
        """
        client = await get_redis_client()
        if client is None:
            return False

        try:
            ttl = ttl or self.default_ttl
            await client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if successful, False otherwise
        """
        client = await get_redis_client()
        if client is None:
            return False

        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """
        Clear all keys matching pattern.

        Args:
            pattern: Key pattern (e.g., "sensor_data:*")

        Returns:
            Number of keys deleted
        """
        client = await get_redis_client()
        if client is None:
            return 0

        try:
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return await client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Cache clear pattern error for {pattern}: {e}")
            return 0


# Global cache instance
cache = Cache(default_ttl=int(os.getenv("CACHE_TTL", "300")))


async def cache_recent_data(limit: int, data: List[Dict[str, Any]]) -> None:
    """
    Cache recent sensor data.

    Args:
        limit: Number of records
        data: Data to cache
    """
    key = f"sensor_data:recent:{limit}"
    t0 = time.perf_counter()
    ok = await cache.set(key, data, ttl=60)  # Cache for 1 minute
    _record_cache_metric("recent_set", "success" if ok else "error", time.perf_counter() - t0)


async def get_cached_recent_data(limit: int) -> Optional[List[Dict[str, Any]]]:
    """
    Get cached recent sensor data.

    Args:
        limit: Number of records

    Returns:
        Cached data or None
    """
    key = f"sensor_data:recent:{limit}"
    t0 = time.perf_counter()
    value = await cache.get(key)
    duration = time.perf_counter() - t0
    _record_cache_metric("recent_get", "hit" if value is not None else "miss", duration)
    return value


async def cache_aggregated_data(
    interval_minutes: int, limit: int, data: List[Dict[str, Any]]
) -> None:
    """
    Cache aggregated sensor data.

    Args:
        interval_minutes: Time bucket interval
        limit: Number of buckets
        data: Data to cache
    """
    key = f"sensor_data:aggregated:{interval_minutes}:{limit}"
    t0 = time.perf_counter()
    ok = await cache.set(key, data, ttl=300)  # Cache for 5 minutes
    _record_cache_metric("aggregated_set", "success" if ok else "error", time.perf_counter() - t0)


async def get_cached_aggregated_data(
    interval_minutes: int, limit: int
) -> Optional[List[Dict[str, Any]]]:
    """
    Get cached aggregated sensor data.

    Args:
        interval_minutes: Time bucket interval
        limit: Number of buckets

    Returns:
        Cached data or None
    """
    key = f"sensor_data:aggregated:{interval_minutes}:{limit}"
    t0 = time.perf_counter()
    value = await cache.get(key)
    duration = time.perf_counter() - t0
    _record_cache_metric("aggregated_get", "hit" if value is not None else "miss", duration)
    return value


async def invalidate_data_cache() -> None:
    """Invalidate all sensor data caches."""
    await cache.clear_pattern("sensor_data:*")
