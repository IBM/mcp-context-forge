# Observability

ContextForge provides comprehensive observability through multiple complementary systems, allowing you to monitor, trace, and analyze your gateway operations.

## Overview

ContextForge offers three observability approaches:

1. **[Internal Observability](observability/internal.md)** - Built-in database-backed tracing with Admin UI dashboards
2. **[OpenTelemetry Integration](observability/opentelemetry.md)** - Standard distributed tracing to external backends (Phoenix, Jaeger, Tempo, Langfuse)
3. **[Prometheus Metrics](observability/prometheus.md)** - Time-series metrics for monitoring and alerting

## Quick Start Guides

### Internal Observability (Built-in)

Database-backed tracing with Admin UI dashboards:

```bash
# Enable internal observability
export OBSERVABILITY_ENABLED=true

# Run ContextForge
mcpgateway

# View dashboards at http://localhost:4444/admin/observability
```

**Features**: Tools/prompts/resources analytics, trace visualization, performance metrics, error tracking

**[Full Guide →](observability/internal.md)**

### OpenTelemetry (External Backends)

Standard distributed tracing to external observability platforms:

```bash
# Enable OpenTelemetry (disabled by default)
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Run ContextForge
mcpgateway
```

**Supported Backends**: Phoenix, Jaeger, Tempo, Langfuse, Zipkin, Datadog, New Relic, Honeycomb, and any OTLP-compatible backend

**[Full Guide →](observability/opentelemetry.md)**

### Prometheus Metrics

Time-series metrics for monitoring and alerting:

```bash
# Enable Prometheus metrics endpoint
export ENABLE_METRICS=true

# Generate scrape token
export METRICS_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username prometheus@monitoring --exp 0 \
  --secret $JWT_SECRET_KEY)

# Run ContextForge
mcpgateway

# Metrics available at http://localhost:4444/metrics/prometheus
```

**Features**: Request rates, error rates, latency percentiles, custom labels

**[Full Guide →](observability/prometheus.md)**

## Documentation

### Core Guides

- **[Internal Observability](observability/internal.md)** - Built-in tracing, metrics, and Admin UI dashboards
- **[OpenTelemetry Integration](observability/opentelemetry.md)** - External observability with OTLP backends
- **[Prometheus Metrics](observability/prometheus.md)** - Time-series metrics and monitoring

### Backend-Specific Guides

- **[Langfuse Integration](observability/langfuse.md)** - LLM observability, prompt management, and evaluations
- **[Phoenix Integration](observability/phoenix.md)** - AI/LLM-focused observability with Arize Phoenix

### Technical Documentation

- **[OpenTelemetry Architecture](../architecture/observability-otel.md)** - Technical implementation details, W3C trace context, baggage

## Choosing an Approach

### Internal Observability

**Characteristics:**
- Zero external dependencies
- Database storage (SQLite or PostgreSQL)
- Admin UI visualization
- Self-contained deployment

**Common Use Cases:**
- Development and testing environments
- Small to medium deployments
- Scenarios where deployment simplicity is important
- When external observability infrastructure is not available

### OpenTelemetry

**Characteristics:**
- Distributed tracing across multiple services
- Vendor-agnostic standard (OTLP protocol)
- Integration with existing observability platforms
- Advanced APM capabilities

**Common Use Cases:**
- Production environments with multiple services
- Organizations with existing observability infrastructure
- Scenarios requiring vendor flexibility
- High-scale deployments with specialized backends

### Prometheus

**Characteristics:**
- Time-series metrics storage
- Industry-standard exposition format
- Integration with Grafana and alerting systems
- Trend analysis and capacity planning

**Common Use Cases:**
- Production monitoring and alerting
- Long-term trend analysis
- Capacity planning
- Integration with existing Prometheus/Grafana stacks

### Combining Multiple Approaches

ContextForge supports running multiple observability systems simultaneously:

