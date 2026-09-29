# ContextForge Performance Smoke Test

This directory documents a controlled k6 smoke test of the complete internal
ContextForge MCP request path in the wxO development sandbox. The run was
intended to prove the workload and identify an initial saturation point; it is
not a production capacity benchmark.

## Request Path

```text
+---------------+
| k6 client pod |
+-------+-------+
        | MCP request
        v
+----------------------+
| ContextForge service |
+----------+-----------+
           v
+----------------------+
| ContextForge pod     |
| + enabled plugins    |
+----------+-----------+
           v
+----------------------+
| Registered virtual   |
| server and time tool |
+----------+-----------+
           v
+----------------------+
| Test time-server pod |
+----------+-----------+
           | MCP response
           v
     k6 records metrics
```

The k6 client and time server were temporary workloads in the same namespace
as ContextForge. The time server was exposed only through an internal
`ClusterIP` Service and was registered as a ContextForge gateway and virtual
server.

## Build Under Test

| Component | Image tag | Image digest |
| --- | --- | --- |
| ContextForge | `20260922-develop-696-9e1580b` | `sha256:0d7d417bde95b55a644cf680bbdce51a09a6a1a88796998fa5b24e09f32aaa58` |
| Policy adapter | `20260923-policy-143-413dab2-amd64` | `sha256:e1e87ad1d9463afa068cc2e8da5cfdfcd1eecabf3ee8b943727ba879ec904fe4` |

The ContextForge image tag contains the abbreviated source commit SHA
`9e1580b`.

## Test Setup

| Setting | Value |
| --- | --- |
| Environment | wxO dev-conn / `wo-dp-006` |
| Namespace | `mcp-context-forge` |
| Duration | 60 seconds per run, including ramp-up |
| Concurrent users | 10, 15, 20, and 30 |
| Ramp-up rate | 5 users per second |
| User pacing | Random 20-100 ms pause between requests |
| Request timeout | 5 seconds |
| Request mix | 20 `tools/call` requests per 1 `tools/list` request |
| Tool | `get_system_time` |
| Authentication | Approved internal dummy tenant token |
| External wxO authentication | Not included |
| ContextForge replicas | 1 |
| ContextForge resources | 1 CPU, 2 GiB memory limit |
| Time-server resources | 250 millicores, 128 MiB memory limit |

The 60-second window included the following ramp-up periods:

| Users | Ramp-up | Full-concurrency portion |
| ---: | ---: | ---: |
| 10 | 2 seconds | 58 seconds |
| 15 | 3 seconds | 57 seconds |
| 20 | 4 seconds | 56 seconds |
| 30 | 6 seconds | 54 seconds |

RPS was calculated across the complete 60-second window.

## Plugin Configuration

The following plugins were enabled in `enforce` mode:

- `WxoAuthCheck`
- `WXOConnections`
- `SpanAttributeCustomizer`

The following plugins were disabled:

- `SQLSanitizer`
- `SecretsDetection`
- `OutputLengthGuard`
- `RateLimiter`
- `Guardrails`
- `GuardrailsCustomModel`

Observability was enabled.

## Results

All four runs completed with zero workload failures.

| Users | Tool calls | Tool RPS | Average | p50 | p95 | p99 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 964 | 16.07 | 529 ms | 324 ms | 1,177 ms | 1,687 ms |
| 15 | 972 | 16.20 | 815 ms | 734 ms | 1,431 ms | 1,990 ms |
| 20 | 945 | 15.75 | 1,123 ms | 1,097 ms | 1,637 ms | 1,962 ms |
| 30 | 918 | 15.30 | 1,724 ms | 1,716 ms | 2,932 ms | 3,333 ms |

## Observations

- Throughput stayed around 15-16 tool calls per second as concurrency
  increased.
- Average latency increased from 529 ms at 10 users to 1,724 ms at 30 users.
- No workload request failures occurred.
- ContextForge CPU reached approximately its configured one-core limit.
- Increasing concurrency increased waiting time without increasing throughput.

These results cover the complete ContextForge request path. They do not
isolate the individual cost of authentication, plugins, database operations,
observability, or routing.

The smoke test did not change the ContextForge image, replica count, resource
limits, plugin configuration, or observability configuration.

## Reproducing the Workload

The manifests deploy an internal time server and one 10-user k6 Job. Before
running them:

1. Coordinate an approved sandbox window.
2. Register the time server URL from `time-server-service.yaml` in
   ContextForge and create a virtual server containing its time tool.
3. Set `CF_MCP_ENDPOINT` and `CF_TOOL_NAME` in `k6-job.yaml` to the registered
   virtual-server endpoint and federated tool name.
4. Have an administrator provision the `cf-k6-test-auth` Secret with a `token`
   key. Never commit the token.
5. Create the k6 script ConfigMap and apply the workloads:

```bash
oc create configmap cf-k6-smoke-script \
  --namespace mcp-context-forge \
  --from-file=k6-contextforge-smoke.js
oc apply -f time-server-deployment.yaml
oc apply -f time-server-service.yaml
oc create -f k6-job.yaml
```

Inspect the generated Job pod and its summary:

```bash
oc get pods,jobs,services -n mcp-context-forge
oc logs -n mcp-context-forge job/cf-k6-smoke
```

To run another concurrency level, delete the completed Job, update
`BENCH_USERS`, and create it again. Do not run concurrent benchmark Jobs in the
shared sandbox.

## Cleanup

Remove the temporary Kubernetes resources when the environment is no longer
needed:

```bash
oc delete job cf-k6-smoke -n mcp-context-forge
oc delete configmap cf-k6-smoke-script -n mcp-context-forge
oc delete service cf-perf-fast-time -n mcp-context-forge
oc delete deployment cf-perf-fast-time -n mcp-context-forge
```

Remove the temporary ContextForge virtual server, gateway, tool, and synthetic
tenant objects through the supported administrative API or UI. Do not remove
shared resources by name alone; verify their IDs and ownership first.
