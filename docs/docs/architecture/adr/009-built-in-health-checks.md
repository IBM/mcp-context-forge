# ADR-0009: Built-in Health Checks & Self-Monitoring

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

MCP Gateways must participate in mesh/federated deployments. Faulty nodes must be detected and removed automatically.
Additionally, cloud-native infrastructure (like Kubernetes, Docker Swarm, or systemd watchdogs) needs a way to check local health.

The gateway config supports health-related settings:

- `HEALTH_CHECK_INTERVAL`: frequency of peer checks
- `HEALTH_CHECK_TIMEOUT`: request timeout per probe
- `UNHEALTHY_THRESHOLD`: number of failures before a peer is marked unhealthy:contentReference[oaicite:0]{index=0}

The README and architecture describe `/health` and `/metrics` endpoints as built-in features:contentReference[oaicite:1]{index=1}.

## Decision

Implement two health-check levels:

1. **Local health endpoint** at `/health`:
   - Verifies database connectivity and response time
   - Optionally checks cache (e.g. Redis ping or in-memory status)

2. **Federated peer liveness**:
   - Every `HEALTH_CHECK_INTERVAL`, we ping all registered peers via HTTP
   - If a peer fails `UNHEALTHY_THRESHOLD` times consecutively, it's temporarily deactivated
   - A separate background task handles this (see `FederationManager`):contentReference[oaicite:2]{index=2}

Health info is also published to `/metrics` in Prometheus format.

## Consequences

- ✅ Federated topologies can eject bad nodes quickly and re-accept them later
- ✅ Local health can be used by Kubernetes probes, HAProxy, etc.
- 🔄 Gateways that go offline briefly won't be removed immediately (tunable)
- 🔍 Metrics include last check time, RTT, and result status

## Alternatives Considered

| Option                         | Why Not                                                                 |
|--------------------------------|--------------------------------------------------------------------------|
| **No health checks**           | Delayed or no reaction to failures; requires manual debugging            |
| **Rely on Kubernetes probes**  | Only detects local process health, not remote peers                     |
| **External APM agent (Datadog)** | Complex setup, costly for small/self-hosted use cases                  |
| **Central heartbeat server**   | Single point of failure, requires extra infra                           |

## Status

This is implemented as part of the `FederationManager` and exposed via `/health` and `/metrics` endpoints.
