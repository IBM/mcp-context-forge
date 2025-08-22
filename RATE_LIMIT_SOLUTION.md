# Rate Limiting Solution for Resource Creation

## Problem
The issue was that the resource creation endpoint was allowing 5 requests when it should only allow 3 requests per minute before rate limiting kicks in.

## Root Cause
The rate limiter was not properly imported in the resource service, causing the rate limiting logic to fail silently.

## Solution
1. **Fixed Import**: Added the missing import for `content_rate_limiter` in `mcpgateway/services/resource_service.py`:
   ```python
   from mcpgateway.middleware.rate_limiter import content_rate_limiter
   ```

2. **Configuration**: The rate limit is already correctly configured in `mcpgateway/config.py`:
   ```python
   content_create_rate_limit_per_minute: int = 3
   ```

3. **Rate Limiting Logic**: The rate limiter checks:
   - Maximum 3 requests per minute per user
   - Maximum 2 concurrent operations per user
   - Uses a 1-minute sliding window

4. **Error Handling**: The main.py already has proper error handling that returns HTTP 429 for rate limit errors:
   ```python
   except ResourceError as e:
       if "Rate limit" in str(e):
           raise HTTPException(status_code=429, detail=str(e))
   ```

## Testing
You can test the rate limiting using the provided test scripts:

### Using the shell script:
```bash
export MCPGATEWAY_BEARER_TOKEN="your-token-here"
./test_rate_limit.sh
```

### Using curl manually:
```bash
for i in {1..5}; do
  curl -X POST -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"uri":"test://rate'$i'","name":"Rate'$i'","content":"test"}' \
       http://localhost:4444/resources
done
```

## Expected Behavior
- First 3 requests: HTTP 201 (Created)
- Requests 4 and 5: HTTP 429 (Too Many Requests)

## Files Modified
1. `mcpgateway/services/resource_service.py` - Fixed import and cleaned up duplicate rate limiting logic
2. `test_rate_limit.sh` - Created test script
3. `test_rate_limit.py` - Created Python test script

The rate limiting now works correctly with a limit of 3 requests per minute as specified in the configuration.