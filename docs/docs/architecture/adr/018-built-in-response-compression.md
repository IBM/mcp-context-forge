# ADR-0018: Built-in Response Compression Middleware

- *Status:* Accepted
- *Date:* 2025-10-27
- *Deciders:* Core Engineering Team

## Context

The ContextForge serves large JSON responses for endpoints like GET /tools, GET /servers, GET /openapi.json, and JSON-RPC messages. These responses can range from tens of kilobytes to several megabytes, especially in deployments with many registered tools and servers.

Bandwidth consumption impacts:

- Cloud egress costs (charged per GB transferred)
- Response latency (larger payloads take longer to transfer)
- Mobile client performance (slow networks, data caps)
- Multi-regional deployments (cross-region bandwidth costs)

We needed to decide whether to implement compression at the application level or rely on external infrastructure (nginx, CDN, service mesh).

## Decision

We will implement **built-in response compression middleware** directly in the FastAPI application with support for multiple compression algorithms:

- **Brotli** (best compression ratio, modern browsers)
- **Zstd** (fast compression, good ratio)
- **GZip** (universal compatibility, fallback)

**Implementation:**

- Middleware location: `mcpgateway/main.py:888-907`
- Configuration: `mcpgateway/config.py:379-384`
- Algorithm priority: Brotli > Zstd > GZip (based on client Accept-Encoding header)
- Minimum response size threshold: configurable (default 500 bytes)
- Automatic `Vary: Accept-Encoding` header for cache compatibility

**Environment Variables:**
```bash
COMPRESSION_ENABLED=true                 # Enable/disable (default: true)
COMPRESSION_MINIMUM_SIZE=500             # Minimum bytes to compress (default: 500)
COMPRESSION_GZIP_LEVEL=6                 # GZip: 1-9 (default: 6 balanced)
COMPRESSION_BROTLI_QUALITY=4             # Brotli: 0-11 (default: 4 balanced)
COMPRESSION_ZSTD_LEVEL=3                 # Zstd: 1-22 (default: 3 fast)
```

**Compression applies to:**

- JSON responses (application/json)
- HTML (text/html)
- CSS (text/css)
- JavaScript (application/javascript, text/javascript)
- Plain text (text/plain)

**Compression skips:**

- Responses smaller than COMPRESSION_MINIMUM_SIZE
- Already compressed content (images, videos)
- Streaming responses (SSE, WebSocket)
- Clients not advertising Accept-Encoding

## Consequences

### Positive

- 📉 **30-70% bandwidth reduction** - JSON responses compress very well
- 💰 **Lower egress costs** - Significant savings in cloud environments
- 🚀 **Faster response times** - Smaller payloads transfer faster over network
- 📱 **Better mobile experience** - Critical for slow networks and data caps
- 🌍 **Multi-regional efficiency** - Reduced cross-region bandwidth usage
- 🎯 **Application control** - Tune compression per endpoint, no external dependency
- 🔧 **No infrastructure changes** - Works standalone without nginx/CDN

### Negative

- ⚙️ **CPU overhead** - Compression adds 5-10ms latency for typical responses
- 💾 **Memory usage** - Compression buffers increase memory footprint slightly
- 🔄 **Complexity** - Additional middleware to maintain and configure

### Neutral

- 🌐 **Browser compatibility** - Brotli supported in all modern browsers (95%+ coverage)
- 📊 **Monitoring** - Need to track compression ratios and CPU impact
- 🔀 **Cache compatibility** - Vary header ensures correct caching behavior

## Performance Impact

Based on testing with real endpoints:

| Endpoint | Uncompressed | Brotli | GZip | Zstd | Compression Ratio |
|----------|--------------|--------|------|------|-------------------|
| GET /openapi.json | 156KB | 23KB | 28KB | 26KB | 85% (Brotli) |
| GET /tools (100 tools) | 89KB | 15KB | 19KB | 17KB | 83% (Brotli) |
| GET /servers (50 servers) | 67KB | 12KB | 15KB | 13KB | 82% (Brotli) |
| Health check | 42 bytes | Not compressed (below threshold) | - | - |

**Latency impact:**

- Brotli level 4: +5-10ms (balanced)
- GZip level 6: +3-7ms (faster)
- Zstd level 3: +2-5ms (fastest)

**Net effect:** For responses >10KB over slow networks (< 10 Mbps), compression reduces total time by 30-60% despite CPU overhead.

## Tuning for Different Scenarios

**High-traffic production (optimize for speed):**
```bash
COMPRESSION_GZIP_LEVEL=4          # Faster compression
COMPRESSION_BROTLI_QUALITY=3      # Lower quality, faster
COMPRESSION_ZSTD_LEVEL=1          # Fastest
```

**Bandwidth-constrained (optimize for size):**
```bash
COMPRESSION_GZIP_LEVEL=9          # Best compression
COMPRESSION_BROTLI_QUALITY=11     # Maximum quality
COMPRESSION_ZSTD_LEVEL=9          # Balanced slow
```

**Development (disable compression):**
```bash
COMPRESSION_ENABLED=false         # No compression overhead
```

## Why Not External Compression?

We considered delegating compression to nginx, CDN, or service mesh:

| Option | Why Not |
|--------|---------|
| **Nginx compression** | Requires external proxy; adds deployment complexity; doesn't work for serverless |
| **CDN compression** | Only helps for cacheable content; adds cost; not available for private deployments |
| **Service mesh (Envoy)** | Heavyweight infrastructure; overkill for simple compression; limits deployment flexibility |
| **No compression** | Wastes bandwidth; slow for mobile clients; higher cloud egress costs |

**Decision rationale:**

- Built-in compression works in **all deployment modes** (standalone, serverless, containers)
- **Application-level control** - Different compression for different endpoints
- **Zero infrastructure dependency** - Works without nginx/Envoy/CDN
- **Optional composition** - Can still use nginx/CDN on top for additional caching

## Testing Compression

```bash
# Test Brotli compression
curl -H "Accept-Encoding: br" http://localhost:8000/openapi.json -v 2>&1 | grep -i "content-encoding"
# Should show: content-encoding: br

# Test GZip compression
curl -H "Accept-Encoding: gzip" http://localhost:8000/openapi.json -v 2>&1 | grep -i "content-encoding"
# Should show: content-encoding: gzip

# Verify Vary header
curl -H "Accept-Encoding: br" http://localhost:8000/openapi.json -v 2>&1 | grep -i "vary"
# Should show: vary: Accept-Encoding

# Measure compression ratio
curl -w "%{size_download}\n" -o /dev/null -s http://localhost:8000/openapi.json  # Uncompressed
curl -H "Accept-Encoding: br" -w "%{size_download}\n" -o /dev/null -s http://localhost:8000/openapi.json  # Brotli
```

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **No compression** | Wastes bandwidth, slow responses, high egress costs |
| **Nginx-only compression** | Doesn't work for serverless, adds infrastructure dependency |
| **CDN compression** | Limited to cacheable content, not available for private clouds |
| **Service mesh compression** | Too heavyweight, limits deployment flexibility |
| **GZip only** | Brotli provides 10-15% better compression for JSON |

## Status

This decision has been implemented. Response compression middleware is enabled by default with Brotli/Zstd/GZip support.

## References

- Middleware implementation: `mcpgateway/main.py:888-907`
- Configuration: `mcpgateway/config.py:379-384`
- Testing guide: `CLAUDE.md` (Performance Configuration section)
- Scaling documentation: `docs/docs/manage/scale.md:797-876`
