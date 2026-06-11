# RFC 6585 Phase 2: Conditional Request Validation (428 Precondition Required)

## Overview

ContextForge implements RFC 6585 Phase 2 conditional request validation to prevent **lost updates** in concurrent modification scenarios. This feature uses ETags (Entity Tags) with optimistic locking to ensure that clients cannot accidentally overwrite changes made by other clients.

## Problem Statement

### The Lost Update Problem

In a multi-client environment, concurrent modifications can result in data loss:

```
Time    Client A                    Client B                    Database
----    ---------                   ---------                   --------
T1      GET /servers/123            -                          version=1
        (receives v1)
T2      -                           GET /servers/123           version=1
                                    (receives v1)
T3      PUT /servers/123            -                          version=2
        (updates to v2) ✅
T4      -                           PUT /servers/123           version=2
                                    (overwrites A's changes)   ❌ LOST UPDATE
```

**Result:** Client B unknowingly destroys Client A's changes.

### Solution: Conditional Requests with ETags

ContextForge now enforces conditional requests for all PUT/PATCH/DELETE operations:

```
Time    Client A                    Client B                    Database
----    ---------                   ---------                   --------
T1      GET /servers/123            -                          version=1
        ETag: W/"123-1"
T2      -                           GET /servers/123           version=1
                                    ETag: W/"123-1"
T3      PUT /servers/123            -                          version=2
        If-Match: W/"123-1" ✅
        (updates to v2)
T4      -                           PUT /servers/123           version=2
                                    If-Match: W/"123-1"
                                    ❌ 412 Precondition Failed
                                    (client must refresh)
```

**Result:** Client B is notified of the conflict and must refresh before updating.

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Enable conditional request validation (opt-in)
CONDITIONAL_REQUESTS_ENABLED=true

# HTTP methods that require conditional headers
CONDITIONAL_REQUESTS_REQUIRED_METHODS=PUT,PATCH,DELETE

# Paths exempt from validation
CONDITIONAL_REQUESTS_EXEMPT_PATHS=/health,/metrics,/auth/,/admin/login,/admin/logout

# Require ETag-based validation (recommended)
CONDITIONAL_REQUESTS_REQUIRE_ETAG=true
```

### Feature Flags

| Setting | Default | Description |
|---------|---------|-------------|
| `CONDITIONAL_REQUESTS_ENABLED` | `false` | Master enable/disable switch |
| `CONDITIONAL_REQUESTS_REQUIRED_METHODS` | `["PUT", "PATCH", "DELETE"]` | HTTP methods requiring If-Match |
| `CONDITIONAL_REQUESTS_EXEMPT_PATHS` | `["/health", "/metrics", ...]` | Paths that bypass validation |
| `CONDITIONAL_REQUESTS_REQUIRE_ETAG` | `true` | Enforce ETag format validation |

## ETag Format

ContextForge uses **weak ETags** for database resources:

```
W/"<resource_id>-<version>"
```

Examples:
- `W/"abc123-5"` - Server with ID `abc123`, version 5
- `W/"tool-xyz-42"` - Tool with ID `tool-xyz`, version 42

**Why weak ETags?**
- Indicate semantic equivalence (not byte-for-byte)
- More efficient for database-backed resources
- Standard pattern for RESTful APIs

## HTTP Status Codes

### 428 Precondition Required

Returned when a client attempts PUT/PATCH/DELETE without an `If-Match` header.

**Request:**
```http
PUT /servers/abc123 HTTP/1.1
Content-Type: application/json

{
  "name": "Updated Server"
}
```

**Response:**
```http
HTTP/1.1 428 Precondition Required
Content-Type: application/json

{
  "error": "Precondition Required",
  "message": "This request requires an If-Match header to prevent concurrent modifications",
  "required_headers": ["If-Match"],
  "resource": "/servers/abc123",
  "documentation": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/If-Match",
  "rfc": "https://datatracker.ietf.org/doc/html/rfc6585#section-3"
}
```

### 412 Precondition Failed

Returned when the `If-Match` header contains a stale ETag (version mismatch).

**Request:**
```http
PUT /servers/abc123 HTTP/1.1
If-Match: W/"abc123-5"
Content-Type: application/json

