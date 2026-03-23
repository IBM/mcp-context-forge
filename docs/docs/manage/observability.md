## Observability

ContextForge provides comprehensive observability through two complementary systems:

1. **Internal Observability** - Built-in database-backed tracing with Admin UI dashboards
2. **OpenTelemetry** - Standard distributed tracing to external backends (Phoenix, Jaeger, Tempo)

## Documentation

- **[OpenTelemetry Overview](observability/observability.md)** - External observability with OTLP backends
- **[Internal Observability](observability/internal-observability.md)** - Built-in tracing, metrics, and Admin UI dashboards
- **[Phoenix Integration](observability/phoenix.md)** - AI/LLM-focused observability with Arize Phoenix

## Quick Start

### Internal Observability (Built-in)

```bash
# Enable internal observability
export OBSERVABILITY_ENABLED=true

# Run ContextForge
mcpgateway

# View dashboards at http://localhost:4444/admin/observability
```

### OpenTelemetry (External)

```bash
# Enable OpenTelemetry (disabled by default)
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Start Phoenix for AI/LLM observability
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

# Run ContextForge
mcpgateway

# View traces at http://localhost:6006
```

## Prometheus metrics (important)

Note: the metrics exposure is wired from `mcpgateway/main.py` but the HTTP
handler itself is registered by the metrics module. The main application
imports and calls `setup_metrics(app)` from `mcpgateway.services.metrics`. The
`setup_metrics` function instruments the FastAPI app and registers the
Prometheus scrape endpoint using the Prometheus instrumentator; the endpoint
available to Prometheus scrapers is:

- GET /metrics/prometheus

The route is defined as a custom FastAPI endpoint in
`mcpgateway/services/metrics.py` with `Depends(require_auth)` for JWT
authentication. The endpoint is registered with `include_in_schema=True` (so it
appears in OpenAPI / Swagger) and supports gzip compression via the
`Accept-Encoding` header.

### Env vars / settings that control metrics

- `ENABLE_METRICS` (env) — set to `true` to enable instrumentation; defaults to `false`. The endpoint requires JWT authentication when enabled.
- `METRICS_EXCLUDED_HANDLERS` (env / settings) — comma-separated regexes for endpoints to exclude from instrumentation (useful for SSE/WS or per-request high-cardinality paths). The implementation reads `settings.METRICS_EXCLUDED_HANDLERS` and compiles the patterns.
- `METRICS_CUSTOM_LABELS` (env / settings) — comma-separated `key=value` pairs used as static labels on the `app_info` gauge (low-cardinality values only). When present, a Prometheus `app_info` gauge is created and set to 1 with those labels.
- Additional settings in `mcpgateway/config.py`: `METRICS_NAMESPACE`, `METRICS_SUBSYSTEM`. Note: these config fields exist, but the current `metrics` module does not wire them into the instrumentator by default (they're available for future use/consumption by custom collectors).

### Enable / verify locally

1. Set `ENABLE_METRICS=true` in your shell or `.env` and generate a scrape token.

     ```bash
     export ENABLE_METRICS=true
     export METRICS_CUSTOM_LABELS="env=local,team=dev"
     export METRICS_EXCLUDED_HANDLERS="/servers/.*/sse,/static/.*"
     ```

2. Start the gateway (development). By default the app listens on port 4444. The Prometheus endpoint will be:

     http://localhost:4444/metrics/prometheus

3. Generate a scrape token (non-expiring service JWT):

     ```bash
     export METRICS_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
       --username prometheus@monitoring --exp 0 \
       --secret $JWT_SECRET_KEY --algo HS256)
     ```

4. Quick check (get the first lines of exposition text):

     ```bash
     curl -sS -H "Authorization: Bearer $METRICS_TOKEN" \
       http://localhost:4444/metrics/prometheus | head -n 20
     ```

5. If metrics are disabled, the endpoint returns a JSON 503 response (authentication is still required).

### Prometheus scrape job example

Add the job below to your `prometheus.yml` for local testing:

```yaml
scrape_configs:
    - job_name: 'mcp-gateway'
        metrics_path: /metrics/prometheus
        authorization:
            type: Bearer
            credentials_file: /path/to/metrics-token.jwt
        static_configs:
            - targets: ['localhost:4444']
```

To create the token file: `echo -n "$METRICS_TOKEN" > /path/to/metrics-token.jwt`.

If Prometheus runs in Docker, adjust the target host accordingly (host networking
or container host IP). The Docker Compose monitoring profile generates the scrape
token automatically via the `prometheus_token` service.
See the repo `docs/manage/scale.md` for examples of deploying Prometheus in
Kubernetes.

### Grafana and dashboards

- Use Grafana to import dashboards for Kubernetes, PostgreSQL and Redis (IDs
    suggested elsewhere in the repo). For ContextForge app metrics, create panels
    for:

    - Request rate: `rate(http_requests_total[1m])`
    - Error rate: `rate(http_requests_total{status=~"5.."}[5m])`
    - P99 latency: `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`

### Common pitfalls — short guidance

- High-cardinality labels

    - Never add per-request identifiers (user IDs, full URIs, request IDs) as
        Prometheus labels. They explode the number of time series and can crash
        Prometheus memory.
    - Use `METRICS_CUSTOM_LABELS` only for low-cardinality labels (env, region).

- Compression (gzip) vs CPU

    - The metrics exposer in `mcpgateway.services.metrics` enables gzip by
        default for the `/metrics/prometheus` endpoint. Compressing the payload
        reduces network usage but increases CPU on scrape time. On CPU-constrained
        nodes consider increasing scrape interval (e.g. 15s→30s) or disabling gzip
        at the instrumentor layer.

- Duplicate collectors during reloads/tests

    - Instrumentation registers collectors on the global Prometheus registry.
        When reloading the app in the same process (tests, interactive sessions)
        you may see "collector already registered"; restart the process or clear
        the registry in test fixtures.

### Quick checklist

- [ ] `ENABLE_METRICS=true`
- [ ] Generate scrape JWT: `python -m mcpgateway.utils.create_jwt_token --username prometheus@monitoring --exp 0 --secret $JWT_SECRET_KEY`
- [ ] `/metrics/prometheus` reachable (with `Authorization: Bearer <token>`)
- [ ] Add scrape job to Prometheus with `authorization: { type: Bearer, credentials_file: <path> }`
- [ ] Exclude high-cardinality paths with `METRICS_EXCLUDED_HANDLERS`
- [ ] Use tracing (OTel) for high-cardinality debugging information

## Where to look in the code

- `mcpgateway/main.py` — wiring: imports and calls `setup_metrics(app)` from
    `mcpgateway.services.metrics`. The function call instruments the app at
    startup; the `/metrics/prometheus` endpoint is registered as a custom
    auth-gated handler inside `mcpgateway/services/metrics.py`.
- `mcpgateway/services/metrics.py` — instrumentation implementation and env-vars.
- `mcpgateway/config.py` — settings defaults and names used by the app.

---
