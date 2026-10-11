# ContextForge Performance Cluster Smoke Test

This directory contains the Kubernetes manifests, registration payloads, k6
workloads, and results from a controlled ContextForge smoke test on the wxO
AWS performance cluster. The test exercised the complete internal MCP request
path. It was intended to characterize scaling and locate an initial saturation
region, not establish a production capacity guarantee.

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
           | Kubernetes load balancing
           v
+--------------------------+
| 16 ContextForge pods     |
| + enabled wxO plugins    |
+-----------+--------------+
            v
+------------------------+
| Registered virtual     |
| server and time tool   |
+-----------+------------+
            v
+------------------------+
| fast-time Service      |
+-----------+------------+
            | Kubernetes load balancing
            v
+------------------------+
| 4 fast-time pods       |
+-----------+------------+
            | MCP response
            v
      k6 records metrics
```

The k6 Jobs and fast-time server ran in the `mcp-context-forge` namespace.
The fast-time server was exposed only through an internal `ClusterIP` Service.

## Build Under Test

| Component | Image tag | Source SHA | Image digest |
| --- | --- | --- | --- |
| ContextForge | `20260926-develop-706-abdfa23` | `abdfa23` | `sha256:d2a8eb37102763fd34d9eb7e003914e97c986f89b0597eee80a46acc891b8196` |
| Policy adapter | `20261001-wo-release-sprint19-20261016-150-f04783d` | `f04783d` | `sha256:115d1fd6c0ec942038dad174863b98bc7f277563cca93b34850c6d7144bac879` |
| fast-time server | digest pinned | - | `sha256:78f93ca1e1befca2c6fd2ce54b5ab4685a2de3e9cf639d38ad0d2da54a7ea3b7` |
| k6 | digest pinned | - | `sha256:31e65b66982b146f628c3034d5179dc59dc3a8ea0c7ef118972017388d889f2f` |

## Test Setup

| Setting | Value |
| --- | --- |
| Environment | wxO AWS performance cluster / `wo-dp-wodlperf` |
| Namespace | `mcp-context-forge` |
| ContextForge replicas | 16 |
| ContextForge HPA | None |
| fast-time replicas | 4 |
| Concurrent users | 10, 30, 60, 125, 250, and 500 |
| Duration | 60 seconds per run, plus one 500-user 120-second run |
| User pacing | Random 20-100 ms pause between requests |
| Request timeout | 5 seconds |
| Request mix | 20 `tools/call` requests per 1 `tools/list` request |
| Tool | `get_system_time` |
| Registered tool | `cf-perf-fast-time-get-system-time` |
| Authentication | Temporary native ContextForge token stored in a Kubernetes Secret |
| External wxO authentication | Not included |
| Observability | Enabled |

The temporary token and Kubernetes Secret were removed after the runs. No
credential is stored in this directory.

### Resource Configuration

| Component | Replicas | CPU request | CPU limit | Memory request | Memory limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| ContextForge | 16 | 4 cores each | 8 cores each | 1 GiB each | 2 GiB each |
| Policy adapter | 16 | 1 core each | 1 core each | 2 GiB each | 3 GiB each |
| fast-time server | 4 | 100 millicores each | 1 core each | 64 MiB each | 256 MiB each |
| k6 Job | 1 per run | 1 core | 4 cores | 512 MiB | 2 GiB |

### Ramp Configuration

RPS was calculated across the complete configured duration, including ramp-up.

| Users | Duration | Spawn rate | Ramp-up | Full concurrency |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 60 s | 5 users/s | 2 s | 58 s |
| 30 | 60 s | 5 users/s | 6 s | 54 s |
| 60 | 60 s | 5 users/s | 12 s | 48 s |
| 125 | 60 s | 5 users/s | 25 s | 35 s |
| 250 | 60 s | 10 users/s | 25 s | 35 s |
| 500 | 60 s | 20 users/s | 25 s | 35 s |
| 500 | 120 s | 20 users/s | 25 s | 95 s |

## Plugin Configuration

The deployed `plugins/config.yaml` was inspected before testing.

Enabled in `enforce` mode:

- `WxoAuthCheck`
- `WXOConnections`
- `SpanAttributeCustomizer`

Disabled:

- `SQLSanitizer`
- `SecretsDetection`
- `OutputLengthGuardPlugin`
- `RateLimiterPlugin`
- `Guardrails`
- `GuardrailsCustomModel`

The deployment also had plugin header overrides, CPEX control telemetry,
ContextForge observability, and OpenTelemetry observability enabled.

## Results

All seven load runs completed with zero workload failures. Together they made
135,968 successful tool calls.

| Users | Duration | Tool calls | Tool RPS | Average | p50 | p95 | p99 | Maximum |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 60 s | 2,900 | 48.33 | 132 ms | 125 ms | 159 ms | 174 ms | 1,232 ms |
| 30 | 60 s | 7,813 | 130.22 | 148 ms | 135 ms | 225 ms | 260 ms | 1,243 ms |
| 60 | 60 s | 11,953 | 199.22 | 200 ms | 157 ms | 382 ms | 548 ms | 881 ms |
| 125 | 60 s | 17,350 | 289.17 | 271 ms | 224 ms | 633 ms | 836 ms | 1,173 ms |
| 250 | 60 s | 22,467 | 374.45 | 453 ms | 410 ms | 924 ms | 1,122 ms | 1,524 ms |
| 500 | 60 s | 23,720 | 395.33 | 912 ms | 880 ms | 1,831 ms | 2,283 ms | 2,800 ms |
| 500 | 120 s | 49,765 | 414.71 | 991 ms | 934 ms | 1,943 ms | 2,366 ms | 3,209 ms |

### Sampled Resource Use

These are approximately five-second samples captured during each run. They
are useful directional observations rather than complete resource profiles.

| Users / duration | ContextForge CPU total | Busiest CF pod | ContextForge memory total | fast-time CPU total | k6 CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 / 60 s | 3.19 cores | 0.61 cores | 17.52 GiB | 0.06 cores | Not captured |
| 30 / 60 s | 8.59 cores | 1.09 cores | 18.30 GiB | 0.15 cores | Not captured |
| 60 / 60 s | 13.59 cores | 1.59 cores | 19.14 GiB | 0.21 cores | Not captured |
| 125 / 60 s | 21.57 cores | 1.79 cores | 19.55 GiB | 0.31 cores | Not captured |
| 250 / 60 s | 27.07 cores | 1.93 cores | 20.16 GiB | 0.35 cores | 0.23 cores |
| 500 / 60 s | 28.12 cores | 2.00 cores | 20.93 GiB | 0.38 cores | 0.23 cores |
| 500 / 120 s | 28.68 cores | 2.02 cores | 21.18 GiB | 0.38 cores | 0.25 cores |

### Single-Lifecycle Check

Before applying load, a one-VU, one-iteration k6 Job performed `initialize`,
`notifications/initialized`, `tools/list`, and one `tools/call`. It passed all
four checks with four HTTP requests and no failures. ContextForge did not
return an MCP session ID, so the client had no session to delete.

## Observations

- Throughput scaled strongly through 125 users and continued increasing at
  250 users.
- Increasing from 250 to 500 users raised 60-second tool RPS by about 5.6%,
  while average latency approximately doubled.
- The 500-user 120-second run remained stable with no failures.
- The longer 500-user run is not directly comparable to the 60-second runs
  because ramp-up accounts for a smaller fraction of its measurement window.
- Neither the single k6 pod nor the four fast-time pods approached its CPU
  limit in the captured samples.
- ContextForge pods also remained below their configured CPU limits. The test
  does not isolate whether plugins, database work, connection pools, routing,
  or another part of the request path constrained throughput.
- No ContextForge or fast-time pod restarted during the runs.

## Files

| File | Purpose |
| --- | --- |
| `../k6-contextforge-smoke.js` | Parameterized load workload and JSON summary |
| `time-server-deployment.yaml` | Four-replica fast-time MCP server |
| `time-server-service.yaml` | Internal ClusterIP Service for the time server |
| `gateway-registration.json` | ContextForge gateway registration payload |
| `server-registration.json` | ContextForge virtual-server registration payload |
| `k6-test-config.yaml` | Tested virtual-server endpoint and tool name |
| `k6-single-lifecycle.js` | One-iteration protocol and tool check |
| `k6-single-lifecycle-job.yaml` | Job for the single-lifecycle check |
| `k6-jobs.yaml` | Suspended 10, 30, 60, and 125-user Jobs |
| `k6-high-load-jobs.yaml` | Suspended 250 and 500-user Jobs |
| `k6-image-check-job.yaml` | Non-traffic k6 image-pull check |

Replace `REPLACE_WITH_TOOL_ID` and `REPLACE_WITH_SERVER_ID` after registering
the temporary gateway and virtual server in the target environment.

## Running the Test

Coordinate an approved performance window before generating load. Apply the
server and configuration, then create the script ConfigMaps:

```bash
oc apply -f time-server-deployment.yaml
oc apply -f time-server-service.yaml
oc apply -f k6-test-config.yaml
oc create configmap cf-k6-smoke-script \
  --namespace mcp-context-forge \
  --from-file=../k6-contextforge-smoke.js
