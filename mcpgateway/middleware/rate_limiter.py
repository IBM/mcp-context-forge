from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List

from mcpgateway.config import settings

class ContentRateLimiter:
    """Rate limiter for content creation operations."""
    def __init__(self):
        self.operation_counts: Dict[str, List[datetime]] = defaultdict(list)
        # Use user_id (str) as key, not a dict
        self.concurrent_operations = defaultdict(int)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user: str, operation: str = "create") -> bool:
        async with self._lock:
            now = datetime.utcnow()
            key = f"{user}:{operation}"  # Keep the original key format
            if self.concurrent_operations[user] >= settings.content_max_concurrent_operations:  # Original check
                return False
            cutoff = now - timedelta(minutes=1)
            self.operation_counts[key] = [ts for ts in self.operation_counts[key] if ts > cutoff]
            if len(self.operation_counts[key]) >= settings.content_create_rate_limit_per_minute:
                return False
            return True

    async def record_operation(self, user: str, operation: str = "create"):
        async with self._lock:
            key = f"{user}:{operation}"  # Keep the original key format
            self.operation_counts[key].append(datetime.utcnow())
            self.concurrent_operations[user] += 1  # Original increment

    async def end_operation(self, user: str):
        async with self._lock:
            self.concurrent_operations[user] = max(0, self.concurrent_operations[user] - 1)  # Original decrement

content_rate_limiter = ContentRateLimiter()
