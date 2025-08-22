#!/bin/bash

# Test script to verify rate limiting works with 3 requests allowed
# Usage: ./test_rate_limit.sh

if [ -z "$MCPGATEWAY_BEARER_TOKEN" ]; then
    echo "Please set MCPGATEWAY_BEARER_TOKEN environment variable"
    exit 1
fi

echo "Testing rate limiting with 5 requests (expecting 3 success, 2 rate limited)..."
echo

successful=0
rate_limited=0

for i in {1..5}; do
    echo -n "Request $i: "
    
    response=$(curl -s -w "%{http_code}" -X POST \
        -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"uri\":\"test://rate$i\",\"name\":\"Rate$i\",\"content\":\"test\"}" \
        http://localhost:4444/resources)
    
    status_code="${response: -3}"
    
    if [ "$status_code" = "201" ]; then
        echo "✅ SUCCESS (201)"
        ((successful++))
    elif [ "$status_code" = "429" ]; then
        echo "❌ RATE LIMITED (429)"
        ((rate_limited++))
    else
        echo "⚠️  UNEXPECTED STATUS ($status_code)"
        echo "Response: ${response%???}"
    fi
    
    # Small delay between requests
    sleep 0.1
done

echo
echo "📊 Results:"
echo "   Successful requests: $successful"
echo "   Rate limited requests: $rate_limited"

if [ $successful -eq 3 ] && [ $rate_limited -eq 2 ]; then
    echo "✅ Rate limiting is working correctly!"
    exit 0
else
    echo "❌ Rate limiting is not working as expected!"
    echo "   Expected: 3 successful, 2 rate limited"
    exit 1
fi