oc create configmap cf-k6-single-lifecycle-script \
  --namespace mcp-context-forge \
  --from-file=k6-single-lifecycle.js
```

Have an authorized administrator provision `cf-k6-test-auth` with a `token`
key immediately before testing. Do not put the token in a manifest, command
history, test output, or source control.

The load Jobs are suspended by default and create no pods or traffic when
applied:

```bash
oc apply -f k6-jobs.yaml
oc apply -f k6-high-load-jobs.yaml
```

Run only one Job at a time during the approved window. For example:

```bash
oc patch job cf-k6-perf-10-60s \
  --namespace mcp-context-forge \
  --type merge \
  --patch '{"spec":{"suspend":false}}'
oc logs --namespace mcp-context-forge job/cf-k6-perf-10-60s
```

## Cleanup

Delete the temporary Jobs and Kubernetes resources after results are captured:

```bash
oc delete -f k6-high-load-jobs.yaml --ignore-not-found
oc delete -f k6-jobs.yaml --ignore-not-found
oc delete -f k6-single-lifecycle-job.yaml --ignore-not-found
oc delete configmap cf-k6-smoke-script cf-k6-single-lifecycle-script \
  --namespace mcp-context-forge \
  --ignore-not-found
oc delete secret cf-k6-test-auth \
  --namespace mcp-context-forge \
  --ignore-not-found
oc delete -f k6-test-config.yaml --ignore-not-found
oc delete -f time-server-service.yaml --ignore-not-found
oc delete -f time-server-deployment.yaml --ignore-not-found
```

Remove the temporary ContextForge virtual server, gateway, and tool through
the supported administrative API or UI. Verify their IDs and ownership before
deleting shared database records.
