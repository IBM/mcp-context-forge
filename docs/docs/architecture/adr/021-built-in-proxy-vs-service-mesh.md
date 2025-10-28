# ADR-0021: Built-in Proxy Capabilities vs Service Mesh

- *Status:* Accepted
- *Date:* 2025-10-27
- *Deciders:* Core Engineering Team

## Context

Modern distributed applications often use service mesh infrastructure (Envoy, Istio, Linkerd) to handle cross-cutting concerns:
- Load balancing and traffic routing
- mTLS and authentication
- Observability (metrics, tracing, logging)
- Rate limiting and circuit breaking
- Request/response transformation
- Compression and caching

ContextForge must support diverse deployment scenarios:
- **Standalone execution**: Single Python module (`python -m mcpgateway`)
- **Serverless platforms**: AWS Lambda, Google Cloud Run, IBM Cloud Code Engine
- **Container orchestration**: Kubernetes, OpenShift
- **Multi-regional deployments**: Cross-region federation
- **Edge deployments**: Minimal resource footprint

We needed to decide whether to:
1. Require external service mesh (Envoy/Istio) for all deployments
2. Build proxy capabilities directly into the application
3. Support both approaches with optional composition

## Decision

We will **embed proxy and gateway capabilities directly into the ContextForge application** with support for optional service mesh composition when needed.

**Built-in capabilities:**
- **MCP-aware routing** - Protocol-specific routing for tools, resources, prompts, servers
- **Response compression** - Brotli, Zstd, GZip middleware (30-70% bandwidth reduction)
- **Caching** - Pluggable cache backend (memory, Redis, database)
- **Observability** - Embedded OpenTelemetry (Prometheus metrics, Jaeger/Zipkin tracing)
- **Authentication** - JWT, Basic Auth, OAuth 2.0/OIDC
- **Rate limiting** - Per-tool and gateway-level rate limits
- **Health checks** - /health (liveness), /ready (readiness)
- **Federation** - mDNS auto-discovery, peer gateway federation

**Service mesh optional:**
- ContextForge works standalone without Envoy/Istio
- Each of the 14 independent modules can integrate with service mesh when needed
- Example: ContextForge translate utility behind Envoy for mTLS

**Key Architectural Decision:**
Application-level intelligence (MCP protocol routing, tool invocation, resource management) is embedded in ContextForge modules, not delegated to infrastructure proxies. Infrastructure concerns (mTLS between all services, canary deployments, complex traffic routing) can optionally be handled by service mesh.

## Consequences

### Positive

- 🎯 **Maximum deployment flexibility** - From `python -m mcpgateway` to multi-regional K8s
- 🚀 **Serverless-native** - Works on Lambda, Cloud Run, Code Engine without infrastructure
- 🐍 **Zero infrastructure dependency** - Runs with SQLite + memory cache
- 🔌 **Modular composition** - 14 independent modules, each can integrate with Envoy independently
- ⚡ **Application-level routing** - MCP-aware, not just HTTP
- 📦 **Embedded observability** - OpenTelemetry built-in, no sidecar required
- 🗜️ **Native compression** - No external proxy needed for bandwidth reduction
- 💰 **Lower operational cost** - No mandatory service mesh infrastructure

### Negative

- 🔧 **Feature overlap** - Some capabilities duplicate what service mesh provides
- 🔄 **Maintenance burden** - Must maintain compression, caching, observability code
- 📚 **Configuration complexity** - More application-level configuration vs. infrastructure

### Neutral

- 🌐 **Optional composition** - Can use both ContextForge + service mesh when needed
- 📊 **Different abstraction level** - Application (MCP) vs. Infrastructure (HTTP/TCP)

## When to Use What

### Use ContextForge Standalone When:

✅ **Lightweight deployments** - Development, testing, single-node production
✅ **Serverless platforms** - AWS Lambda, Google Cloud Run, IBM Cloud Code Engine
✅ **Edge deployments** - Minimal resources, no Kubernetes
✅ **Embedded use cases** - Imported as Python module in other applications
✅ **No existing infrastructure** - Starting fresh without service mesh

### Use Envoy/Istio Service Mesh When:

✅ **Enterprise Kubernetes** - Existing service mesh infrastructure
✅ **Polyglot microservices** - Need unified traffic management across languages
✅ **Advanced traffic routing** - Canary deployments, A/B testing, complex routing rules
✅ **Compliance requirements** - mTLS mandated across all services
✅ **Centralized policy enforcement** - External proxy for all traffic

### Use Both Together When:

✅ **Enterprise Kubernetes with MCP requirements**
  - ContextForge modules handle MCP protocol concerns
  - Envoy/Istio handle infrastructure concerns (mTLS, observability, traffic routing)
  - Example: ContextForge gateway behind Istio ingress with mTLS between services

✅ **Hybrid deployment model**
  - Core gateway in Kubernetes with Istio
  - Standalone utilities (translate, wrapper) on edge devices
  - Each module integrates with Envoy independently as needed

## Architecture Comparison

### Service Mesh Approach (Envoy/Istio)

