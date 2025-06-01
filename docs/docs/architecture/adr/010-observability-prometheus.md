# ADR-0010: Observability via Prometheus, Structured Logs, and Metrics

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

The MCP Gateway is a long-running service that executes tools, processes requests, and federates with remote peers.
Operators and developers must be able to observe:

- Overall system health
- Request throughput and latency
- Tool and resource usage
- Error rates and failure patterns
- Federation behavior and peer availability

The gateway needs to surface this without requiring external instrumentation or agents.

## Decision

We will implement native observability features using:

1. **Structured JSON logs** with optional plaintext fallback:
   - Controlled by `LOG_FORMAT=json|text` and `LOG_LEVEL`:contentReference[oaicite:0]{index=0}
   - Includes fields: timestamp, level, logger name, request ID, route, auth user, latency

2. **Prometheus-compatible `/metrics` endpoint**:
   - Exposes key counters and histograms: tool invocations, failures, resource loads, peer syncs, etc.
   - Uses plain `text/plain; version=0.0.4` exposition format

3. **Latency decorators** and in-code timing for critical paths:
   - Completion requests
   - Resource resolution
   - Federation sync/health probes

4. **Per-request IDs and correlation**:
   - Middleware attaches `X-Request-ID` if present or generates a new one
   - Request ID propagates through logs and errors

## Consequences

- 📊 Metrics can be scraped by Prometheus and visualized in Grafana
- 🔍 Developers can trace logs by request or user
- 🛠️ No external sidecars required for basic visibility
- 📦 Docker image contains `/metrics` by default and logs to `stdout` (JSON)

## Alternatives Considered

| Option                           | Why Not                                                             |
|----------------------------------|----------------------------------------------------------------------|
| **No structured logging**        | Difficult to parse or filter logs; weak correlation per request     |
| **Third-party APM (e.g., Datadog)** | Adds vendor lock-in, overhead, and cost                            |
| **Syslog or Fluentd only**       | Requires extra deployment layers; still needs JSON emitters         |
| **StatsD / Telegraf metrics**    | Less common today than Prometheus; harder to self-host              |

## Status

Implemented in `LoggingService` and `metrics_router`. Observability is active by default for all transports and routes.
