# RFC 6585 Compliance

ContextForge implements [RFC 6585](https://www.rfc-editor.org/rfc/rfc6585) HTTP status codes to ensure standards-compliant error handling and client interoperability.

## Overview

RFC 6585 defines additional HTTP status codes for specific error conditions:

- **428 Precondition Required** - Server requires conditional request headers
- **429 Too Many Requests** - Rate limiting enforcement
- **431 Request Header Fields Too Large** - Header size validation
- **511 Network Authentication Required** - Captive portal authentication (not applicable to ContextForge)

## 429 Too Many Requests

### Implementation

ContextForge uses 429 responses with RFC-compliant headers for rate limiting across multiple surfaces:

**Middleware**: [`RateLimitMiddleware`](../../../mcpgateway/middleware/rate_limit_middleware.py:71)
**Configuration**: [`config.py`](../../../mcpgateway/config.py:3185-3209)

### Response Headers

Per RFC 6585 § 4 and RFC 9110, 429 responses include:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1234567890
```

### Rate Limit Tiers

| Tier | Endpoints | Default Limit | Burst |
|------|-----------|---------------|-------|
| CRITICAL | `/auth/email/*`, `/auth/sso/*` | 10 req/min | 0 |
| HIGH | `/tokens`, `/oauth`, `/rbac` | 30 req/min | 0 |
| MEDIUM | `/mcp`, `/tools`, `/prompts`, `/resources` | 100 req/min | 20 |
| LOW | `/health`, `/metrics`, `/docs` | 500 req/min | 100 |

### Configuration

```bash
# Enable rate limiting
RATE_LIMITING_ENABLED=true
RATE_LIMITING_REDIS_ENABLED=true

# Tier limits (requests per minute)
RATE_LIMIT_CRITICAL_RPM=10
RATE_LIMIT_HIGH_RPM=30
RATE_LIMIT_MEDIUM_RPM=100
RATE_LIMIT_LOW_RPM=500

# Lockout after excessive violations
RATE_LIMIT_LOCKOUT_ENABLED=true
RATE_LIMIT_LOCKOUT_THRESHOLD=5
RATE_LIMIT_LOCKOUT_DURATION_MINUTES=15
```

### Example Response

```json
{
  "error": "Rate limit exceeded",
  "message": "Maximum 100 requests per minute for MEDIUM tier endpoints.",
  "limit": 100,
  "reset_in_seconds": 60
}
```

### Lockout Response

After exceeding the violation threshold:

```json
{
  "error": "Account locked",
  "message": "Too many rate limit violations. Account locked for 15 minutes. This may indicate suspicious activity on your account.",
  "lockout_duration_minutes": 15,
  "reset_in_seconds": 900
}
```

## 431 Request Header Fields Too Large

### Implementation

ContextForge validates header sizes per RFC 6585 § 5 to prevent resource exhaustion attacks.

**Middleware**: [`HeaderSizeMiddleware`](../../../mcpgateway/middleware/header_size_middleware.py:32)
**Configuration**: [`config.py`](../../../mcpgateway/config.py:3211-3214)

### Validation Rules

1. **Total header size**: All headers combined must not exceed `max_header_total_size_bytes` (default: 16KB)
2. **Individual field size**: Each header field must not exceed `max_header_field_size_bytes` (default: 8KB)
3. **Header count**: Total number of headers must not exceed `max_header_count` (default: 100)

### Response Headers

Per RFC 6585 § 5, 431 responses include:

```http
HTTP/1.1 431 Request Header Fields Too Large
Connection: close
```

The `Connection: close` header is included as recommended by RFC 6585 to prevent further requests on the same connection.

### Configuration

```bash
# Enable header size validation
HEADER_SIZE_VALIDATION_ENABLED=true

# Size limits
MAX_HEADER_TOTAL_SIZE_BYTES=16384  # 16KB
MAX_HEADER_FIELD_SIZE_BYTES=8192   # 8KB
MAX_HEADER_COUNT=100
```

### Example Responses

**Too many headers**:
```json
{
  "error": "Request Header Fields Too Large",
  "message": "Too many header fields (105 > 100)",
  "violation_type": "header_count",
  "limits": {
    "max_total_size_bytes": 16384,
    "max_field_size_bytes": 8192,
    "max_header_count": 100
  }
}
```

**Individual field too large**:
```json
{
  "error": "Request Header Fields Too Large",
  "message": "Header field 'X-Large-Header' exceeds maximum size (9000 > 8192 bytes)",
  "violation_type": "field_size",
  "field_name": "X-Large-Header",
  "limits": {
    "max_total_size_bytes": 16384,
    "max_field_size_bytes": 8192,
    "max_header_count": 100
  }
}
```

**Total size too large**:
```json
{
  "error": "Request Header Fields Too Large",
  "message": "Total header size exceeds maximum (20000 > 16384 bytes)",
  "violation_type": "total_size",
  "limits": {
    "max_total_size_bytes": 16384,
    "max_field_size_bytes": 8192,
    "max_header_count": 100
  }
}
```

## 428 Precondition Required

### Status

**Not currently implemented** - Reserved for future conditional request support.

### Planned Use Cases

- Optimistic locking for resource updates
- Conditional tool execution based on resource state
- ETag-based caching validation

### Future Implementation

When implemented, 428 responses will require clients to include conditional headers:

```http
HTTP/1.1 428 Precondition Required
```

```json
{
  "error": "Precondition Required",
  "message": "This request requires conditional headers",
  "required_headers": ["If-Match", "If-Unmodified-Since"]
}
```

## 511 Network Authentication Required

### Status

**Not applicable** - This status code is for captive portals and network-level authentication, which is outside the scope of ContextForge's application-layer authentication.

## Cross-Surface Consistency

RFC 6585 status codes are consistently applied across all ContextForge surfaces:

### REST API

All REST endpoints respect rate limiting and header size validation:

```bash
curl -X POST https://gateway.example.com/tools/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
# Returns 429 if rate limited
# Returns 431 if headers too large
```

### MCP Protocol

MCP endpoints (`/mcp`, `/mcp/sse`, `/mcp/ws`) enforce the same limits:

```bash
curl -X POST https://gateway.example.com/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
# Returns 429 if rate limited
# Returns 431 if headers too large
```

### A2A (Agent-to-Agent)

A2A endpoints respect rate limiting for agent invocations:

```bash
curl -X POST https://gateway.example.com/a2a/agents/my-agent/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
# Returns 429 if rate limited
```

## Client Handling

### Retry Logic

Clients should implement exponential backoff when receiving 429 responses:

```python
import time
import httpx

def make_request_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        response = httpx.post(url, headers=headers)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"Rate limited. Retrying after {retry_after}s...")
            time.sleep(retry_after)
            continue

        return response

    raise Exception("Max retries exceeded")
```

### Header Size Management

Clients should monitor header sizes to avoid 431 responses:

```python
def validate_headers(headers):
    total_size = sum(len(k) + len(v) + 2 for k, v in headers.items())

    if total_size > 16384:
        raise ValueError(f"Headers too large: {total_size} bytes")

    if len(headers) > 100:
        raise ValueError(f"Too many headers: {len(headers)}")

    for name, value in headers.items():
        field_size = len(name) + len(value) + 2
        if field_size > 8192:
            raise ValueError(f"Header '{name}' too large: {field_size} bytes")
```

## Testing

### Rate Limiting Tests

See [`test_rate_limit_middleware.py`](../../../tests/unit/mcpgateway/middleware/test_rate_limit_middleware.py) for comprehensive test coverage.

### Header Size Tests

See [`test_header_size_middleware.py`](../../../tests/unit/mcpgateway/middleware/test_header_size_middleware.py) for validation tests.

## Security Considerations

### Rate Limiting

- **Multi-dimensional limiting**: Enforced per IP, user, and team
- **Lockout protection**: Temporary account lockout after excessive violations
- **Redis-backed**: Distributed rate limiting across multiple gateway instances
- **Audit logging**: All rate limit violations logged via SecurityLogger

### Header Size Validation

- **DoS prevention**: Prevents resource exhaustion from oversized headers
- **Early rejection**: Headers validated before authentication/authorization
- **Connection closure**: RFC-compliant connection management for 431 responses

## Monitoring

### Metrics

Rate limiting and header validation metrics are exposed via `/metrics`:

```prometheus
# Rate limit violations
http_requests_total{status="429",endpoint="/mcp"}

# Header size rejections
http_requests_total{status="431",endpoint="/tools"}
```

### Logs

Structured logs include RFC 6585 status codes:

```json
{
  "level": "warning",
  "message": "Rate limit exceeded",
  "status_code": 429,
  "client_ip": "203.0.113.1",
  "endpoint": "/mcp",
  "tier": "MEDIUM"
}
```

## References

- [RFC 6585: Additional HTTP Status Codes](https://www.rfc-editor.org/rfc/rfc6585)
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [MCP Specification](https://developer.ibm.com/tutorials/awb-handle-remote-tool-calling-model-context-protocol/)
