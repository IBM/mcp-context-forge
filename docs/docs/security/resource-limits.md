# Resource Limits and Process Management

This guide covers resource limit configuration for ContextForge deployments to ensure stable operation and prevent resource exhaustion.

## Overview

Resource limits help maintain system stability by preventing individual containers from consuming excessive resources. ContextForge supports configurable limits for:

- Process count (nproc)
- Open file descriptors (nofile)
- Memory allocation
- CPU usage

## Docker Compose Configuration

### Process Limits

All ContextForge compose files include process limits to prevent resource exhaustion:

```yaml
services:
  gateway:
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
      nproc:
        soft: 5000
        hard: 5000
```

**Recommended Values:**
- `nproc`: 5000 processes (soft and hard limit)
- `nofile`: 65535 file descriptors (soft and hard limit)

These limits are applied across all deployment variants:
- `docker-compose.yml` (production)
- `docker-compose-debug.yml` (debugging)
- `docker-compose-performance.yml` (high-load testing)
- `docker-compose-verbose-logging.yml` (verbose logging)
- `docker-compose-embedded.yml` (embedded mode)
- `docker-compose.override.lite.yml` (resource-constrained)
- `docker-compose.sso.yml` (SSO integration)
- `docker-compose.with-langfuse.yml` (Langfuse observability)
- `docker-compose.with-phoenix.yml` (Phoenix observability)

### Memory and CPU Limits

Configure resource limits in the `deploy` section:

```yaml
services:
  gateway:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G
        reservations:
          cpus: '2'
          memory: 2G
```

## Kubernetes Configuration

**Important:** Kubernetes does NOT provide native per-container process limits equivalent to Docker's `ulimits.nproc`.

### Defense-in-Depth Approach

For production Kubernetes deployments, implement multiple layers of protection:

#### Option 1: Admission Controllers (Recommended)

**OPA Gatekeeper:**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sProcessLimit
metadata:
  name: container-process-limit
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
  parameters:
    maxProcesses: 5000
```

**Kyverno:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: limit-processes
spec:
  validationFailureAction: enforce
  rules:
    - name: check-process-limit
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Container must not spawn excessive processes"
        pattern:
          spec:
            containers:
              - =(securityContext):
                  =(capabilities):
                    drop:
                      - SYS_ADMIN
```

#### Option 2: Runtime Security Tools

**Falco Rule:**

```yaml
- rule: Excessive Process Creation
  desc: Detect rapid process creation patterns
  condition: >
    spawned_process and
    proc.pname = proc.name and
    evt.count > 100 in 1s
  output: "Rapid process creation detected (user=%user.name container=%container.name)"
  priority: CRITICAL
```

#### Option 3: Node-level cgroups v2 (Advanced)

Configure pids.max at the node level (affects all pods on the node):

```bash
echo 5000 > /sys/fs/cgroup/kubepods/pids.max
```

**Note:** Requires node-level access and impacts all pods on the node.

### Helm Chart Configuration

The ContextForge Helm chart includes inline documentation for Kubernetes process limit strategies. See `charts/mcp-stack/values.yaml` for detailed guidance.

## Monitoring Resource Usage

### Docker

Monitor container resource usage:

```bash
# View resource usage for all containers
docker stats

# View specific container
docker stats mcp-context-forge-gateway-1

# Check ulimits inside container
docker exec mcp-context-forge-gateway-1 ulimit -a
```

### Kubernetes

Monitor pod resource usage:

```bash
# View resource usage
kubectl top pods -n mcp-gateway

# Check resource limits
kubectl describe pod <pod-name> -n mcp-gateway

# View events
kubectl get events -n mcp-gateway --sort-by='.lastTimestamp'
```

## Troubleshooting

### Process Limit Exceeded

**Symptoms:**
- Container becomes unresponsive
- "Cannot fork" errors in logs
- Failed health checks

**Resolution:**
1. Check current process count: `docker exec <container> ps aux | wc -l`
2. Review application logs for process leaks
3. Restart container: `docker compose restart gateway`
4. Adjust limits if legitimate workload requires higher values

### File Descriptor Exhaustion

**Symptoms:**
- "Too many open files" errors
- Connection failures
- Database connection pool exhaustion

**Resolution:**
1. Check current usage: `docker exec <container> lsof | wc -l`
2. Increase `nofile` limits if needed
3. Review application for file descriptor leaks

## Best Practices

1. **Set Conservative Limits**: Start with recommended values and adjust based on monitoring
2. **Monitor Regularly**: Track resource usage trends to detect anomalies early
3. **Test Under Load**: Validate limits under realistic load conditions
4. **Document Changes**: Record any limit adjustments and rationale
5. **Layer Defenses**: Use multiple protection mechanisms (ulimits + admission controllers + runtime security)

## References

- [Docker ulimits documentation](https://docs.docker.com/engine/reference/commandline/run/#ulimit)
- [Kubernetes Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/)
- [Kyverno](https://kyverno.io/)
- [Falco](https://falco.org/)
