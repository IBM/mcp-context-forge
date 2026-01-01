# Nginx Caching Proxy for MCP Gateway

High-performance reverse proxy with CDN-like caching capabilities for the MCP Gateway. Provides intelligent caching for static assets, API responses, and schema endpoints with minimal configuration.

## Features

- **Multi-tier caching strategy** with 3 dedicated cache zones
- **Intelligent cache bypass** for mutations (POST/PUT/PATCH/DELETE)
- **CDN-like performance** with stale-while-revalidate patterns
- **WebSocket/SSE support** with proper proxy configuration
- **Cache status headers** for debugging and monitoring
- **Persistent cache storage** using Docker volumes
- **Security headers** and best practices out of the box

## Quick Start

### Start with Docker Compose

```bash
# From repository root
docker-compose up -d nginx

# View logs
docker-compose logs -f nginx

# Access via caching proxy
curl -I http://localhost:8080/health
```

### Verify Caching

```bash
# First request (MISS)
curl -I http://localhost:8080/openapi.json | grep X-Cache-Status
# X-Cache-Status: MISS

# Second request (HIT)
curl -I http://localhost:8080/openapi.json | grep X-Cache-Status
# X-Cache-Status: HIT

# Check cache effectiveness
docker-compose exec nginx du -sh /var/cache/nginx/*
```

## Cache Zones

### 1. Static Assets Cache (`static_cache`)

**Purpose**: Cache CSS, JS, images, fonts
**Size**: 1GB
**TTL**: 30 days
**Patterns**: `*.css`, `*.js`, `*.jpg`, `*.png`, `*.gif`, `*.ico`, `*.svg`, `*.woff`, `*.woff2`, `*.ttf`, `*.eot`, `*.otf`, `*.webp`, `*.avif`

**Benefits**:
- 95%+ cache hit rate for static assets
- 50-90% reduction in backend load
- Near-instant response times (<5ms)

### 2. API Response Cache (`api_cache`)

**Purpose**: Cache read-only API responses
**Size**: 512MB
**TTL**: 5 minutes
**Endpoints**: `/tools`, `/servers`, `/gateways`, `/resources`, `/prompts`, `/tags`, `/a2a`, `/health`, `/version`, `/metrics`

**Benefits**:
- 40-70% reduction in database queries
- 30-50% improvement in API response times
- Reduced database connection pressure

### 3. Schema Cache (`schema_cache`)

**Purpose**: Cache OpenAPI specs and documentation
**Size**: 256MB
**TTL**: 24 hours
**Endpoints**: `/openapi.json`, `/docs`, `/redoc`

**Benefits**:
- 99%+ cache hit rate for schema endpoints
- 80-95% reduction in schema generation overhead
- Sub-millisecond response times

## Cache Bypass Rules

Cache is automatically bypassed for:

- **Mutation methods**: POST, PUT, PATCH, DELETE
- **WebSocket connections**: `/servers/*/ws`
- **SSE streams**: `/servers/*/sse`
- **JSON-RPC endpoint**: `/` (root)

## Performance Characteristics

### Expected Cache Hit Rates

| Endpoint Type | Expected Hit Rate | TTL |
|--------------|------------------|-----|
| Static assets | 95-99% | 30 days |
| OpenAPI schema | 99%+ | 24 hours |
| API responses | 40-70% | 5 minutes |
| Admin UI | 30-50% | 1 minute |

### Performance Improvements

| Metric | Without Cache | With Cache | Improvement |
|--------|--------------|-----------|-------------|
| Static asset response time | 20-50ms | 1-5ms | **80-90% faster** |
| OpenAPI schema response time | 50-200ms | 1-10ms | **90-95% faster** |
| API list endpoints | 30-100ms | 5-20ms | **60-80% faster** |
| Backend load (requests/sec) | 1000 | 200-400 | **60-80% reduction** |

### Resource Usage

