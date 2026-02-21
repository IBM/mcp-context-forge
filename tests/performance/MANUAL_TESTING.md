# ContextForge API Manual Testing Guide

Complete CLI testing examples for ContextForge API endpoints.

## Prerequisites

```bash
# Install required tools
# - curl (usually pre-installed)
# - jq (for JSON parsing)
# - hey (for load testing)

# Install jq on Ubuntu/Debian
sudo apt-get install jq

# Install hey
go install github.com/rakyll/hey@latest
# OR download from: https://github.com/rakyll/hey/releases
```

## Quick Start: Complete Test Script

```bash
#!/bin/bash
# Save this as test_gateway.sh and run: bash test_gateway.sh

echo "=== ContextForge API Tests ==="

# 1. Health Check (no auth required)
echo -e "\n1. Health Check:"
curl -s http://localhost:4444/health | jq .

# 2. Login and get token
echo -e "\n2. Login:"
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')
echo "Token: ${TOKEN:0:50}..."

# 3. List tools
echo -e "\n3. List Tools (first 3):"
curl -s -X GET "http://localhost:4444/tools?limit=3" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0:3] | .[] | {name, description, team}'

# 4. List servers
echo -e "\n4. List Servers:"
curl -s -X GET "http://localhost:4444/servers?limit=3" \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | {id, name, url}'

# 5. List resources
echo -e "\n5. List Resources (first 3):"
curl -s -X GET "http://localhost:4444/resources?limit=3" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0:3] | .[] | {name, uri}'

echo -e "\n=== Tests Complete ==="
```

## Individual API Endpoint Tests

### 1. Health Check (No Authentication)

```bash
# Basic health check
curl -s http://localhost:4444/health | jq .

# Expected output:
# {
#   "status": "healthy",
#   "timestamp": "2025-10-10T09:27:54.705729Z"
# }
```

### 2. Authentication - Get JWT Token

```bash
# Login and get token
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Verify token was received
echo "Token: ${TOKEN:0:50}..."

# Decode JWT to see payload (optional)
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq .
```

### 3. List Tools (GET)

```bash
# List all tools (limit 5)
curl -s -X GET "http://localhost:4444/tools?limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Get just tool names and descriptions
curl -s -X GET "http://localhost:4444/tools?limit=10" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '.[] | {name, description, team, visibility}'

# Count total tools
curl -s -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $TOKEN" | jq 'length'
```

### 4. List Servers

```bash
# List all servers
curl -s -X GET "http://localhost:4444/servers" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Get server summary
curl -s -X GET "http://localhost:4444/servers" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '.[] | {id, name, url, enabled, reachable}'
```

### 5. List Resources

```bash
# List resources
curl -s -X GET "http://localhost:4444/resources?limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Get resource names and URIs
curl -s -X GET "http://localhost:4444/resources" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '.[] | {name, uri, mimeType}'
```

### 6. List Prompts

```bash
# List prompts
curl -s -X GET "http://localhost:4444/prompts?limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Get prompt names and descriptions
curl -s -X GET "http://localhost:4444/prompts" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '.[] | {name, description}'
```

### 7. Get User Profile

```bash
# Get current user info
curl -s -X GET "http://localhost:4444/auth/email/me" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Expected output:
# {
#   "email": "admin@example.com",
#   "full_name": "Platform Administrator",
#   "is_admin": true,
#   "auth_provider": "local",
#   "created_at": "2025-10-10T09:23:25.943945Z"
# }
```

## Performance Testing with hey

### Tools API Performance Test

```bash
# Get token first
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Performance test: 1000 requests, 50 concurrent
hey -n 1000 -c 50 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/tools?limit=10"

# Expected results (with optimized logging):
# Summary:
#   Total:        0.5-0.8 secs
#   Slowest:      0.05 secs
#   Fastest:      0.001 secs
#   Average:      0.02 secs
#   Requests/sec: 1500-2000
#
# Status code distribution:
#   [200] 1000 responses
```

### Health Check Performance Test

```bash
# No authentication required - test raw performance
hey -n 5000 -c 100 -m GET \
  "http://localhost:4444/health"

# Expected: 3000-5000 RPS (no DB queries)
```

### Multiple Endpoint Stress Test

```bash
# Generate token
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Test multiple endpoints in parallel
echo "Testing /tools..."
hey -n 500 -c 25 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/tools" &

echo "Testing /servers..."
hey -n 500 -c 25 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/servers" &

echo "Testing /resources..."
hey -n 500 -c 25 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/resources" &

# Wait for all tests to complete
wait

echo "All performance tests complete!"
```

## Benchmarking Script

Create a comprehensive benchmark script:

```bash
#!/bin/bash
# Save as benchmark.sh

echo "=== ContextForge Performance Benchmark ==="
echo "Starting at $(date)"

# Get token
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Test 1: Health endpoint (no auth)
echo -e "\n1. Health Check (5000 req, 100 concurrent):"
hey -n 5000 -c 100 -m GET \
  "http://localhost:4444/health" | \
  grep -E "Requests/sec:|Total:|Status code"

# Test 2: Tools endpoint
echo -e "\n2. Tools API (1000 req, 50 concurrent):"
hey -n 1000 -c 50 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/tools?limit=10" | \
  grep -E "Requests/sec:|Total:|Status code"

# Test 3: Servers endpoint
echo -e "\n3. Servers API (1000 req, 50 concurrent):"
hey -n 1000 -c 50 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/servers" | \
  grep -E "Requests/sec:|Total:|Status code"

echo -e "\n=== Benchmark Complete ==="
echo "Finished at $(date)"
```