{
  "name": "Updated Server"
}
```

**Response (when current version is 6):**
```http
HTTP/1.1 412 Precondition Failed
Content-Type: application/json
ETag: W/"abc123-6"

{
  "error": "Precondition Failed",
  "message": "The resource has been modified by another client",
  "current_etag": "W/\"abc123-6\"",
  "resource": "/servers/abc123",
  "documentation": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/412"
}
```

## Client Workflow

### Basic Flow

1. **GET the resource** to obtain current state and ETag
2. **Make modifications** to your local copy
3. **PUT/PATCH/DELETE** with `If-Match` header
4. **Handle responses**:
   - 200 OK → Success
   - 412 Precondition Failed → Refresh and retry
   - 428 Precondition Required → Missing If-Match header

### Python Example

```python
import requests

BASE_URL = "http://localhost:4444"
headers = {"Authorization": "Bearer <token>"}

# Step 1: Get current resource
response = requests.get(f"{BASE_URL}/servers/abc123", headers=headers)
server = response.json()
current_version = server["version"]

# Generate ETag
etag = f'W/"{server["id"]}-{current_version}"'

# Step 2: Modify resource
server["name"] = "Updated Server Name"

# Step 3: Update with If-Match header
update_headers = {
    **headers,
    "If-Match": etag
}

response = requests.put(
    f"{BASE_URL}/servers/abc123",
    json=server,
    headers=update_headers
)

# Step 4: Handle response
if response.status_code == 200:
    print("✅ Update successful")
elif response.status_code == 412:
    print("❌ Resource was modified by another client")
    print(f"Current ETag: {response.json()['current_etag']}")
    print("Please refresh and try again")
elif response.status_code == 428:
    print("❌ Missing If-Match header")
