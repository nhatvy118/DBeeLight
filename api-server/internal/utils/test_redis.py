"""Unit tests for Redis client functions."""

import pytest
from internal.utils.redis_client import (
    init_redis_client,
    redis_get,
    redis_set,
    redis_delete,
    redis_exists,
    redis_expire,
    redis_ttl,
    close_redis_client,
    get_redis_client,
)

@pytest.fixture(scope="module")
async def redis_client():
    """Fixture to initialize Redis client for all tests."""
    client = await init_redis_client()
    if not client:
        pytest.skip("Redis not available. Make sure Redis is running.")
    yield client
    # Don't close Redis client in fixture teardown - let it stay open for other tests
    # The connection will be reused and pytest will handle cleanup


@pytest.fixture(autouse=True)
async def cleanup_redis(redis_client):
    """Cleanup test keys before and after each test."""
    # Cleanup before test
    test_keys = ["test:key1", "test:key2", "test:key3", "test:key4"]
    for key in test_keys:
        await redis_delete(key)
    
    yield
    
    # Cleanup after test
    for key in test_keys:
        await redis_delete(key)


class TestRedisConnection:
    """Test Redis connection and initialization."""
    
    async def test_init_redis_client(self):
        """Test Redis client initialization."""
        client = await init_redis_client()
        assert client is not None, "Redis client should be initialized"
        
        # Test ping
        result = await client.ping()
        assert result is True, "Redis ping should return True"
    
    async def test_get_redis_client_singleton(self):
        """Test that get_redis_client returns singleton."""
        client1 = await get_redis_client()
        client2 = await get_redis_client()
        
        assert client1 is not None
        assert client2 is not None
        assert client1 is client2, "Should return same client instance (singleton)"


class TestRedisGetSet:
    """Test Redis GET and SET operations."""
    
    async def test_set_and_get_string(self):
        """Test setting and getting a string value."""
        key = "test:key1"
        value = "Hello Redis"
        
        result = await redis_set(key, value)
        assert result is True, "SET should return True"
        
        retrieved = await redis_get(key)
        assert retrieved == value, "GET should return the same value"
    
    async def test_set_and_get_dict(self):
        """Test setting and getting a dictionary value."""
        key = "test:key1"
        value = {"message": "Hello Redis", "count": 42, "active": True}
        
        result = await redis_set(key, value)
        assert result is True
        
        retrieved = await redis_get(key)
        assert retrieved == value
        assert retrieved["message"] == "Hello Redis"
        assert retrieved["count"] == 42
        assert retrieved["active"] is True
    
    async def test_set_and_get_list(self):
        """Test setting and getting a list value."""
        key = "test:key1"
        value = [1, 2, 3, "four", {"five": 5}]
        
        result = await redis_set(key, value)
        assert result is True
        
        retrieved = await redis_get(key)
        assert retrieved == value
        assert len(retrieved) == 5
    
    async def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        key = "test:nonexistent"
        
        value = await redis_get(key)
        assert value is None, "GET should return None for nonexistent key"
    
    async def test_set_overwrite(self):
        """Test overwriting an existing key."""
        key = "test:key1"
        
        # Set initial value
        await redis_set(key, "initial")
        assert await redis_get(key) == "initial"
        
        # Overwrite
        await redis_set(key, "updated")
        assert await redis_get(key) == "updated"


class TestRedisTTL:
    """Test Redis TTL (Time To Live) operations."""
    
    async def test_set_with_ttl(self):
        """Test setting a key with TTL."""
        key = "test:key1"
        value = {"ttl": "test"}
        
        result = await redis_set(key, value, ttl=10)
        assert result is True
        
        ttl = await redis_ttl(key)
        assert 0 < ttl <= 10, f"TTL should be between 0 and 10, got {ttl}"
    
    async def test_expire_existing_key(self):
        """Test setting expiration on an existing key."""
        key = "test:key1"
        value = "test value"
        
        # Set without TTL
        await redis_set(key, value)
        ttl_before = await redis_ttl(key)
        assert ttl_before == -1, "Key without TTL should return -1"
        
        # Set expiration
        result = await redis_expire(key, 15)
        assert result is True
        
        ttl_after = await redis_ttl(key)
        assert 0 < ttl_after <= 15, f"TTL should be between 0 and 15, got {ttl_after}"
    
    async def test_ttl_nonexistent_key(self):
        """Test TTL on a nonexistent key."""
        key = "test:nonexistent"
        
        ttl = await redis_ttl(key)
        assert ttl == -2, "TTL should return -2 for nonexistent key"


class TestRedisExists:
    """Test Redis EXISTS operation."""
    
    async def test_exists_existing_key(self):
        """Test EXISTS on an existing key."""
        key = "test:key1"
        value = "test"
        
        await redis_set(key, value)
        exists = await redis_exists(key)
        assert exists is True, "EXISTS should return True for existing key"
    
    async def test_exists_nonexistent_key(self):
        """Test EXISTS on a nonexistent key."""
        key = "test:nonexistent"
        
        exists = await redis_exists(key)
        assert exists is False, "EXISTS should return False for nonexistent key"


class TestRedisDelete:
    """Test Redis DELETE operation."""
    
    async def test_delete_existing_key(self):
        """Test deleting an existing key."""
        key = "test:key1"
        value = "test"
        
        # Set and verify
        await redis_set(key, value)
        assert await redis_exists(key) is True
        
        # Delete
        result = await redis_delete(key)
        assert result is True, "DELETE should return True for existing key"
        
        # Verify deleted
        assert await redis_exists(key) is False
        assert await redis_get(key) is None
    
    async def test_delete_nonexistent_key(self):
        """Test deleting a nonexistent key."""
        key = "test:nonexistent"
        
        result = await redis_delete(key)
        assert result is False, "DELETE should return False for nonexistent key"


class TestRedisIntegration:
    """Integration tests for Redis operations."""
    
    async def test_session_cache_simulation(self):
        """Simulate session cache operations."""
        session_id = "test:session:123"
        messages = [
            {"role": "user", "content": "Hello", "timestamp": "2024-01-01T00:00:00"},
            {"role": "assistant", "content": "Hi there!", "timestamp": "2024-01-01T00:00:01"},
        ]
        
        # Set session data with TTL
        result = await redis_set(session_id, {"messages": messages}, ttl=300)
        assert result is True
        
        # Get session data
        data = await redis_get(session_id)
        assert data is not None
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
        
        # Update session (add new message)
        new_message = {"role": "user", "content": "How are you?", "timestamp": "2024-01-01T00:00:02"}
        data["messages"].append(new_message)
        
        result = await redis_set(session_id, data, ttl=300)
        assert result is True
        
        # Verify update
        updated_data = await redis_get(session_id)
        assert len(updated_data["messages"]) == 3
        assert updated_data["messages"][2]["content"] == "How are you?"
        
        # Cleanup
        await redis_delete(session_id)
    
    async def test_multiple_keys_operations(self):
        """Test operations on multiple keys."""
        keys = ["test:key1", "test:key2", "test:key3"]
        values = ["value1", {"key": "value2"}, [1, 2, 3]]
        
        # Set multiple keys
        for key, value in zip(keys, values):
            result = await redis_set(key, value)
            assert result is True
        
        # Verify all keys exist
        for key in keys:
            assert await redis_exists(key) is True
        
        # Get all values
        retrieved = []
        for key in keys:
            value = await redis_get(key)
            retrieved.append(value)
        
        assert retrieved == values
        
        # Delete all keys
        for key in keys:
            result = await redis_delete(key)
            assert result is True
            assert await redis_exists(key) is False
