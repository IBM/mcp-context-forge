# OpenShift Build Pipelines

ContextForge provides an OpenShift Template that creates `BuildConfig` and `ImageStream` resources for every container image built from the project's `docker-compose.yml`. Builds run inside the cluster using the Docker (Containerfile) strategy and push images to the internal registry.

---

## Components

| BuildConfig | Language | Context Directory | Dockerfile | Description |
|---|---|---|---|---|
| `contextforge` | Python + Rust | `.` (repo root) | `Containerfile.lite` | Main ContextForge gateway (with Rust plugins) |
| `nginx-cache` | nginx | `infra/nginx` | `Dockerfile` | Caching reverse proxy |
| `fast-time-server` | Go | `mcp-servers/go/fast-time-server` | `Dockerfile` | MCP time-tool server |
| `fast-test-server` | Rust | `mcp-servers/rust/fast-test-server` | `Containerfile` | MCP test server for perf testing |
| `slow-time-server` | Go | `mcp-servers/go/slow-time-server` | `Dockerfile` | Latency-injecting time server |
| `a2a-echo-agent` | Go | `a2a-agents/go/a2a-echo-agent` | `Dockerfile` | A2A protocol echo agent |
| `benchmark-server` | Go | `mcp-servers/go/benchmark-server` | `Dockerfile` | Load-testing MCP server |

Each BuildConfig has a matching ImageStream. Built images land at:

```
image-registry.openshift-image-registry.svc:5000/<namespace>/<name>:latest
```

---

## Prerequisites

- `oc` CLI authenticated to an OpenShift 4.x cluster
- A project/namespace (e.g. `contextforge-dev`)
- The cluster must be able to reach `https://github.com/IBM/mcp-context-forge.git` (or your fork)

---

## Quick Start

### Create the namespace and apply the template

```bash
oc new-project contextforge-dev

# Apply with default branch (main)
oc process -f openshift/builds/build-pipelines.yaml \
  -p GIT_REF=main \
  -p NAMESPACE=contextforge-dev \
  | oc apply -f -
```

### Trigger all builds

```bash
for bc in contextforge nginx-cache fast-time-server fast-test-server \
          slow-time-server a2a-echo-agent benchmark-server; do
  oc start-build "$bc" &
done
wait
```

### Follow a specific build

```bash
oc start-build contextforge --follow
```

---

## Switching Branches

All BuildConfigs share a `GIT_REF` parameter. There are two ways to change the target branch.

### Option A: Re-process the template

Re-applies all BuildConfigs with the new ref in one command:

```bash
oc process -f openshift/builds/build-pipelines.yaml \
  -p GIT_REF=feature/my-branch \
  -p NAMESPACE=contextforge-dev \
  | oc apply -f -
```

Then trigger builds as above.

### Option B: Patch a single BuildConfig

Useful when you only need to rebuild one component from a different branch:

```bash
oc patch bc/contextforge \
  -p '{"spec":{"source":{"git":{"ref":"feature/my-branch"}}}}'
oc start-build contextforge --follow
```

---

## Build Args

The `contextforge` BuildConfig uses `Containerfile.lite` with Rust enabled, equivalent to `make docker-prod-rust`:

| Build Arg | Value | Effect |
|---|---|---|
| `ENABLE_RUST` | `true` | Builds Rust plugins (PII filter, etc.) |
| `ENABLE_RUST_MCP_RMCP` | `true` | Builds the Rust MCP runtime with rmcp support |

These are hardcoded in the template. To disable Rust (equivalent to `make docker-prod`), edit the `buildArgs` section in `build-pipelines.yaml`.

---

## Template Parameters

| Parameter | Default | Description |
|---|---|---|
| `GIT_REF` | `main` | Git branch, tag, or commit SHA to build |
| `GIT_URI` | `https://github.com/IBM/mcp-context-forge.git` | Git repository URL |
| `NAMESPACE` | `contextforge-dev` | Target namespace for all resources |

To use a fork:

```bash
oc process -f openshift/builds/build-pipelines.yaml \
  -p GIT_URI=https://github.com/youruser/mcp-context-forge.git \
  -p GIT_REF=my-branch \
  | oc apply -f -
```

---

## Monitoring Builds

```bash
# List all builds
oc get builds

# Watch builds in real time
oc get builds -w

# Stream logs for a specific build
oc logs -f build/contextforge-1

# Check build status
oc get bc -o custom-columns='NAME:.metadata.name,LAST_VERSION:.status.lastVersion'
```

---

## Using Built Images in Deployments

Because each ImageStream has `lookupPolicy.local: true`, you can reference images by their ImageStream name directly in Deployments:

```yaml
containers:
  - name: gateway
    image: contextforge:latest    # Resolved via ImageStream
```

Or reference the full internal registry path:

```yaml
image: image-registry.openshift-image-registry.svc:5000/contextforge-dev/contextforge:latest
```

---

## Resource Limits

Build resource allocations are tuned per component type:

| Component | Memory Limit | CPU Limit | Rationale |
|---|---|---|---|
| `contextforge` | 4Gi | 2 | Large Python dependency tree |
| `fast-test-server` | 4Gi | 2 | Rust compilation is memory-intensive |
| Go servers | 2Gi | 2 | Go builds are lighter |
| `nginx-cache` | 1Gi | 1 | Minimal build, just copies config |

Adjust these in `openshift/builds/build-pipelines.yaml` if builds OOM or are slow.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Build fails with `fetch` error | Cluster cannot reach GitHub. Check egress/proxy settings. |
| Build OOM killed | Increase `resources.limits.memory` in the BuildConfig. |
| `ImageStream not found` | Ensure `NAMESPACE` parameter matches your current project. |
| `Dockerfile not found` | Check `contextDir` and `dockerfilePath` match the repo layout. |
| Rust nightly image pull fails | Ensure `docker.io` is accessible; consider mirroring the image. |

---

## File Locations

- **Template**: [`openshift/builds/build-pipelines.yaml`](../../openshift/builds/build-pipelines.yaml)
- **General OpenShift deployment guide**: [deployment/openshift.md](openshift.md)
