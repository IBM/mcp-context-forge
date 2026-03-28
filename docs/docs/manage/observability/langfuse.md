# Langfuse Integration Guide

[Langfuse](https://langfuse.com) provides LLM observability for ContextForge, offering trace visualization, prompt management, evaluations, cost tracking, and analytics for AI-powered applications.

## Why Langfuse?

Langfuse is purpose-built for LLM application observability:

- **Trace visualization** - End-to-end request traces with latency breakdown
- **Prompt management** - Version, test, and deploy prompts
- **Evaluations** - Score traces with custom or built-in evaluators
- **Cost tracking** - Token usage and cost analytics per model
- **User analytics** - Session-level and user-level aggregations
- **Datasets** - Create test datasets from production traces
- **OpenTelemetry native** - Receives traces via standard OTLP/HTTP

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Start ContextForge with Langfuse
make langfuse-up

# Or manually:
docker compose -f docker-compose.yml \
               -f docker-compose.with-langfuse.yml up -d

# View Langfuse UI
open http://localhost:3100
# Login: admin@example.com / changeme
```

### Option 2: Standalone Langfuse

If you already have a Langfuse instance running (self-hosted or cloud), configure ContextForge to send traces to it:

```bash
# Configure ContextForge OTEL to point at your Langfuse instance
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http
export OTEL_EXPORTER_OTLP_ENDPOINT=http://your-langfuse:3000/api/public/otel/v1/traces
export OTEL_SERVICE_NAME=contextforge-gateway

# Auth: base64-encode your Langfuse project keys
AUTH=$(echo -n "pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY" | base64)
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $AUTH"

# Start ContextForge
mcpgateway
```

### Option 3: Langfuse Cloud

For managed deployments, use [Langfuse Cloud](https://cloud.langfuse.com):

```bash
# Get API keys from your Langfuse Cloud project settings
AUTH=$(echo -n "pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY" | base64)

export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $AUTH"
export OTEL_SERVICE_NAME=contextforge-gateway
```

## Architecture

The integration uses OpenTelemetry (OTLP/HTTP) to send traces from ContextForge to Langfuse:

```
ContextForge Gateway
  |
  | OTLP/HTTP (protobuf)
  v
Langfuse Web (port 3100)
  |
  +-- PostgreSQL (operational data, migrations)
  +-- ClickHouse (OLAP trace analytics)
  +-- MinIO (S3-compatible event/media storage)
  +-- Redis (caching, queues)
  |
  v
Langfuse Worker (async processing)
```

!!! info "OTLP Protocol"
    Langfuse only supports OTLP over HTTP (not gRPC). The Docker Compose overlay sets `OTEL_EXPORTER_OTLP_PROTOCOL=http` automatically.

## Docker Compose Configuration

The `docker-compose.with-langfuse.yml` overlay provides:

- **langfuse-web** - UI, API, and OTLP ingestion endpoint (port 3100)
- **langfuse-worker** - Async event processing (ClickHouse ingestion, evaluations)
- **langfuse-db** - Dedicated PostgreSQL instance (separate from ContextForge's)
- **langfuse-clickhouse** - OLAP analytics database
- **langfuse-minio** - S3-compatible object storage
- **langfuse-cache** - Dedicated Redis with auth

The gateway is overridden to:

```yaml
gateway:
  environment:
    - OTEL_ENABLE_OBSERVABILITY=true
    - OTEL_TRACES_EXPORTER=otlp
    - OTEL_EXPORTER_OTLP_PROTOCOL=http
    - OTEL_EXPORTER_OTLP_ENDPOINT=http://langfuse-web:3000/api/public/otel/v1/traces
    - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(pk:sk)>
    - OTEL_SERVICE_NAME=contextforge-gateway
```

!!! note "Separate Infrastructure"
    Langfuse uses its own PostgreSQL, Redis, ClickHouse, and MinIO instances. This avoids coupling with ContextForge's databases and allows independent lifecycle management.

## What Gets Traced

ContextForge instruments these operations with OpenTelemetry spans:

| Operation | Span Name | Attributes |
|-----------|-----------|------------|
| Tool invocation | `tool.invoke` | tool name, gateway, duration, status |
| Prompt rendering | `prompt.render` | prompt name, template vars |
| Resource fetch | `resource.read` | resource URI, MIME type |
| Gateway health check | `gateway.health_check_batch` | gateway count, check type |

Each span includes:

- Correlation ID for request tracing
- Service name and deployment environment
- Error details on failure (message, exception)

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make langfuse-up` | Start Langfuse + ContextForge with OTEL enabled |
| `make langfuse-down` | Stop the Langfuse stack |
| `make langfuse-status` | Show Langfuse service status |
| `make langfuse-logs` | Tail Langfuse logs |
| `make langfuse-clean` | Stop and remove all Langfuse data (volumes) |
| `make langfuse-monitoring-up` | Start Langfuse alongside Grafana/Prometheus/Tempo |
| `make langfuse-monitoring-down` | Stop Langfuse + monitoring stack |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LANGFUSE_PORT` | Host port for Langfuse UI | `3100` |
| `LANGFUSE_PUBLIC_KEY` | API public key | `pk-lf-contextforge` |
| `LANGFUSE_SECRET_KEY` | API secret key | `sk-lf-contextforge` |
| `LANGFUSE_OTEL_AUTH` | Base64-encoded `pk:sk` for OTEL header | auto-generated |
| `LANGFUSE_INIT_USER_EMAIL` | Admin user email | `admin@example.com` |
| `LANGFUSE_INIT_USER_PASSWORD` | Admin user password | `changeme` |
| `LANGFUSE_POSTGRES_PASSWORD` | Langfuse DB password | `langfuse` |
| `LANGFUSE_CLICKHOUSE_USER` | ClickHouse username | `clickhouse` |
| `LANGFUSE_CLICKHOUSE_PASSWORD` | ClickHouse password | `clickhouse` |
| `LANGFUSE_MINIO_USER` | MinIO access key | `minio` |
| `LANGFUSE_MINIO_PASSWORD` | MinIO secret key | `miniosecret` |
| `LANGFUSE_REDIS_AUTH` | Redis password | `langfuse-redis-secret` |

!!! warning "Production Credentials"
    The default credentials are for development only. Override all passwords and keys via `.env` or environment variables before deploying to production.

## Using the Langfuse UI

### Viewing Traces

1. Open [http://localhost:3100](http://localhost:3100)
2. Log in with `admin@example.com` / `changeme`
3. Navigate to **Traces** in the sidebar
4. Each tool invocation appears as a trace with:
    - Span name (e.g., `tool.invoke`)
    - Duration and latency
    - Service attributes (deployment environment, namespace)
    - Error details if the invocation failed

### Creating Evaluations

Langfuse supports scoring traces with evaluators:

1. Navigate to **Evaluations** in the sidebar
2. Create custom evaluators for response quality, latency, or cost
3. Evaluators can run automatically on new traces

### Prompt Management

Langfuse can version and manage prompts:

1. Navigate to **Prompts** in the sidebar
2. Create prompt templates with variables
3. Track which prompt versions produce the best results

## Combined with Monitoring Stack

To run Langfuse alongside the full Grafana/Prometheus/Tempo monitoring stack:

```bash
make langfuse-monitoring-up
```

This starts:

- **Langfuse** at `http://localhost:3100` (LLM-specific analytics)
- **Grafana** at `http://localhost:3000` (infrastructure metrics and dashboards)
- **Prometheus** at `http://localhost:9090` (metrics collection)
- **Tempo** at `http://localhost:3200` (distributed tracing)

!!! tip "Dual Trace Export"
    By default, OTEL traces go to Langfuse only. To send traces to both Langfuse and Tempo simultaneously, deploy an [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) with a fan-out pipeline.

## Production Deployment

### Security Hardening

1. **Change all default credentials** in `.env`:
    ```bash
    LANGFUSE_PUBLIC_KEY=pk-lf-<random>
    LANGFUSE_SECRET_KEY=sk-lf-<random>
    LANGFUSE_INIT_USER_PASSWORD=<strong-password>
    LANGFUSE_POSTGRES_PASSWORD=<strong-password>
    LANGFUSE_ENCRYPTION_KEY=<64-hex-chars>
    LANGFUSE_NEXTAUTH_SECRET=<random-string>
    ```

2. **Regenerate the OTEL auth header**:
    ```bash
    LANGFUSE_OTEL_AUTH=$(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)
    ```

3. **Enable TLS** for the Langfuse endpoint in production.

### Kubernetes

Langfuse provides a [Helm chart](https://langfuse.com/docs/deployment/self-host/kubernetes) for production Kubernetes deployments. Configure ContextForge's OTEL exporter to point at the Langfuse service endpoint.

### Resource Requirements

| Service | CPU (min) | Memory (min) | Storage |
|---------|-----------|-------------|---------|
| langfuse-web | 0.5 core | 256 MB | - |
| langfuse-worker | 0.5 core | 256 MB | - |
| langfuse-db | 0.25 core | 256 MB | 1 GB+ |
| langfuse-clickhouse | 0.5 core | 512 MB | 5 GB+ |
| langfuse-minio | 0.25 core | 128 MB | 1 GB+ |
| langfuse-cache | 0.1 core | 64 MB | - |

## Troubleshooting

### No Traces Appearing

1. **Check OTEL is enabled** in the gateway:
    ```bash
    docker exec <gateway-container> env | grep OTEL_
    ```
    Verify `OTEL_ENABLE_OBSERVABILITY=true` and `OTEL_EXPORTER_OTLP_PROTOCOL=http`.

2. **Check the gateway logs** for export errors:
    ```bash
    docker compose -f docker-compose.yml \
      -f docker-compose.with-langfuse.yml logs gateway | grep -i otel
    ```

3. **Check Langfuse health**:
    ```bash
    curl http://localhost:3100/api/public/health
    # Expected: {"status":"OK","version":"3.x.x"}
    ```

4. **Verify traces via API**:
    ```bash
    AUTH=$(echo -n "pk-lf-contextforge:sk-lf-contextforge" | base64)
    curl -H "Authorization: Basic $AUTH" \
      http://localhost:3100/api/public/traces
    ```

### Export Timeout Errors

If you see "Failed to export span batch due to timeout" in gateway logs:

- This is normal during startup while Langfuse initializes
- If persistent, check that `langfuse-web` is healthy and reachable from the gateway container

### S3 Upload Errors

If Langfuse logs show "Failed to upload JSON to S3":

- Verify MinIO is running: `docker compose exec langfuse-minio mc ls local/langfuse`
- Check that service names use hyphens (not underscores) - the AWS SDK rejects hostnames with underscores

## Next Steps

- [OpenTelemetry Overview](observability.md) - All supported backends
- [Phoenix Integration](phoenix.md) - Alternative AI observability backend
- [Internal Observability](internal-observability.md) - Built-in database-backed observability
- [Langfuse Documentation](https://langfuse.com/docs) - Full Langfuse documentation