```
┌─────────────────────────────────────────────┐
│  Client Request                             │
└─────────────┬───────────────────────────────┘
              │
┌─────────────▼───────────────────────────────┐
│  Istio Ingress Gateway (Envoy)              │
│  - mTLS termination                         │
│  - Load balancing                           │
│  - HTTP routing                             │
└─────────────┬───────────────────────────────┘
              │
┌─────────────▼───────────────────────────────┐
│  ContextForge Pod                           │
│  ┌─────────────────────────────────────┐   │
│  │ Envoy Sidecar                       │   │
│  │ - mTLS                               │   │
│  │ - Metrics                            │   │
│  │ - Compression                        │   │
│  └─────────────┬───────────────────────┘   │
│                │                             │
│  ┌─────────────▼───────────────────────┐   │
│  │ ContextForge Gateway                │   │
│  │ - MCP routing                        │   │
│  │ - Tool invocation                    │   │
│  │ - Resource management                │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

**Trade-offs:**
- ✅ Infrastructure-level mTLS, observability, traffic management
- ❌ Additional network hop (sidecar latency)
- ❌ Resource overhead (Envoy sidecar per pod: ~50-100MB memory)
- ❌ Requires Kubernetes + service mesh infrastructure
- ❌ Doesn't work for serverless, standalone, embedded deployments

### ContextForge Built-in Approach

```
┌─────────────────────────────────────────────┐
│  Client Request                             │
└─────────────┬───────────────────────────────┘
              │
┌─────────────▼───────────────────────────────┐
│  ContextForge Gateway                       │
│  - MCP-aware routing                        │
│  - Response compression (Brotli/Zstd/GZip)  │
│  - Caching (memory/Redis/database)          │
│  - OpenTelemetry observability              │
│  - Authentication (JWT/Basic/OAuth)         │
│  - Rate limiting                            │
│  - Tool invocation                          │
│  - Resource management                      │
└─────────────────────────────────────────────┘
```

**Trade-offs:**
- ✅ Zero infrastructure dependency
- ✅ Works standalone, serverless, containers, Kubernetes
- ✅ MCP-aware routing (not just HTTP)
- ✅ Lower latency (no sidecar hop)
- ✅ Lower resource usage (no sidecar overhead)
- ❌ Application must handle cross-cutting concerns
- ❌ No infrastructure-level mTLS (use HTTPS + JWT instead)

### Hybrid Approach (Both Together)

```
┌─────────────────────────────────────────────┐
│  Istio Ingress Gateway                      │
│  - External mTLS                            │
│  - Infrastructure load balancing            │
└─────────────┬───────────────────────────────┘
              │
┌─────────────▼───────────────────────────────┐
│  ContextForge Gateway (no sidecar)          │
│  - MCP routing (application intelligence)   │
│  - Tool invocation                          │
│  - Resource management                      │
│  - Compression + caching (app-level)        │
└─────────────┬───────────────────────────────┘
              │
              ├─ PostgreSQL (via Istio mTLS)
              ├─ Redis (via Istio mTLS)
              └─ MCP Peers (via Istio mTLS)
```

**Trade-offs:**
- ✅ Best of both worlds: MCP intelligence + infrastructure mTLS
- ✅ ContextForge handles application concerns
- ✅ Istio handles infrastructure concerns
- ⚠️ More complex configuration
- ⚠️ Requires understanding both systems

## Modular Composition Example

Each ContextForge module can integrate with Envoy independently:

```yaml
# Example: ContextForge Translate utility behind Envoy for mTLS
apiVersion: v1
kind: Service
metadata:
  name: mcp-translate
spec:
  selector:
    app: mcp-translate
  ports:
    - port: 80
      targetPort: 9000
---
# Envoy handles external mTLS, rate limiting, load balancing
# ContextForge Translate handles MCP protocol bridging (stdio ↔ SSE ↔ HTTP)
```

The `translate` utility has **zero gateway dependencies** and can run:
- Standalone: `python -m mcptranslate --stdio "uvx mcp-server-git" --port 9000`
- Behind Envoy: Envoy terminates mTLS, forwards to ContextForge translate
- In Kubernetes: With or without Istio sidecar

## Why This Decision Matters

**Problem:** Service mesh architectures assume:
- Container infrastructure (no standalone mode)
- Kubernetes control plane (overhead for simple deployments)
- Polyglot microservices (need HTTP-level abstraction)

**Solution:** ContextForge needs to work everywhere:
- **Development:** `python -m mcpgateway` with zero dependencies
- **Serverless:** AWS Lambda without sidecar infrastructure
- **Edge:** Raspberry Pi running standalone utilities
- **Enterprise K8s:** Multi-regional deployment with Istio (optional)

## Implementation Details

**Built-in proxy capabilities implemented in:**
- Response compression: `mcpgateway/main.py:888-907`
- Caching: `mcpgateway/services/cache_service.py`
- Observability: `mcpgateway/observability/` (OpenTelemetry)
- Authentication: `mcpgateway/auth/` (JWT, Basic, OAuth)
- Rate limiting: `mcpgateway/middleware/rate_limit.py`
- Health checks: `GET /health`, `GET /ready`

**Service mesh integration points:**
- Helm chart supports Istio annotations
- Network policies compatible with service mesh
- Prometheus metrics compatible with Istio telemetry
- Can disable built-in compression if Envoy handles it

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Require Envoy/Istio for all deployments** | Breaks standalone, serverless, edge use cases |
| **No proxy capabilities (external only)** | Poor developer experience, incompatible with serverless |
| **Gateway-only mode (no MCP logic)** | Loses MCP-aware routing, tool invocation intelligence |
| **Implement full service mesh in Python** | Duplicates Envoy/Istio, massive scope, poor performance |

## Status

This decision is implemented. ContextForge provides built-in proxy capabilities and optionally integrates with service mesh infrastructure.

## References

- Architecture overview: `docs/docs/architecture/index.md:163-288`
- Compression middleware: `mcpgateway/main.py:888-907`
- Caching backend: ADR-007 (Pluggable Cache Backend)
- Observability: ADR-010 (Observability via Prometheus)
- Scaling guide: `docs/docs/manage/scale.md`
- Modular architecture: ADR-019 (Modular Architecture Split)
