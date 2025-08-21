"""Rate limiting middleware for content operations."""

# Standard
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

# Third-Party
from httpx import AsyncClient
import pytest

# First-Party
from mcpgateway.config import settings


class ContentRateLimiter:
    """Rate limiter for content creation operations."""

    def __init__(self):
        self.operation_counts = defaultdict(list)  # Tracks timestamps of operations per user
        self.concurrent_operations = defaultdict(int)  # Tracks concurrent operations per user
        self._lock = asyncio.Lock()

    async def reset(self):
        """Reset all rate limiting data."""
        async with self._lock:
            self.operation_counts.clear()
            self.concurrent_operations.clear()

    async def check_rate_limit(self, user: str, operation: str = "create") -> (bool, int):
        """
        Check if the user is within the allowed rate limit.

        Args:
            user: User identifier
            operation: Operation type

        Returns:
            allowed (bool): True if within limit, False otherwise
            retry_after (int): Seconds until user can retry
        """
        async with self._lock:
            datetime.now(timezone.utc)
            key = f"{user}:{operation}"

            # Check create limit per user (permanent limit - no time window)
            if len(self.operation_counts[key]) >= settings.content_create_rate_limit_per_minute:
                return False, 1

            return True, 0

    async def record_operation(self, user: str, operation: str = "create"):
        """Record a new operation for the user.

        Args:
            user: User identifier
            operation: Operation type
        """
        async with self._lock:
            key = f"{user}:{operation}"
            now = datetime.now(timezone.utc)
            self.operation_counts[key].append(now)

    async def end_operation(self, user: str, operation: str = "create"):
        """End an operation for the user.

        Args:
            user: User identifier
            operation: Operation type
        """
        # No-op since we only track total count, not concurrent operations


@pytest.mark.asyncio
async def test_resource_rate_limit(async_client: AsyncClient, token):
    """Test resource rate limiting functionality.
    
    Args:
        async_client: HTTP client for testing.
        token: Authentication token.
    """
    for i in range(3):
        res = await async_client.post("/resources", headers={"Authorization": f"Bearer {token}"}, json={"uri": f"test://rate{i}", "name": f"Rate{i}", "content": "test"})
        assert res.status_code == 201

    # Fourth request should fail
    res = await async_client.post("/resources", headers={"Authorization": f"Bearer {token}"}, json={"uri": "test://rate4", "name": "Rate4", "content": "test"})
    assert res.status_code == 429


# Singleton instance
content_rate_limiter = ContentRateLimiter()
