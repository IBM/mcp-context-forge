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
# Configure the Langfuse project keys used by the gateway exporter
# LANGFUSE_PUBLIC_KEY=pk-lf-<set-a-unique-public-key>
# LANGFUSE_SECRET_KEY=sk-lf-<set-a-unique-secret-key>

# Start ContextForge with Langfuse
make langfuse-up

# Or manually:
docker compose -f docker-compose.yml \
               -f docker-compose.with-langfuse.yml up -d

# View Langfuse UI
open http://localhost:3100
# Login with LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD
# Defaults: admin@example.com / changeme unless you override them

# Verify that fresh MCP traffic lands in Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-contextforge \
LANGFUSE_SECRET_KEY=sk-lf-contextforge \
uv run pytest tests/live_gateway/mcp/test_langfuse_traces.py -q
```

### Option 2: Standalone Langfuse

If you already have a Langfuse instance running (self-hosted or cloud), configure ContextForge to send traces to it:

```bash
# Configure ContextForge OTEL to point at your Langfuse instance
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export LANGFUSE_OTEL_ENDPOINT=http://your-langfuse:3000/api/public/otel/v1/traces
export OTEL_SERVICE_NAME=contextforge-gateway

# Preferred: configure Langfuse project keys and let the gateway derive OTLP auth
export LANGFUSE_PUBLIC_KEY=pk-lf-YOUR_PUBLIC_KEY
export LANGFUSE_SECRET_KEY=sk-lf-YOUR_SECRET_KEY

# Optional compatibility override if you already have a pre-encoded header value
# export LANGFUSE_OTEL_AUTH=$(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)
# export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $LANGFUSE_OTEL_AUTH"

# Start ContextForge
mcpgateway
```

### Option 3: Langfuse Cloud

For managed deployments, use [Langfuse Cloud](https://cloud.langfuse.com):

```bash
# Get API keys from your Langfuse Cloud project settings
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export LANGFUSE_OTEL_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
export LANGFUSE_PUBLIC_KEY=pk-lf-YOUR_PUBLIC_KEY
export LANGFUSE_SECRET_KEY=sk-lf-YOUR_SECRET_KEY
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

ContextForge only needs the Langfuse OTLP endpoint and project credentials. The self-hosted Langfuse database, cache, ClickHouse, and MinIO passwords are internal to the compose overlay and are not consumed by the gateway runtime.

The gateway is overridden to:

```yaml
gateway:
  environment:
    - OTEL_ENABLE_OBSERVABILITY=true
    - OTEL_TRACES_EXPORTER=otlp
    - OTEL_EXPORTER_OTLP_PROTOCOL=http
    - LANGFUSE_OTEL_ENDPOINT=http://langfuse-web:3000/api/public/otel/v1/traces
    - LANGFUSE_PUBLIC_KEY=<your-project-public-key>
    - LANGFUSE_SECRET_KEY=<your-project-secret-key>
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
| `make langfuse-reset-data` | Stop the Langfuse stack and remove only Langfuse data volumes |
| `make langfuse-clean-including-contextforge` | Stop the combined stack and remove Langfuse and ContextForge volumes |
| `make langfuse-monitoring-up` | Start Langfuse alongside Grafana/Prometheus/Tempo |
| `make langfuse-monitoring-down` | Stop Langfuse + monitoring stack |

`make langfuse-clean` was removed because the name was ambiguous. Use one of the explicit targets above depending on whether you want to preserve ContextForge data.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LANGFUSE_PORT` | Host port for Langfuse UI | `3100` |
| `LANGFUSE_WORKER_PORT` | Localhost-only Langfuse worker metrics port | `3130` |
| `LANGFUSE_OTEL_ENDPOINT` | Langfuse OTLP/HTTP traces endpoint | local compose service |
| `LANGFUSE_PUBLIC_KEY` | API public key | `pk-lf-contextforge` in the local compose overlay |
| `LANGFUSE_SECRET_KEY` | API secret key | `sk-lf-contextforge` in the local compose overlay |
| `LANGFUSE_OTEL_AUTH` | Optional base64-encoded `pk:sk` OTLP auth override | unset |
| `LANGFUSE_INIT_USER_EMAIL` | Admin user email | `admin@example.com` |
| `LANGFUSE_INIT_USER_PASSWORD` | Optional local overlay admin password override | `changeme` |
| `LANGFUSE_POSTGRES_PASSWORD` | Optional local overlay DB password override | local compose default |
| `LANGFUSE_CLICKHOUSE_USER` | ClickHouse username | `clickhouse` |
| `LANGFUSE_CLICKHOUSE_PASSWORD` | Optional local overlay ClickHouse password override | local compose default |
| `LANGFUSE_MINIO_USER` | MinIO access key | `minio` |
| `LANGFUSE_MINIO_PASSWORD` | Optional local overlay MinIO password override | local compose default |
| `LANGFUSE_REDIS_AUTH` | Optional local overlay Redis password override | local compose default |
| `LANGFUSE_NEXTAUTH_SECRET` | Optional local overlay NextAuth secret override | local compose default |
| `LANGFUSE_SALT` | Optional local overlay application salt override | local compose default |
| `LANGFUSE_ENCRYPTION_KEY` | Optional local overlay encryption key override | local compose default |
| `OTEL_EMIT_LANGFUSE_ATTRIBUTES` | Force-enable or disable Langfuse-specific span attributes | auto in normal runtime, `true` in local Langfuse compose overlay |
| `OTEL_CAPTURE_IDENTITY_ATTRIBUTES` | Force-enable or disable user/team identity enrichment | auto in normal runtime, `true` in local Langfuse compose overlay |
| `OTEL_CAPTURE_INPUT_SPANS` | Comma-separated allowlist of span names allowed to capture observation input payloads | empty in normal runtime, `tool.invoke,prompt.render,llm.proxy,a2a.invoke` in local Langfuse compose overlay |
| `OTEL_CAPTURE_OUTPUT_SPANS` | Comma-separated allowlist of span names allowed to capture observation output payloads | empty |
| `OTEL_REDACT_FIELDS` | Structured-field and free-text redaction keys used before export | `password,secret,token,...` |
| `OTEL_MAX_TRACE_PAYLOAD_SIZE` | Max serialized input/output payload size in characters | `32768` |

