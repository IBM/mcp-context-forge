# Manual Testing Guide: Validation Middleware Performance Optimizations

This guide provides step-by-step instructions to manually test the validation middleware performance optimizations in your local environment.

## Prerequisites

1. MCP Gateway installed and configured
2. Python environment with dependencies installed
3. `curl` or similar HTTP client
4. Optional: `ab` (Apache Bench) or `wrk` for load testing

## Setup

### 1. Configure Environment Variables

Create or update your `.env` file with the following settings:

```bash
# Enable validation middleware
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_MIDDLEWARE_ENABLED=true
VALIDATION_STRICT=true
SANITIZE_OUTPUT=true

# Performance optimization settings
VALIDATION_MAX_BODY_SIZE=1048576  # 1MB
VALIDATION_MAX_RESPONSE_SIZE=5242880  # 5MB
# Use comma-separated patterns OR JSON array format
VALIDATION_SKIP_ENDPOINTS='["^/health$","^/metrics$","^/static/.*"]'
VALIDATION_CACHE_ENABLED=true
VALIDATION_CACHE_MAX_SIZE=1000
VALIDATION_CACHE_TTL=300
VALIDATION_SAMPLE_LARGE_RESPONSES=true
VALIDATION_SAMPLE_SIZE=10240

# Enable logging (INFO level is sufficient for performance logs)
LOG_LEVEL=INFO
```

### 2. Start the Gateway

```bash
# From the project root
make dev
```

Or if using production mode:

```bash
make serve
```

The gateway should start on `http://localhost:4444` (or your configured port).

## Test Scenarios

### Test 1: Endpoint Filtering (Skip Validation)

**Objective**: Verify that configured endpoints skip validation entirely.

**Steps**:

1. Test health endpoint (should skip validation):
```bash
curl -v http://localhost:4444/health
-H "Authorization: Bearer $TOKEN" \
```

2. Check logs for:
```
[VALIDATION] Skipping validation for endpoint: /health
```

3. Test metrics endpoint (should skip validation):
```bash
curl -v http://localhost:4444/metrics
-H "Authorization: Bearer $TOKEN" \
```

4. Test a regular API endpoint (should validate):
```bash
curl -v http://localhost:4444/servers
-H "Authorization: Bearer $TOKEN" \
```

**Expected Results**:
- `/health` and `/metrics` show "Skipping validation" in logs
- Regular API endpoints do NOT show skip message
- Response times for `/health` and `/metrics` should be faster

---

### Test 2: Large Request Body (Skip Validation)

**Objective**: Verify that large request bodies skip validation.

**Steps**:

1. Create a large JSON payload (>1MB):
```bash
# Generate a 2MB JSON file
python3 << 'EOF'
import json
data = {"data": "x" * 2000000}  # 2MB of data
with open("/tmp/large_payload.json", "w") as f:
    json.dump(data, f)
EOF
```

2. Send the large payload to a tools endpoint:
```bash
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d @/tmp/large_payload.json \
  -v
```

3. Check logs for:
```
[VALIDATION] Skipping validation for large request body: 2000000 bytes (threshold: 1048576)
```

**Expected Results**:
- Log message confirms validation was skipped
- Request completes without validation overhead
- No validation errors despite large size

---

### Test 3: Cache Hit (Repeated Requests)

**Objective**: Verify that identical payloads use cached validation results.

**Steps**:

1. Send the same request multiple times:
```bash
# First request (cache miss)
curl -X 'PUT' \
  'http://localhost:4444/prompts/7c3406144e7c49cca9eeb857b8224ac1' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
  "tags": ["JAN cpu"]
}'  \
  -w "\nTime: %{time_total}s\n"

# Second request (cache hit)
curl -X 'PUT' \
  'http://localhost:4444/prompts/{prompt_id}' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
  "tags": ["test cpu"]
}'  \
  -w "\nTime: %{time_total}s\n"

# Third request (cache hit)
curl -X 'PUT' \
  'http://localhost:4444/prompts/{prompt_id}' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
  "tags": ["test cpu"]
}'  \
  -w "\nTime: %{time_total}s\n"
```

3. Check logs for:
```
[VALIDATION] Cache hit for request body
```

