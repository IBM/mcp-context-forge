#!/usr/bin/env python3
"""
Test script to verify the rate limiting is working correctly.
This script will make 5 requests to create resources and verify that only 3 are allowed.
"""

import asyncio
import os
import sys
import json
from httpx import AsyncClient

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_rate_limit():
    """Test that rate limiting works correctly with 3 requests allowed."""
    
    # You'll need to replace this with your actual token
    token = os.environ.get("MCPGATEWAY_BEARER_TOKEN")
    if not token:
        print("Please set MCPGATEWAY_BEARER_TOKEN environment variable")
        return
    
    base_url = "http://localhost:4444"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    async with AsyncClient() as client:
        successful_requests = 0
        rate_limited_requests = 0
        
        # Try to make 5 requests
        for i in range(5):
            payload = {
                "uri": f"test://rate{i}",
                "name": f"Rate{i}",
                "content": "test content"
            }
            
            try:
                response = await client.post(
                    f"{base_url}/resources",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 201:
                    successful_requests += 1
                    print(f"✅ Request {i+1}: SUCCESS (201)")
                elif response.status_code == 429:
                    rate_limited_requests += 1
                    print(f"❌ Request {i+1}: RATE LIMITED (429)")
                else:
                    print(f"⚠️  Request {i+1}: UNEXPECTED STATUS ({response.status_code})")
                    print(f"Response: {response.text}")
                    
            except Exception as e:
                print(f"❌ Request {i+1}: ERROR - {e}")
        
        print(f"\n📊 Results:")
        print(f"   Successful requests: {successful_requests}")
        print(f"   Rate limited requests: {rate_limited_requests}")
        
        if successful_requests == 3 and rate_limited_requests == 2:
            print("✅ Rate limiting is working correctly!")
        else:
            print("❌ Rate limiting is not working as expected!")
            print("   Expected: 3 successful, 2 rate limited")

if __name__ == "__main__":
    asyncio.run(test_rate_limit())