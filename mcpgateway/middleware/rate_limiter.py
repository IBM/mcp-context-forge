"""Rate limiter middleware for content creation operations."""

# Standard
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os
from typing import Dict, List

# First-Party
from mcpgateway.config import settings


class ContentRateLimiter:
    """Rate limiter for content creation operations."""

    def __init__(self):
        """Initialize the ContentRateLimiter."""
        self.operation_counts: Dict[str, List[datetime]] = defaultdict(list)
        self.concurrent_operations: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user: str, operation: str = "create") -> bool:
        """
        Check if the user is within the allowed rate limit.

        Parameters:
            user (str): The user identifier.
            operation (str): The operation name.

        Returns:
            bool: True if within rate limit, False otherwise.
        """
        if os.environ.get("TESTING", "0") == "1":
            return True
        async with self._lock:
            now = datetime.now(timezone.utc)
            key = f"{user}:{operation}"
            if self.concurrent_operations[user] >= settings.content_max_concurrent_operations:
                return False
            cutoff = now - timedelta(minutes=1)
            self.operation_counts[key] = [ts for ts in self.operation_counts[key] if ts > cutoff]
            if len(self.operation_counts[key]) >= settings.content_create_rate_limit_per_minute:
                return False
            return True

    async def record_operation(self, user: str, operation: str = "create"):
        """
        Record a new operation for the user.

        Parameters:
            user (str): The user identifier.
            operation (str): The operation name.
        """
        async with self._lock:
            key = f"{user}:{operation}"
            self.operation_counts[key].append(datetime.now(timezone.utc))
            self.concurrent_operations[user] += 1

    async def end_operation(self, user: str):
        """
        End an operation for the user.

        Parameters:
            user (str): The user identifier.
        """
        async with self._lock:
            self.concurrent_operations[user] = max(0, self.concurrent_operations[user] - 1)


content_rate_limiter = ContentRateLimiter()