**Expected Results**:
- First request: No cache message
- Subsequent requests: "Cache hit" message in logs
- Second and third requests should be slightly faster

---

### Test 4: Response Sampling (Large Responses)

**Objective**: Verify that large responses are sampled instead of fully sanitized.

**Steps**:

1. Request a list endpoint that may return a large response:
```bash
# Request a large response (>5MB to skip, or >10KB to sample)
curl -X GET http://localhost:4444/servers \
  -H "Authorization: Bearer $TOKEN" \
  -v
```

2. For responses between 10KB and 5MB, check logs for:
```
[VALIDATION] Sampling response for sanitization: 1048576 bytes (sample: 10240)
[VALIDATION] Sample clean, skipping full sanitization
```

3. For responses >5MB, check logs for:
```
[VALIDATION] Skipping sanitization for large response: 10485760 bytes (threshold: 5242880)
```

**Expected Results**:
- Medium responses (10KB-5MB): Sampling message
- Large responses (>5MB): Skip sanitization message
- Response times should be faster for large responses

---

### Test 5: Validation Failure Caching

**Objective**: Verify that validation failures are also cached.

**Steps**:

1. Create a payload with dangerous patterns for tool creation:
```bash
cat > /tmp/dangerous_payload1.json << 'EOF'
{
  "name": "dangerous_tool",
  "displayName": "Dangerous Tool",
  "description": "rm -rf / $(malicious) dangerous command injection test",
  "url": "http://example.com/$(malicious)",
  "integration_type": "REST",
  "request_type": "SSE",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "default": "rm -rf /"
      }
    }
  }
}
EOF
```

2. Send the request multiple times to a tools endpoint:
```bash
# First request (validation fails, cached)
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d @/tmp/dangerous_payload1.json \
  -v
   \
  -w "\nTime: %{time_total}s\n"

# Second request (cached failure)
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d @/tmp/dangerous_payload.json \
  -v
   \
  -w "\nTime: %{time_total}s\n"
```

**Expected Results**:
- Both requests should fail with 422 status
- Second request should use cached failure (faster)
- Logs show validation failure for both

---

### Test 6: Cache Expiration

**Objective**: Verify that cache entries expire after TTL.

**Steps**:

1. Set a short TTL in `.env`:
```bash
VALIDATION_CACHE_TTL=10  # 10 seconds
```

2. Restart the gateway

3. Send a request to a tools endpoint:
```bash
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"test": "data"}' \
  -v
```

4. Wait 15 seconds

5. Send the same request again:
```bash
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"test": "data"}' \
  -v
```

**Expected Results**:
- First request: No cache hit
- Second request (within 10s): Cache hit
- Third request (after 15s): No cache hit (expired)

---

### Test 7: Disable Optimizations (Baseline)

**Objective**: Compare performance with and without optimizations.

**Steps**:

1. Disable optimizations in `.env`:
```bash
VALIDATION_MAX_BODY_SIZE=0  # Validate all
VALIDATION_MAX_RESPONSE_SIZE=0  # Sanitize all
VALIDATION_CACHE_ENABLED=false
VALIDATION_SKIP_ENDPOINTS=  # Empty
VALIDATION_SAMPLE_LARGE_RESPONSES=false
```

2. Restart the gateway

3. Run the same tests as above and compare:
   - Response times
   - CPU usage
   - Log messages

**Expected Results**:
- No "Skipping" or "Cache hit" messages
- Slower response times for large payloads
- Higher CPU usage

---

## Performance Benchmarking

### Using Apache Bench (ab)

1. Install Apache Bench:
```bash
# Ubuntu/Debian
sudo apt-get install apache2-utils

# macOS
brew install httpd
```

2. Benchmark with optimizations enabled:
```bash
# Small payload (should be similar)
ab -n 1000 -c 10 -p /tmp/test_payload.json \
  -T "application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:4444/api/test

# Large payload (should be much faster with optimizations)
ab -n 100 -c 5 -p /tmp/large_payload.json \
  -T "application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:4444/tools
```

3. Disable optimizations and run the same benchmarks

4. Compare results:
   - Requests per second
   - Time per request
   - CPU usage (use `top` or `htop` in another terminal)

### Using wrk

1. Install wrk:
```bash
# Ubuntu/Debian
sudo apt-get install wrk

# macOS
brew install wrk
```

