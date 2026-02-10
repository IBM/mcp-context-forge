# -*- coding: utf-8 -*-
"""Unit tests for CacheTTLDict cache implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest
import pytest_asyncio

# First-Party
from llmguardplugin.cache import CacheTTLDict


@pytest_asyncio.fixture
async def cache():
    """Create a CacheTTLDict instance with mocked redis."""
    with patch("llmguardplugin.cache.aioredis.from_url") as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        cache_instance = CacheTTLDict(ttl=300)
        cache_instance.cache = mock_client
        yield cache_instance


class TestCacheTTLDictInit:
    """Tests for CacheTTLDict initialization."""

    def test_init_default_ttl(self):
        """Test initialization with default TTL."""
        with patch("llmguardplugin.cache.aioredis.from_url") as mock_redis:
            mock_redis.return_value = AsyncMock()
            cache = CacheTTLDict()
            assert cache.cache_ttl == 0
            assert cache.cache is not None

    def test_init_custom_ttl(self):
        """Test initialization with custom TTL."""
        with patch("llmguardplugin.cache.aioredis.from_url") as mock_redis:
            mock_redis.return_value = AsyncMock()
            cache = CacheTTLDict(ttl=600)
            assert cache.cache_ttl == 600


class TestUpdateCache:
    """Tests for update_cache method."""

    @pytest.mark.asyncio
    async def test_update_cache_success(self, cache):
        """Test successful cache update."""
        key = "test_key"
        value = [("original", "PERSON", "placeholder")]

        # Mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[True, True])
        cache.cache.pipeline = MagicMock(return_value=mock_pipe)
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        success_set, success_expiry = await cache.update_cache(key, value)

        assert success_set is True
        assert success_expiry is True
        mock_pipe.set.assert_called_once()
        mock_pipe.expire.assert_called_once_with(key, cache.cache_ttl)

    @pytest.mark.asyncio
    async def test_update_cache_serialization_error(self, cache):
        """Test cache update with serialization error."""
        key = "test_key"
        # Create a non-serializable object
        value = [object()]

        success_set, success_expiry = await cache.update_cache(key, value)

        assert success_set is False
        assert success_expiry is False

    @pytest.mark.asyncio
    async def test_update_cache_set_failure(self, cache):
        """Test cache update when set operation fails."""
        key = "test_key"
        value = [("original", "PERSON", "placeholder")]

        # Mock pipeline with set failure
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[False, True])
        cache.cache.pipeline = MagicMock(return_value=mock_pipe)
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        success_set, success_expiry = await cache.update_cache(key, value)

        assert success_set is False
        assert success_expiry is True

    @pytest.mark.asyncio
    async def test_update_cache_expiry_failure(self, cache):
        """Test cache update when expiry operation fails."""
        key = "test_key"
        value = [("original", "PERSON", "placeholder")]

        # Mock pipeline with expiry failure
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[True, False])
        cache.cache.pipeline = MagicMock(return_value=mock_pipe)
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)

        success_set, success_expiry = await cache.update_cache(key, value)

        assert success_set is True
        assert success_expiry is False


class TestRetrieveCache:
    """Tests for retrieve_cache method."""

    @pytest.mark.asyncio
    async def test_retrieve_cache_hit(self, cache):
        """Test successful cache retrieval."""
        key = "test_key"
        value = [["original", "PERSON", "placeholder"]]
        serialized = orjson.dumps(value)

        cache.cache.get = AsyncMock(return_value=serialized)

        result = await cache.retrieve_cache(key)

        assert result == [("original", "PERSON", "placeholder")]
        cache.cache.get.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_retrieve_cache_miss(self, cache):
        """Test cache miss."""
        key = "test_key"

        cache.cache.get = AsyncMock(return_value=None)

        result = await cache.retrieve_cache(key)

        assert result is None
        cache.cache.get.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_retrieve_cache_invalid_json(self, cache):
        """Test cache retrieval with invalid JSON."""
        key = "test_key"

        cache.cache.get = AsyncMock(return_value=b"invalid json{")
        cache.cache.delete = AsyncMock()

        result = await cache.retrieve_cache(key)

        assert result is None
        cache.cache.delete.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_retrieve_cache_unexpected_type(self, cache):
        """Test cache retrieval with unexpected data type."""
        key = "test_key"
        value = "not a list"
        serialized = orjson.dumps(value)

        cache.cache.get = AsyncMock(return_value=serialized)
        cache.cache.delete = AsyncMock()

        result = await cache.retrieve_cache(key)

        assert result is None
        cache.cache.delete.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_retrieve_cache_with_nested_lists(self, cache):
        """Test cache retrieval with nested lists."""
        key = "test_key"
        value = [["item1", "item2"], ["item3", "item4"]]
        serialized = orjson.dumps(value)

        cache.cache.get = AsyncMock(return_value=serialized)

        result = await cache.retrieve_cache(key)

        assert result == [("item1", "item2"), ("item3", "item4")]


class TestConvertToListOfTuples:
    """Tests for _convert_to_list_of_tuples method."""

    @pytest.mark.asyncio
    async def test_convert_list_of_lists(self, cache):
        """Test converting list of lists to list of tuples."""
        obj = [["a", "b"], ["c", "d"]]
        result = cache._convert_to_list_of_tuples(obj)
        assert result == [("a", "b"), ("c", "d")]

    @pytest.mark.asyncio
    async def test_convert_mixed_types(self, cache):
        """Test converting mixed types (lists and non-lists)."""
        obj = [["a", "b"], "string", 123]
        result = cache._convert_to_list_of_tuples(obj)
        assert result == [("a", "b"), "string", 123]

    @pytest.mark.asyncio
    async def test_convert_empty_list(self, cache):
        """Test converting empty list."""
        obj = []
        result = cache._convert_to_list_of_tuples(obj)
        assert result == []


class TestDeleteCache:
    """Tests for delete_cache method."""

    @pytest.mark.asyncio
    async def test_delete_cache_success(self, cache):
        """Test successful cache deletion."""
        key = "test_key"

        cache.cache.delete = AsyncMock(return_value=1)
        cache.cache.exists = AsyncMock(return_value=0)

        await cache.delete_cache(key)

        cache.cache.delete.assert_called_once_with(key)
        cache.cache.exists.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_delete_cache_not_found(self, cache):
        """Test cache deletion when key doesn't exist."""
        key = "test_key"

        cache.cache.delete = AsyncMock(return_value=0)
        cache.cache.exists = AsyncMock(return_value=0)

        await cache.delete_cache(key)

        cache.cache.delete.assert_called_once_with(key)
        cache.cache.exists.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_delete_cache_still_exists(self, cache):
        """Test cache deletion when key still exists after deletion."""
        key = "test_key"

        cache.cache.delete = AsyncMock(return_value=1)
        cache.cache.exists = AsyncMock(return_value=1)

        await cache.delete_cache(key)

        cache.cache.delete.assert_called_once_with(key)
        cache.cache.exists.assert_called_once_with(key)


# Made with Bob
