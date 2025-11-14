# -*- coding: utf-8 -*-
"""Tests for correlation ID utilities."""

import asyncio
import pytest
from mcpgateway.utils.correlation_id import (
    clear_correlation_id,
    extract_correlation_id_from_headers,
    generate_correlation_id,
    get_correlation_id,
    get_or_generate_correlation_id,
    set_correlation_id,
    validate_correlation_id,
)


def test_generate_correlation_id():
    """Test correlation ID generation."""
    id1 = generate_correlation_id()
    id2 = generate_correlation_id()

    assert id1 is not None
    assert id2 is not None
    assert id1 != id2
    assert len(id1) == 32  # UUID4 hex is 32 characters
    assert len(id2) == 32


def test_set_and_get_correlation_id():
    """Test setting and getting correlation ID."""
    test_id = "test-correlation-123"

    set_correlation_id(test_id)
    retrieved_id = get_correlation_id()

    assert retrieved_id == test_id

    clear_correlation_id()


def test_clear_correlation_id():
    """Test clearing correlation ID."""
    test_id = "test-correlation-456"

    set_correlation_id(test_id)
    assert get_correlation_id() == test_id

    clear_correlation_id()
    assert get_correlation_id() is None


def test_get_correlation_id_returns_none_when_not_set():
    """Test getting correlation ID when not set."""
    clear_correlation_id()
    assert get_correlation_id() is None


def test_extract_correlation_id_from_headers():
    """Test extracting correlation ID from headers."""
    headers = {"X-Correlation-ID": "header-correlation-789"}

    correlation_id = extract_correlation_id_from_headers(headers)
    assert correlation_id == "header-correlation-789"


def test_extract_correlation_id_from_headers_case_insensitive():
    """Test case-insensitive header extraction."""
    headers = {"x-correlation-id": "lowercase-id"}

    correlation_id = extract_correlation_id_from_headers(headers)
    assert correlation_id == "lowercase-id"


def test_extract_correlation_id_from_headers_custom_header():
    """Test extracting from custom header name."""
    headers = {"X-Request-ID": "custom-request-id"}

    correlation_id = extract_correlation_id_from_headers(headers, "X-Request-ID")
    assert correlation_id == "custom-request-id"


def test_extract_correlation_id_from_headers_not_found():
    """Test when correlation ID header is not present."""
    headers = {"Content-Type": "application/json"}

    correlation_id = extract_correlation_id_from_headers(headers)
    assert correlation_id is None


def test_extract_correlation_id_from_headers_empty_value():
    """Test when correlation ID header has empty value."""
    headers = {"X-Correlation-ID": "   "}

    correlation_id = extract_correlation_id_from_headers(headers)
    assert correlation_id is None


def test_get_or_generate_correlation_id_when_not_set():
    """Test get_or_generate when ID is not set."""
    clear_correlation_id()

    correlation_id = get_or_generate_correlation_id()

    assert correlation_id is not None
    assert len(correlation_id) == 32
    assert get_correlation_id() == correlation_id  # Should be stored

    clear_correlation_id()


def test_get_or_generate_correlation_id_when_already_set():
    """Test get_or_generate when ID is already set."""
    test_id = "existing-correlation-id"
    set_correlation_id(test_id)

    correlation_id = get_or_generate_correlation_id()

    assert correlation_id == test_id

    clear_correlation_id()


def test_validate_correlation_id_valid():
    """Test validation of valid correlation IDs."""
    assert validate_correlation_id("abc-123") is True
    assert validate_correlation_id("test_id_456") is True
    assert validate_correlation_id("UPPER-lower-123_mix") is True


def test_validate_correlation_id_invalid():
    """Test validation of invalid correlation IDs."""
    assert validate_correlation_id(None) is False
    assert validate_correlation_id("") is False
    assert validate_correlation_id("   ") is False
    assert validate_correlation_id("id with spaces") is False
    assert validate_correlation_id("id@special!chars") is False


def test_validate_correlation_id_too_long():
    """Test validation rejects overly long IDs."""
    long_id = "a" * 256  # Default max is 255

    assert validate_correlation_id(long_id) is False
    assert validate_correlation_id(long_id, max_length=300) is True


@pytest.mark.asyncio
async def test_correlation_id_isolation_between_async_tasks():
    """Test that correlation IDs are isolated between concurrent async tasks."""
    results = []

    async def task_with_id(task_id: str):
        set_correlation_id(task_id)
        await asyncio.sleep(0.01)  # Simulate async work
        retrieved_id = get_correlation_id()
        results.append((task_id, retrieved_id))
        clear_correlation_id()

    # Run multiple tasks concurrently
    await asyncio.gather(
        task_with_id("task-1"),
        task_with_id("task-2"),
        task_with_id("task-3"),
    )

    # Each task should have retrieved its own ID
    assert len(results) == 3
    for task_id, retrieved_id in results:
        assert task_id == retrieved_id


@pytest.mark.asyncio
async def test_correlation_id_inheritance_in_nested_tasks():
    """Test that correlation ID is inherited by child async tasks."""

    async def parent_task():
        set_correlation_id("parent-id")
        parent_id = get_correlation_id()

        async def child_task():
            return get_correlation_id()

        child_id = await child_task()

        clear_correlation_id()
        return parent_id, child_id

    parent_id, child_id = await parent_task()

    # Child should inherit parent's correlation ID
    assert parent_id == "parent-id"
    assert child_id == "parent-id"


def test_correlation_id_context_isolation():
    """Test that correlation ID is properly isolated per context."""
    clear_correlation_id()

    # Set ID in one context
    set_correlation_id("context-1")
    assert get_correlation_id() == "context-1"

    # Overwrite with new ID
    set_correlation_id("context-2")
    assert get_correlation_id() == "context-2"

    clear_correlation_id()
    assert get_correlation_id() is None


def test_extract_correlation_id_strips_whitespace():
    """Test that extracted correlation ID has whitespace stripped."""
    headers = {"X-Correlation-ID": "  trimmed-id  "}

    correlation_id = extract_correlation_id_from_headers(headers)
    assert correlation_id == "trimmed-id"