2. Create a Lua script for POST requests:
```bash
cat > /tmp/post.lua << 'EOF'
wrk.method = "POST"
wrk.body   = '{"test": "data", "value": 123}'
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Authorization"] = "Bearer YOUR_TOKEN"
EOF
```

3. Run benchmark:
```bash
# With optimizations
wrk -t4 -c100 -d30s -s /tmp/post.lua http://localhost:4444/tools

# Disable optimizations and run again
```

---

## Monitoring and Verification

### 1. Check Logs

Monitor logs in real-time:
```bash
tail -f logs/mcpgateway.log | grep VALIDATION
```

Look for these key messages:
- `[VALIDATION] Skipping validation for endpoint: /health`
- `[VALIDATION] Skipping validation for large request body: X bytes`
- `[VALIDATION] Cache hit for request body`
- `[VALIDATION] Skipping sanitization for large response: X bytes`
- `[VALIDATION] Sampling response for sanitization: X bytes`
- `[VALIDATION] Sample clean, skipping full sanitization`

### 2. Monitor CPU Usage

In a separate terminal:
```bash
# Linux
top -p $(pgrep -f mcpgateway)

# Or use htop for better visualization
htop -p $(pgrep -f mcpgateway)

# macOS
top -pid $(pgrep -f mcpgateway)
```

Compare CPU usage with and without optimizations during load tests.

### 3. Check Cache Statistics

You can check metrics endpoint for cache statistics:

```bash
# Check metrics endpoint
curl http://localhost:4444/metrics
```

---

## Troubleshooting

### Issue: No "Skipping" or "Cache Hit" Messages in Logs

**Solution**:
1. Verify `LOG_LEVEL=INFO` in `.env` (or `DEBUG` for even more detail)
2. Restart the gateway
3. Check that `EXPERIMENTAL_VALIDATE_IO=true`
4. Ensure `VALIDATION_CACHE_ENABLED=true` for cache-related logs

### Issue: Cache Not Working

**Solution**:
1. Verify `VALIDATION_CACHE_ENABLED=true`
2. Check that payloads are identical (same JSON, same order)
3. Verify TTL hasn't expired
4. Check logs for cache-related errors

### Issue: Large Payloads Still Being Validated

**Solution**:
1. Verify `VALIDATION_MAX_BODY_SIZE` is set correctly
2. Check payload size: `ls -lh /tmp/large_payload.json`
3. Ensure payload is actually larger than threshold
4. Restart gateway after config changes

### Issue: Endpoints Not Being Skipped

**Solution**:
1. Verify regex patterns in `VALIDATION_SKIP_ENDPOINTS`
2. Test regex patterns independently:
```python
import re
pattern = re.compile(r"^/health$")
print(pattern.match("/health"))  # Should match
```
3. Check for typos in endpoint paths

---

## Expected Performance Improvements

Based on the implementation, you should observe:

| Scenario | Improvement |
|----------|-------------|
| Large request bodies (>1MB) | ~99% faster (skipped) |
| Cached payloads | ~95% faster (cache hit) |
| Large clean responses (>5MB) | ~97% faster (sampled/skipped) |
| Filtered endpoints (/health) | ~98% faster (skipped) |
| Small payloads (<1KB) | No change (always validated) |

---

## Cleanup

After testing, restore production settings:

```bash
# Restore .env from .env.example
cp .env.example .env

# Edit .env with your production values
nano .env

# Restart gateway
make serve
```

---

## Additional Testing Ideas

1. **Stress Test**: Use `locust` or `k6` for more comprehensive load testing
2. **Memory Profiling**: Use `memory_profiler` to check memory usage
3. **Distributed Testing**: Test with multiple gateway instances
4. **Real-World Payloads**: Test with actual production-like data
5. **Security Testing**: Verify that optimizations don't bypass security checks

---

## Questions or Issues?

If you encounter any issues during testing:

1. Check the logs: `tail -f logs/mcpgateway.log`
2. Review configuration: `cat .env | grep VALIDATION`
3. Verify gateway is running: `curl http://localhost:4444/health`
4. Check the documentation: `docs/validation-middleware-performance.md`

For more help, refer to the main documentation or open an issue on GitHub.