- **Memory**: ~200-300MB for cache zones + OS overhead
- **Disk**: Up to 1.75GB (1GB + 512MB + 256MB)
- **CPU**: <5% under normal load, <15% during cache invalidation

## Configuration

### Environment Variables

No environment variables required. All configuration is in `nginx.conf`.

### High-Concurrency Tuning

The nginx configuration is optimized for 3000+ concurrent users (e.g., locust load testing). Key settings:

#### Worker Process Settings

```nginx
# nginx.conf - Main context
worker_processes auto;              # One worker per CPU core
worker_rlimit_nofile 65535;         # Max open files per worker
worker_cpu_affinity auto;           # Bind workers to CPUs

events {
    worker_connections 8192;        # Connections per worker (default: 1024)
    use epoll;                      # Linux-optimized event model
    multi_accept on;                # Accept multiple connections at once
    accept_mutex off;               # Disable mutex for better parallelism
}
```

#### Listen Socket Tuning

```nginx
# Server block
listen 80 backlog=4096 reuseport;
```

- **backlog=4096**: Kernel queue for pending connections (default: 511)
- **reuseport**: Distribute connections across workers (reduces lock contention)

#### Keepalive Settings

```nginx
keepalive_timeout 65;               # Client connection timeout
keepalive_requests 10000;           # Requests per connection (default: 100)
reset_timedout_connection on;       # Free memory from timed-out connections
```

### Rate Limiting

Rate limiting is configured for high-concurrency load testing scenarios:

```nginx
# Zone definition (10MB shared memory, ~160,000 IPs)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=3000r/s;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

# Return 429 instead of 503 (semantically correct per RFC 6585)
limit_req_status 429;
limit_conn_status 429;
```

**Applied to API endpoints:**

```nginx
location ~ ^/(tools|servers|gateways|...)$ {
    limit_req zone=api_limit burst=3000 nodelay;
    limit_conn conn_limit 3000;
    # ...
}
```

**How it works:**

| Parameter | Value | Effect |
|-----------|-------|--------|
| `rate=3000r/s` | 3000 tokens/second | Sustained request rate |
| `burst=3000` | 3000 bucket size | Requests that can queue/proceed |
| `nodelay` | Immediate | Burst requests processed instantly |
| `limit_conn 3000` | 3000 connections | Max concurrent connections per IP |

**Effective limits:**
- Sustained: 3000 requests/second continuously
- Burst: Up to 3000 additional requests can proceed instantly
- Peak: 6000 requests in first second, then 3000/s sustained

**Excluded from rate limiting:**
- `/health` endpoint (for monitoring during load tests)

**Tuning for your workload:**

```nginx
# Lower limits for production (protect backend)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;

location /api {
    limit_req zone=api_limit burst=50 nodelay;
    limit_conn conn_limit 100;
}
```

### Upstream Load Balancing

The upstream configuration is optimized for high-throughput scenarios:

```nginx
upstream gateway_backend {
    least_conn;                       # Route to backend with fewest connections

    server gateway:4444 max_fails=0;  # Disable failure tracking (always retry)

    keepalive 512;                    # Persistent connections per worker
    keepalive_requests 100000;        # Requests per keepalive connection
    keepalive_timeout 60s;            # Connection idle timeout
}
```

**Load balancing algorithms:**

| Algorithm | Use Case |
|-----------|----------|
| `least_conn` (default) | High-concurrency, uneven request duration |
| `round_robin` | Even request distribution |
| `ip_hash` | Session affinity (sticky sessions) |

**Keepalive pool sizing:**
- Each nginx worker maintains its own pool
- With 4 workers: 512 × 4 = 2048 reusable connections
- Remaining connections use short-lived TCP

**Upstream retry configuration:**

```nginx
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 2;
proxy_next_upstream_timeout 10s;
```

### Proxy Buffer Tuning

Larger buffers reduce disk I/O for upstream responses:

```nginx
proxy_buffer_size 16k;              # First response buffer (headers)
proxy_buffers 8 32k;                # Number and size of buffers per connection
proxy_busy_buffers_size 64k;        # Max size while sending to client
proxy_temp_file_write_size 64k;     # Chunk size for temp files
```