```

### curl Example

```bash
# Step 1: Get current resource and extract version
RESPONSE=$(curl -s -H "Authorization: Bearer <token>" \
  http://localhost:4444/servers/abc123)

VERSION=$(echo $RESPONSE | jq -r '.version')
ID=$(echo $RESPONSE | jq -r '.id')
ETAG="W/\"${ID}-${VERSION}\""

# Step 2: Update with If-Match header
curl -X PUT \
  -H "Authorization: Bearer <token>" \
  -H "If-Match: ${ETAG}" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Server", "endpoint_url": "http://new-url.com"}' \
  http://localhost:4444/servers/abc123
```

## Affected Resources

Conditional request validation applies to these resources:

| Resource | Endpoint Pattern | Version Column | ETag Support |
|----------|------------------|----------------|--------------|
| Servers | `/servers/{id}` | ✅ | ✅ |
| Gateways | `/gateways/{id}` | ✅ | ✅ |
| Tools | `/tools/{id}` | ✅ | ✅ |
| Resources | `/resources/{id}` | ✅ | ✅ |
| Prompts | `/prompts/{id}` | ✅ | ✅ |
| A2A Agents | `/a2a/{id}` | ✅ | ✅ |

## Advanced Features

### Wildcard ETag

Use `If-Match: *` to match any version (update regardless of current state):

```http
PUT /servers/abc123 HTTP/1.1
If-Match: *
Content-Type: application/json

{
  "name": "Force Update"
}
```

⚠️ **Warning:** Bypasses conflict detection. Use only for administrative overrides.

### Multiple ETags

Provide multiple ETags to match against:

```http
PUT /servers/abc123 HTTP/1.1
If-Match: W/"abc123-5", W/"abc123-6", W/"abc123-7"
Content-Type: application/json

{
  "name": "Updated Server"
}
```

Request succeeds if **any** ETag matches the current version.

### Exempt Paths

These paths bypass conditional request validation:

- `/health` - Health checks
- `/metrics` - Metrics endpoints
- `/auth/*` - Authentication endpoints
- `/admin/login` - Admin login
- `/admin/logout` - Admin logout

Configure additional exempt paths via `CONDITIONAL_REQUESTS_EXEMPT_PATHS`.

## Monitoring & Observability

### Security Events

All conditional request violations are logged via SecurityLogger:

```json
{
  "event_type": "authorization_failure",
  "severity": "medium",
  "category": "conditional_request",
  "user_email": "admin@example.com",
  "client_ip": "192.168.1.100",
  "description": "Conditional request missing If-Match header",
  "threat_score": 0.3,
  "context": {
    "endpoint": "/servers/abc123",
    "method": "PUT",
    "if_match_header": null
  }
}
```

### Metrics

Monitor these patterns:
- **428 response rate** - Clients not sending If-Match headers
- **412 response rate** - Concurrent modification conflicts
- **High 412 rate on specific resources** - Hot-spot contention

## Migration Guide

### Enabling the Feature

1. **Announce to API consumers** - Provide 2-week notice
2. **Update client code** - Add If-Match header support
3. **Enable in staging** - Test with real traffic
4. **Enable in production** - Monitor 428/412 rates
5. **Remove legacy paths** - After client migration

### Gradual Rollout

**Option 1: Path-based exemptions**
```bash
# Initially exempt all paths
CONDITIONAL_REQUESTS_EXEMPT_PATHS=/servers,/gateways,/tools,/resources,/prompts

# Gradually remove exemptions
CONDITIONAL_REQUESTS_EXEMPT_PATHS=/gateways,/tools,/resources,/prompts
CONDITIONAL_REQUESTS_EXEMPT_PATHS=/tools,/resources,/prompts
CONDITIONAL_REQUESTS_EXEMPT_PATHS=/resources,/prompts
CONDITIONAL_REQUESTS_EXEMPT_PATHS=
```

**Option 2: Method-based rollout**
```bash
# Start with DELETE only
CONDITIONAL_REQUESTS_REQUIRED_METHODS=DELETE

# Add PUT
CONDITIONAL_REQUESTS_REQUIRED_METHODS=DELETE,PUT

# Add PATCH
CONDITIONAL_REQUESTS_REQUIRED_METHODS=DELETE,PUT,PATCH
```

## Troubleshooting

### Client receives 428 responses

**Cause:** Client not sending `If-Match` header

**Solution:**
```python
# Add If-Match header to PUT/PATCH/DELETE requests
headers["If-Match"] = f'W/"{resource_id}-{version}"'
```

### Client receives frequent 412 responses

**Cause:** High concurrent modification rate on resource

**Solutions:**
1. **Retry with exponential backoff**
2. **Implement client-side locking**
3. **Reduce modification frequency**
4. **Use batch operations** (when available)

### Wildcard ETag rejected

**Cause:** Wildcard ETags bypass conflict detection

**Solution:** Only use `If-Match: *` for administrative overrides where conflict detection is not needed.

## RFC Compliance

ContextForge implements:
- **RFC 6585 Section 3** - 428 Precondition Required status code
- **RFC 7232 Section 2.3** - ETag header field
- **RFC 7232 Section 3.1** - If-Match conditional header

## Security Considerations

### Audit Trail

All conditional request violations are logged with:
- User identity
- Client IP address
- Resource path
- Request method
- ETag provided (if any)
- Timestamp

### Threat Detection

High rates of 428/412 responses may indicate:
- **Malicious clients** - Attempting unauthorized modifications
- **Misconfigured clients** - Not implementing conditional requests
- **DoS attempts** - Flooding with invalid requests

### Best Practices

1. **Enable audit logging** - Track all 428/412 responses
2. **Monitor trends** - Alert on abnormal 412 rates
3. **Rate limit 428/412** - Prevent abuse
4. **Client validation** - Verify If-Match format before proxying

## Performance Impact

### Minimal Overhead

- **Database query**: One additional version lookup per PUT/PATCH/DELETE
- **ETag generation**: O(1) string formatting
- **Response time**: < 1ms additional latency

### Caching Benefits

Weak ETags enable HTTP caching:
```http
GET /servers/abc123 HTTP/1.1
If-None-Match: W/"abc123-5"

→ 304 Not Modified (if version unchanged)
```

## References

- [RFC 6585 - HTTP Status Code 428](https://datatracker.ietf.org/doc/html/rfc6585#section-3)
- [RFC 7232 - HTTP Conditional Requests](https://datatracker.ietf.org/doc/html/rfc7232)
- [MDN - If-Match Header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/If-Match)
- [MDN - 428 Precondition Required](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/428)
- [MDN - 412 Precondition Failed](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/412)
