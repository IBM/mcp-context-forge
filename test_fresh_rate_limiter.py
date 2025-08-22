#!/usr/bin/env python3
"""
Test with a fresh rate limiter instance.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcpgateway.middleware.rate_limiter import ContentRateLimiter
from mcpgateway.config import settings

async def test_fresh_rate_limiter():
    """Test with a fresh rate limiter instance."""
    # Create a fresh instance
    rate_limiter = ContentRateLimiter()
    
    print(f"Rate limit per minute: {settings.content_create_rate_limit_per_minute}")
    print(f"Max concurrent operations: {settings.content_max_concurrent_operations}")
    
    user_id = "test_user"
    operation = "create"
    key = f"{user_id}:{operation}"
    
    print(f"\nTesting fresh rate limiter for user: {user_id}")
    
    # Test multiple requests
    for i in range(5):
        print(f"\n--- Request {i+1} ---")
        current_count = len(rate_limiter.operation_counts[key])
        print(f"Current count: {current_count}, Limit: {settings.content_create_rate_limit_per_minute}")
        
        allowed, retry_after = await rate_limiter.check_rate_limit(user_id, operation)
        print(f"Check result: allowed={allowed}, retry_after={retry_after}")
        
        if allowed:
            await rate_limiter.record_operation(user_id, operation)
            new_count = len(rate_limiter.operation_counts[key])
            print(f"After record - new count: {new_count}")
        else:
            print(f"  -> RATE LIMITED! Should retry after {retry_after} seconds")
            break
    
    print("\nFresh rate limiter test completed.")

if __name__ == "__main__":
    asyncio.run(test_fresh_rate_limiter())