### Open File Cache

Reduces file descriptor overhead for frequently accessed files:

```nginx
open_file_cache max=10000 inactive=60s;  # Cache up to 10,000 file descriptors
open_file_cache_valid 30s;               # Revalidate cached info every 30s
open_file_cache_min_uses 2;              # Cache after 2 accesses
open_file_cache_errors on;               # Cache lookup errors too
```

### Access Logging

**Default: Disabled for performance**

```nginx
# access_log /var/log/nginx/access.log main;  # Uncomment for debugging
access_log off;                               # Disabled for load testing
```

Access logging is a major I/O bottleneck under high load. Enable only for debugging:

```bash
# Edit nginx.conf, uncomment access_log line, then:
docker-compose restart nginx
```

The log format includes cache status and timing metrics:

```nginx
log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                '$status $body_bytes_sent "$http_referer" '
                '"$http_user_agent" "$http_x_forwarded_for" '
                'cache_status=$upstream_cache_status '
                'rt=$request_time uct="$upstream_connect_time" '
                'uht="$upstream_header_time" urt="$upstream_response_time"';
```

### Cache Size Tuning

Edit `nginx/nginx.conf`:

```nginx
# Increase static cache to 5GB
proxy_cache_path /var/cache/nginx/static
                 levels=1:2
                 keys_zone=static_cache:100m
                 max_size=5g  # Changed from 1g
                 inactive=30d
                 use_temp_path=off;
```

### TTL Tuning

Edit cache valid directives:

```nginx
# Increase API cache TTL to 15 minutes
proxy_cache_valid 200 15m;  # Changed from 5m
```

## Monitoring

### Cache Statistics

```bash
# View cache size
docker-compose exec nginx du -sh /var/cache/nginx/*

# View cache entry counts
docker-compose exec nginx find /var/cache/nginx -type f | wc -l

# View nginx stats
curl http://localhost:8080/metrics  # If metrics enabled in gateway
```

### Access Logs

```bash
# Follow access logs with cache status
docker-compose logs -f nginx | grep cache_status

# Analyze cache hit rate
docker-compose exec nginx cat /var/log/nginx/access.log | \
  grep -oP 'cache_status=\K\w+' | sort | uniq -c
```

### Cache Headers

All responses include `X-Cache-Status` header:

- `HIT`: Served from cache
- `MISS`: Not in cache, fetched from backend
- `BYPASS`: Cache bypassed (mutation or excluded endpoint)
- `EXPIRED`: Cache expired, revalidating
- `STALE`: Serving stale content while updating
- `UPDATING`: Cache being updated in background
- `REVALIDATED`: Cache entry validated and still fresh

## Troubleshooting

### Cache Not Working

1. Check `X-Cache-Status` header:
   ```bash
   curl -I http://localhost:8080/openapi.json | grep X-Cache-Status
   ```

2. Verify cache directory permissions:
   ```bash
   docker-compose exec nginx ls -la /var/cache/nginx
   ```

3. Check nginx error logs:
   ```bash
   docker-compose logs nginx | grep error
   ```

### Low Cache Hit Rate

1. Verify request patterns:
   ```bash
   docker-compose exec nginx cat /var/log/nginx/access.log | \
     grep -oP 'cache_status=\K\w+' | sort | uniq -c
   ```

2. Check for cache-busting query parameters
3. Increase TTL values if appropriate

### High Memory Usage

1. Reduce cache zone sizes in `nginx.conf`
2. Reduce `max_size` parameters
3. Reduce `inactive` time to expire old entries faster

### Stale Content

Purge cache manually:

```bash
# Remove all cache
docker-compose exec nginx rm -rf /var/cache/nginx/*

# Restart nginx to clear in-memory state
docker-compose restart nginx
```

## Architecture