!!! note "Gateway vs Self-Hosted Langfuse Secrets"
    ContextForge itself only reads `LANGFUSE_OTEL_ENDPOINT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_OTEL_AUTH`. The other `LANGFUSE_*` secrets in this table apply only when you run the local self-hosted Langfuse compose overlay.

!!! warning "Local Compose Defaults"
    The self-hosted Langfuse compose overlay uses local-only demo project keys when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are unset. This convenience is limited to the compose path; ContextForge code does not embed Langfuse credentials.

!!! note "Payload Capture Defaults"
    ContextForge now uses allowlist-based payload capture. In normal runtime, `OTEL_CAPTURE_INPUT_SPANS` and `OTEL_CAPTURE_OUTPUT_SPANS` default to empty. The local Langfuse compose overlay enables a small dev-focused input allowlist for `tool.invoke`, `prompt.render`, `llm.proxy`, and `a2a.invoke`.

## Using the Langfuse UI

### Viewing Traces

1. Open [http://localhost:3100](http://localhost:3100)
2. Log in with the configured `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD`
3. Navigate to **Traces** in the sidebar
4. Each tool invocation appears as a trace with:
    - Span name (e.g., `tool.invoke`)
    - Duration and latency
    - Service attributes (deployment environment, namespace)
    - Error details if the invocation failed

### Viewing Users, Sessions, and Generations

1. Navigate to **Users** to group traces by `langfuse.user.id`
2. Navigate to **Sessions** to inspect MCP session grouping via `langfuse.session.id`
3. Navigate to **Generations** to inspect `llm.proxy` and `llm.chat` spans with `gen_ai.*` token usage
4. Filter by tags such as `team:<team-id>`, `auth:jwt`, and `env:production`

### Dashboard Workflow

Use the Langfuse UI in this order when validating the gateway:

1. **Traces**: confirm the request path and child spans
2. **Users**: verify the request is attributed to the authenticated email
3. **Sessions**: verify repeated MCP traffic groups under one session
4. **Generations**: verify LLM spans include model and token usage
5. **Evaluations**: score or annotate selected traces after reviewing outputs

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

The gateway still exports traces to Langfuse in this mode. Tempo remains available for dashboards, metrics, and optional collector-based dual export.

If any of those host ports are already in use, override them before starting the stack. Supported compose-only overrides include `LANGFUSE_PORT`, `LANGFUSE_WORKER_PORT`, `GRAFANA_PORT`, `LOKI_PORT`, `PROMETHEUS_PORT`, `TEMPO_PORT`, `TEMPO_OTLP_GRPC_PORT`, `TEMPO_OTLP_HTTP_PORT`, `PGADMIN_PORT`, and `REDIS_COMMANDER_PORT`. `LOKI_PORT` defaults to `3101` so it does not collide with Langfuse on `3100`.

!!! tip "Dual Trace Export"
    By default, OTEL traces go to Langfuse only. To send traces to both Langfuse and Tempo simultaneously, run an [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) with a fan-out pipeline. This repo now includes a sample collector config at `infra/monitoring/otel-collector/collector.langfuse-tempo.yaml`.

Example:

```bash
LANGFUSE_OTEL_AUTH=$(printf '%s' "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)
docker run --rm \
  --network mcp-context-forge_mcpnet \
  -e LANGFUSE_OTEL_ENDPOINT=http://langfuse-web:3000/api/public/otel/v1/traces \
  -e LANGFUSE_OTEL_AUTH="$LANGFUSE_OTEL_AUTH" \
  -e TEMPO_OTLP_GRPC_ENDPOINT=tempo:4317 \
  -v "$PWD/infra/monitoring/otel-collector/collector.langfuse-tempo.yaml:/etc/otelcol/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:0.123.0 \
  --config=/etc/otelcol/config.yaml
```

Then point ContextForge at the collector instead of Langfuse directly:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
```

## Production Deployment

### Security Hardening

1. **Set the gateway-facing Langfuse credentials** in `.env`:
    ```bash
    LANGFUSE_PUBLIC_KEY=pk-lf-<random>
    LANGFUSE_SECRET_KEY=sk-lf-<random>
    ```
    If you run the local self-hosted overlay and want to replace its internal service defaults, override the additional `LANGFUSE_*` compose variables as well.

2. **Optionally precompute the OTEL auth header** if you prefer to pass a base64 token instead of raw project keys:
    ```bash
    LANGFUSE_OTEL_AUTH=$(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)
    ```
    When `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, ContextForge can derive the OTLP Authorization header automatically.

3. **Configure OTEL payload controls** for trace capture:
    ```bash
    OTEL_EMIT_LANGFUSE_ATTRIBUTES=true
    OTEL_CAPTURE_IDENTITY_ATTRIBUTES=true
    OTEL_REDACT_FIELDS=password,secret,token,api_key,authorization,credential,auth_value,access_token,refresh_token,auth_token,client_secret,cookie,set-cookie,private_key
    OTEL_MAX_TRACE_PAYLOAD_SIZE=32768
    OTEL_CAPTURE_INPUT_SPANS=tool.invoke,prompt.render,llm.proxy
    OTEL_CAPTURE_OUTPUT_SPANS=llm.proxy,llm.chat
    ```
    `OTEL_CAPTURE_INPUT_SPANS` and `OTEL_CAPTURE_OUTPUT_SPANS` are allowlists. Leave them empty to disable observation payload capture entirely.
    Structured payloads are redacted by field name, and all exported string values also pass through URL and free-text secret scrubbing. This covers common cases such as `token=...`, signed URLs, and embedded `Bearer` / `Basic` credentials, but it is still best practice to avoid placing secrets inside generic free-text fields such as `query`, `message`, or `data`.

4. **Enable TLS** for the Langfuse endpoint in production.
    ```bash
    LANGFUSE_OTEL_ENDPOINT=https://langfuse.example.com/api/public/otel/v1/traces
    OTEL_EXPORTER_OTLP_INSECURE=false
    ```
    If your OTLP endpoint uses a private CA, mount that CA into the gateway container or host trust store before enabling export.

5. **Verify startup credential enforcement**.
   ContextForge now fails startup when a Langfuse OTLP endpoint is configured without a resolved `Authorization` header. Supplying arbitrary `OTEL_EXPORTER_OTLP_HEADERS` is not enough; the final header set must contain valid Langfuse basic auth, whether derived from `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`, `LANGFUSE_OTEL_AUTH`, or an explicit `Authorization=Basic ...` OTLP header.

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
    AUTH=$(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)
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

### Startup Fails With Langfuse Credential Errors

If the gateway exits during startup with a Langfuse credential error:

- Check `OTEL_EXPORTER_OTLP_HEADERS`, `LANGFUSE_OTEL_AUTH`, or the `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` pair
- Verify `LANGFUSE_OTEL_ENDPOINT` points at `/api/public/otel/v1/traces`
- Restart the gateway after fixing the missing or mismatched credentials

## Next Steps

- [OpenTelemetry Overview](opentelemetry.md) - All supported backends
- [Phoenix Integration](phoenix.md) - Alternative AI observability backend
- [Internal Observability](internal.md) - Built-in database-backed observability
- [Prometheus Metrics](prometheus.md) - Time-series monitoring
- [Langfuse Documentation](https://langfuse.com/docs) - Full Langfuse documentation