- Internal observability for local debugging alongside external production monitoring
- Different retention policies for different data types
- Redundancy in observability data collection
- Supporting different team tooling preferences

## Comparison Matrix

| Feature | Internal | OpenTelemetry | Prometheus |
|---------|----------|---------------|------------|
| **Storage** | Database (SQLite/PostgreSQL) | External backends | Time-series DB |
| **Setup** | Built-in, zero config | Requires external services | Requires Prometheus server |
| **Cost** | Free, self-hosted | Depends on backend | Free (OSS) or paid (cloud) |
| **Retention** | Configurable in-database | Backend-dependent | Configurable |
| **UI** | Admin UI dashboards | Backend-specific UIs | Grafana dashboards |
| **Use Cases** | Dev, testing, small deployments | Production, microservices | Monitoring, alerting |
| **Standards** | Custom implementation | OpenTelemetry standard | Prometheus exposition format |
| **Integration** | Self-contained | APM ecosystem | Monitoring ecosystem |

## Configuration Reference

### Internal Observability

```bash
OBSERVABILITY_ENABLED=true
OBSERVABILITY_TRACE_HTTP_REQUESTS=true
OBSERVABILITY_TRACE_RETENTION_DAYS=7
OBSERVABILITY_MAX_TRACES=100000
OBSERVABILITY_SAMPLE_RATE=1.0
```

**[Full Configuration →](observability/internal.md#configuration-reference)**

### OpenTelemetry

```bash
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=mcp-gateway
OTEL_SERVICE_VERSION=1.0.0
```

**[Full Configuration →](observability/opentelemetry.md#configuration-reference)**

### Prometheus

```bash
ENABLE_METRICS=true
METRICS_CUSTOM_LABELS="env=production,region=us-east-1"
METRICS_EXCLUDED_HANDLERS="/servers/.*/sse,/static/.*"
```

**[Full Configuration →](observability/prometheus.md#configuration-reference)**

## What Gets Traced

All observability systems capture:

- **Tool invocations** - Full lifecycle with arguments, results, and timing
- **Prompt rendering** - Template processing and message generation
- **Resource fetching** - URI resolution, caching, and content retrieval
- **Gateway federation** - Cross-gateway requests and health checks
- **Plugin execution** - Pre/post hooks if plugins are enabled
- **Errors and exceptions** - Full context and error details

## Production Deployment

### High Availability

For production deployments:

1. **Enable all three systems** for comprehensive observability
2. **Use PostgreSQL** for internal observability storage
3. **Deploy Prometheus** with remote write to long-term storage
4. **Configure OpenTelemetry** to send to production APM
5. **Set appropriate retention** policies for each system

### Example Production Configuration

```bash
# Internal observability (short retention)
OBSERVABILITY_ENABLED=true
OBSERVABILITY_TRACE_RETENTION_DAYS=3
OBSERVABILITY_SAMPLE_RATE=0.1

# OpenTelemetry (production APM)
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector.prod.example.com
OTEL_TRACES_SAMPLER_ARG=0.01

# Prometheus (monitoring)
ENABLE_METRICS=true
METRICS_CUSTOM_LABELS="env=production,region=us-east-1"
METRICS_EXCLUDED_HANDLERS="/health.*,/metrics.*,/static/.*"
```

## Getting Started

1. **Choose an approach**: Review the comparison matrix and use cases above
2. **Follow the quick start**: Use the configuration examples for your chosen system(s)
3. **Configure backends**: See the backend-specific guides for detailed setup instructions
4. **Set up dashboards**: Configure visualization tools (Admin UI, Grafana, or backend-specific UIs)
5. **Configure retention**: Adjust sampling rates and retention policies based on your requirements

## Related Documentation

- [Configuration Reference](configuration.md) - All observability settings
- [Scaling Guide](scale.md) - Production deployment patterns
- [Security Features](../architecture/security-features.md) - Authentication and authorization
- [Admin UI Documentation](ui-customization.md) - Customizing observability dashboards
