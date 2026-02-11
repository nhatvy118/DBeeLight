"""Redis client utility for caching session messages."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

logger = logging.getLogger(__name__)

# Global Redis client singleton
_redis_client: Optional[aioredis.Redis] = None


async def init_redis_client() -> Optional[aioredis.Redis]:
    """
    Initialize Redis client singleton.
    Returns None if Redis is not available or connection fails.
    """
    global _redis_client
    
    if not REDIS_AVAILABLE:
        logger.warning("⚠️  Redis not available (package not installed). Install with: uv add redis[hiredis]")
        return None
    
    if _redis_client is not None:
        return _redis_client
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    try:
        _redis_client = await aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=False,  # We'll decode manually for JSON
            max_connections=10,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )
        
        # Test connection
        await _redis_client.ping()
        logger.info(f"✅ Redis connected: {redis_url}")
        return _redis_client
        
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed: {e}. Using in-memory cache fallback.")
        _redis_client = None
        return None


async def get_redis_client() -> Optional[aioredis.Redis]:
    """
    Get Redis client singleton.
    Returns None if Redis is not available.
    """
    if _redis_client is None:
        return await init_redis_client()
    return _redis_client


async def close_redis_client():
    """Close Redis client connection."""
    global _redis_client
    if _redis_client:
        try:
            await _redis_client.aclose()
            _redis_client = None
            logger.info("Redis client closed")
        except RuntimeError as e:
            # Event loop might be closed already (e.g., in test teardown)
            if "Event loop is closed" not in str(e):
                raise
            logger.debug("Redis client close skipped: event loop already closed")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")
            _redis_client = None


async def redis_get(key: str) -> Optional[Any]:
    """
    Get value from Redis.
    
    Args:
        key: Redis key
        
    Returns:
        Deserialized value (JSON) or None if not found
    """
    client = await get_redis_client()
    if not client:
        return None
    
    try:
        data = await client.get(key)
        if data is None:
            return None
        
        # Decode bytes to string, then parse JSON
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to decode Redis value for key {key}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Redis GET error for key {key}: {e}")
        return None


async def redis_set(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """
    Set value in Redis.
    
    Args:
        key: Redis key
        value: Value to store (will be JSON serialized)
        ttl: Time to live in seconds (optional)
        
    Returns:
        True if successful, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        # Serialize to JSON
        data = json.dumps(value, ensure_ascii=False)
        
        if ttl:
            # Set with expiration
            await client.setex(key, ttl, data)
        else:
            # Set without expiration
            await client.set(key, data)
        
        return True
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize value for Redis key {key}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Redis SET error for key {key}: {e}")
        return False


async def redis_delete(key: str) -> bool:
    """
    Delete key from Redis.
    
    Args:
        key: Redis key to delete
        
    Returns:
        True if deleted, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        result = await client.delete(key)
        return result > 0
    except Exception as e:
        logger.warning(f"Redis DELETE error for key {key}: {e}")
        return False


async def redis_exists(key: str) -> bool:
    """
    Check if key exists in Redis.
    
    Args:
        key: Redis key to check
        
    Returns:
        True if exists, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        result = await client.exists(key)
        return result > 0
    except Exception as e:
        logger.warning(f"Redis EXISTS error for key {key}: {e}")
        return False


async def redis_expire(key: str, ttl: int) -> bool:
    """
    Set expiration time for a key.
    
    Args:
        key: Redis key
        ttl: Time to live in seconds
        
    Returns:
        True if expiration was set, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        result = await client.expire(key, ttl)
        return result
    except Exception as e:
        logger.warning(f"Redis EXPIRE error for key {key}: {e}")
        return False


async def redis_ttl(key: str) -> int:
    """
    Get remaining TTL for a key.
    
    Args:
        key: Redis key
        
    Returns:
        TTL in seconds, -1 if no expiration, -2 if key doesn't exist
    """
    client = await get_redis_client()
    if not client:
        return -2
    
    try:
        return await client.ttl(key)
    except Exception as e:
        logger.warning(f"Redis TTL error for key {key}: {e}")
        return -2


# ==================== Redis Stack Operations ====================

async def redis_stack_push(key: str, value: Any) -> bool:
    """
    Push a message to the end of a Redis list (stack).
    
    Args:
        key: Redis key (stack name)
        value: Value to push (will be JSON serialized)
        
    Returns:
        True if successful, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        data = json.dumps(value, ensure_ascii=False)
        await client.rpush(key, data)  # RPUSH: add to end (FIFO order)
        return True
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize value for Redis stack {key}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Redis stack PUSH error for key {key}: {e}")
        return False


async def redis_stack_get_all(key: str) -> List[Any]:
    """
    Get all messages from a Redis list (stack).
    
    Args:
        key: Redis key (stack name)
        
    Returns:
        List of deserialized values, empty list if key doesn't exist
    """
    client = await get_redis_client()
    if not client:
        return []
    
    try:
        data_list = await client.lrange(key, 0, -1)  # Get all items
        if not data_list:
            return []
        
        result = []
        for data in data_list:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                result.append(json.loads(data))
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode item in stack {key}")
                continue
        
        return result
    except Exception as e:
        logger.warning(f"Redis stack GET_ALL error for key {key}: {e}")
        return []


async def redis_stack_length(key: str) -> int:
    """
    Get the length of a Redis list (stack).
    
    Args:
        key: Redis key (stack name)
        
    Returns:
        Number of items in the stack, 0 if key doesn't exist
    """
    client = await get_redis_client()
    if not client:
        return 0
    
    try:
        return await client.llen(key)
    except Exception as e:
        logger.warning(f"Redis stack LENGTH error for key {key}: {e}")
        return 0


async def redis_stack_clear(key: str) -> bool:
    """
    Clear all messages from a Redis list (stack).
    
    Args:
        key: Redis key (stack name)
        
    Returns:
        True if successful, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False
    
    try:
        await client.delete(key)
        return True
    except Exception as e:
        logger.warning(f"Redis stack CLEAR error for key {key}: {e}")
        return False