## Expected Performance Results

With optimized logging settings (`LOG_LEVEL=ERROR`, `DISABLE_ACCESS_LOG=true`):

| Endpoint | Requests/sec | P50 Latency | P99 Latency |
|----------|-------------|-------------|-------------|
| /health | 3000-5000 | <5ms | <20ms |
| /tools | 1500-2000 | <25ms | <50ms |
| /servers | 1500-2000 | <25ms | <50ms |
| /resources | 1200-1800 | <30ms | <60ms |

**Note**: Actual performance depends on:
- Hardware specs
- Database configuration (SQLite vs PostgreSQL)
- Number of tools/servers/resources
- LOG_LEVEL setting (ERROR is fastest)
- DISABLE_ACCESS_LOG setting

## Troubleshooting

### Token Expiration

```bash
# Tokens expire after 7 days by default
# If you get "Invalid authentication credentials", regenerate token:
export TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')
```

### Check Token Validity

```bash
# Decode token to check expiration
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '.exp'

# Compare with current time
echo "Current time: $(date +%s)"
echo "Token expires: $(echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq -r '.exp')"
```

### View Detailed API Response

```bash
# Get full response with headers
curl -v -X GET "http://localhost:4444/tools?limit=1" \
  -H "Authorization: Bearer $TOKEN"

# Or use -i for just headers
curl -i -X GET "http://localhost:4444/health"
```

## Advanced: Automated Testing

Create a continuous test script that runs every 5 seconds:

```bash
#!/bin/bash
# Save as continuous_test.sh

while true; do
  clear
  echo "=== ContextForge Health Check ==="
  echo "Timestamp: $(date)"

  # Get token
  TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email": "admin@example.com", "password": "changeme"}' \
    | jq -r '.access_token')

  # Test endpoints
  echo -e "\nHealth: $(curl -s http://localhost:4444/health | jq -r '.status')"
  echo "Tools: $(curl -s -X GET http://localhost:4444/tools -H "Authorization: Bearer $TOKEN" | jq 'length') available"
  echo "Servers: $(curl -s -X GET http://localhost:4444/servers -H "Authorization: Bearer $TOKEN" | jq 'length') registered"

  echo -e "\nPress Ctrl+C to stop"
  sleep 5
done
```

Run with: `bash continuous_test.sh`

## Integration with Automated Tests

These manual tests complement the automated test suites:

```bash
# Run automated tests
make test                    # Unit and integration tests
make smoketest              # End-to-end Docker tests

# Run performance tests
cd tests/performance
./run-configurable.sh       # Configurable performance suite
./run-advanced.sh           # Advanced multi-profile tests
```

## Common Testing Scenarios

### Scenario 1: Verify Fix After Deployment

```bash
#!/bin/bash
# Quick smoke test after deployment

TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Test critical endpoints
HEALTH=$(curl -s http://localhost:4444/health | jq -r '.status')
TOOLS=$(curl -s -X GET http://localhost:4444/tools -H "Authorization: Bearer $TOKEN" | jq 'length')

if [ "$HEALTH" = "healthy" ] && [ "$TOOLS" -ge 0 ] 2>/dev/null; then
  echo "✅ Deployment verified successfully"
  exit 0
else
  echo "❌ Deployment verification failed"
  exit 1
fi
```

### Scenario 2: Load Test Before Release

```bash
#!/bin/bash
# Pre-release load test

TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

echo "Running load test..."
hey -n 10000 -c 100 -m GET \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/tools?limit=10" > /tmp/load_test_results.txt

# Check if 99% of requests succeeded
SUCCESS_RATE=$(grep "200" /tmp/load_test_results.txt | grep -oP '\d+(?= responses)' || echo "0")

if [ "$SUCCESS_RATE" -ge 9900 ]; then
  echo "✅ Load test passed (${SUCCESS_RATE}/10000 succeeded)"
  exit 0
else
  echo "❌ Load test failed (only ${SUCCESS_RATE}/10000 succeeded)"
  exit 1
fi
```

### Scenario 3: API Response Time Monitoring

```bash
#!/bin/bash
# Monitor API response times

TOKEN=$(curl -s -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme"}' \
  | jq -r '.access_token')

# Measure response time
START=$(date +%s%3N)
curl -s -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $TOKEN" > /dev/null
END=$(date +%s%3N)

RESPONSE_TIME=$((END - START))

echo "Tools API response time: ${RESPONSE_TIME}ms"

if [ "$RESPONSE_TIME" -lt 100 ]; then
  echo "✅ Response time acceptable"
else
  echo "⚠️  Response time slower than expected"
fi
```

## See Also

- [Automated Performance Tests](./README.md) - Comprehensive automated test suite
- [Quick Start Guide](./QUICK_START.md) - Get started with performance testing
- [Main README](../../README.md) - Full project documentation