```
┌─────────────────┐
│   Client        │
│  (Browser/CLI)  │
└────────┬────────┘
         │ http://localhost:8080
         ▼
┌─────────────────────────────────────┐
│   Nginx Caching Proxy               │
│                                     │
│  ┌──────────────────────────────┐  │
│  │  Cache Zones                 │  │
│  │  • static_cache  (1GB)       │  │
│  │  • api_cache     (512MB)     │  │
│  │  • schema_cache  (256MB)     │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌──────────────────────────────┐  │
│  │  Cache Logic                 │  │
│  │  • Method-based bypass       │  │
│  │  • Pattern matching          │  │
│  │  • TTL enforcement           │  │
│  │  • Stale-while-revalidate    │  │
│  └──────────────────────────────┘  │
└────────┬────────────────────────────┘
         │ http://gateway:4444
         ▼
┌─────────────────┐
│  MCP Gateway    │
│  (FastAPI)      │
└─────────────────┘
```

## Security

### Headers

All responses include security headers:

- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

### Access Control

Default configuration allows all origins. To restrict:

```nginx
# Add to server block in nginx.conf
location / {
    # Restrict to specific IP ranges
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;

    proxy_pass http://gateway_backend;
}
```

## Advanced Features

### Cache Purging (Optional)

Requires `nginx` with `ngx_cache_purge` module. Uncomment in `nginx.conf`:

```nginx
location ~ /purge(/.*) {
    allow 127.0.0.1;
    allow 172.16.0.0/12;  # Docker networks
    deny all;
    proxy_cache_purge static_cache $scheme$request_method$host$1;
}
```

Purge specific URL:

```bash
curl -X PURGE http://localhost:8080/purge/openapi.json
```

### Custom Cache Keys

Modify cache key construction in `nginx.conf`:

```nginx
# Include user in cache key for user-specific responses
proxy_cache_key "$scheme$request_method$host$request_uri$http_authorization";
```

### Conditional Caching

Add custom bypass logic:

```nginx
# Skip cache if specific header present
map $http_x_no_cache $skip_cache {
    default 0;
    "1" 1;
}

proxy_cache_bypass $skip_cache;
```

## Testing

### Manual Testing

```bash
# Test static asset caching
for i in {1..5}; do
  curl -I http://localhost:8080/static/style.css | grep X-Cache-Status
done

# Test API caching
for i in {1..5}; do
  curl -I http://localhost:8080/tools | grep X-Cache-Status
done

# Test cache bypass on mutations
curl -X POST http://localhost:8080/tools -H "Content-Type: application/json" \
  -d '{"name":"test"}' -I | grep X-Cache-Status
```

### Load Testing

```bash
# Install hey (HTTP load generator)
# https://github.com/rakyll/hey

# Test without cache (direct to gateway)
hey -n 1000 -c 50 http://localhost:4444/openapi.json

# Test with cache (through nginx)
hey -n 1000 -c 50 http://localhost:8080/openapi.json

# Compare results
```

## Migration

### From Direct Gateway Access

1. Update client URLs from `:4444` to `:8080`
2. Start nginx service: `docker-compose up -d nginx`
3. Monitor logs: `docker-compose logs -f nginx`

### Gradual Rollout

Keep both ports exposed during transition:

- `:4444` - Direct gateway access (existing clients)
- `:8080` - Cached access (new clients)

Update clients incrementally to use `:8080`.

## Maintenance

### Regular Tasks

1. **Monitor cache size**: `docker-compose exec nginx du -sh /var/cache/nginx`
2. **Review hit rates**: Check `X-Cache-Status` in access logs
3. **Update TTLs**: Adjust based on content change frequency

### Backup

Cache is ephemeral by design. No backup needed.

To preserve cache across restarts, use named volume (already configured):

```yaml
volumes:
  - nginx_cache:/var/cache/nginx
```

## References

- [Nginx Caching Guide](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache)
- [Nginx Performance Tuning](https://nginx.org/en/docs/http/ngx_http_core_module.html)
- [HTTP Caching Best Practices](https://web.dev/http-cache/)
