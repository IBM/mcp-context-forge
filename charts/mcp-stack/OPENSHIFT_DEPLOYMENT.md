# OpenShift Deployment Guide for ContextForge MCP Gateway

## Prerequisites

- OpenShift cluster with `oc` and `helm` CLI tools
- NFS PersistentVolume with `ReadWriteMany` access mode
- Docker Hub account (for pulling rate-limited images)

## Quick Deploy
```bash
# 1. Log in to OpenShift
oc login <cluster-api-url> --token=<your-token>
oc project <your-namespace>

# 2. Ensure NFS PV is available
oc get pv | grep nfsx

# If PV is in Released state, clear it:
oc patch pv nfsx-pv --type=json -p '[{"op":"remove","path":"/spec/claimRef"}]'

# 3. Create Docker Hub pull secret (required to avoid rate limits)
oc create secret docker-registry dockerhub-secret \
  --docker-server=docker.io \
  --docker-username=<your-dockerhub-username> \
  --docker-password=<your-dockerhub-password> \
  -n <your-namespace>
oc secrets link default dockerhub-secret --for=pull -n <your-namespace>

# 4. Install with Helm
helm install contextforge ./charts/mcp-stack -n <your-namespace> \
  -f <your-values-file> \
  --set mcpContextForge.replicaCount=1

# 5. Wait for pods (Postgres must start first, then migration, then gateway)
oc get pods -n <your-namespace> -w

# 6. Fix PgBouncer seccomp issue (OpenShift rejects RuntimeDefault)
oc get deployment contextforge-mcp-stack-pgbouncer -n <your-namespace> -o yaml > /tmp/pgbouncer-deploy.yaml
sed -i.bak '/seccompProfile/,/type: RuntimeDefault/d' /tmp/pgbouncer-deploy.yaml
oc replace -f /tmp/pgbouncer-deploy.yaml --force

# Add pull secret to PgBouncer
oc patch deployment contextforge-mcp-stack-pgbouncer -n <your-namespace> \
  --type=strategic -p '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"dockerhub-secret"}]}}}}'

# 7. Create the route (points to nginx proxy, not directly to gateway)
oc create route edge contextforge \
  --service=contextforge-mcp-stack-nginx \
  --port=80 \
  --insecure-policy=Redirect \
  -n <your-namespace>

# 8. Scale gateway to 2 replicas after migration completes
oc scale deployment contextforge-mcp-stack-mcpgateway -n <your-namespace> --replicas=2

# 9. Access the app
oc get route -n <your-namespace>
# Open the URL with https:// and log in with admin@example.com / admin123
```

## values.yaml Changes Required for OpenShift + NFS

The following changes were made to the default `values.yaml` for OpenShift on IBM Fyre with NFS storage:

| Setting | Default | Changed To | Reason |
|---------|---------|------------|--------|
| `pgbouncer.enabled` | `false` | `true` | Enables connection pooling |
| `pgbouncer.pool.mode` | `transaction` | `session` | Alembic migrations require advisory locks which only work in session mode |
| `postgres.persistence.useReadWriteOncePod` | `true` | `false` | NFS volumes only support ReadWriteMany |
| `postgres.persistence.accessModes` | `[ReadWriteOnce]` | `[ReadWriteMany]` | Must match the NFS PV access mode |
| `nginxProxy.enabled` | `false` | `true` | Enables nginx reverse proxy in front of gateway |
| `nginxProxy.persistence.enabled` | `true` | `false` | Only one NFS PV available on test clusters |
| `nginxProxy.image.repository` | `mcpgateway/nginx-cache` | `yosiefeyob1/nginx-cache` | Original image not published; built from infra/nginx/Dockerfile.amd64 |

## Post-Deploy Manual Fixes (Should Be Automated in Chart)

### 1. PgBouncer seccomp Profile
OpenShift's Security Context Constraints (SCC) reject `seccompProfile: RuntimeDefault` for regular service accounts. The PgBouncer deployment template includes this setting, causing pods to fail with `FailedCreate`. Fix by exporting the deployment YAML, removing the seccomp block, and replacing.

**Recommended chart fix:** Make the seccomp profile conditional or remove it for OpenShift compatibility.

### 2. Docker Hub Pull Secret
Docker Hub rate-limits unauthenticated pulls. The PgBouncer (`edoburu/pgbouncer`) and nginx images require authentication. A pull secret must be created and linked to the default service account, then patched into deployments.

**Recommended chart fix:** Support `global.imagePullSecrets` properly so all deployments inherit the pull secret.

### 3. Route Creation
The Helm chart does not create an OpenShift Route. The route must be created manually and should point to the nginx proxy service (not directly to the gateway).

**Recommended chart fix:** Add an optional OpenShift Route template in the chart, gated by a values flag like `route.enabled: true`.

## Nginx Proxy Image

The `mcpgateway/nginx-cache` image referenced in the chart does not exist on Docker Hub. It must be built from the Dockerfile in this repo.

- `infra/nginx/Dockerfile` — Original Red Hat UBI 10 base (requires x86 build environment)
- `infra/nginx/Dockerfile.amd64` — Alpine-based alternative (can be cross-compiled from ARM Macs using `docker buildx`)

To build from an ARM Mac:
```bash
docker buildx create --name mybuilder --use
docker buildx build --platform linux/amd64 -t <your-registry>/nginx-cache:latest -f infra/nginx/Dockerfile.amd64 infra/nginx/ --push
```

## Traffic Flow
```
Browser → OpenShift Route → Nginx Proxy (cache + reverse proxy) → Gateway Pods → PgBouncer → PostgreSQL
```

## Troubleshooting
```bash
# Check all pods
oc get pods -n <your-namespace>

# Check pod logs
oc logs <pod-name> -n <your-namespace> --tail=50

# Check PVC binding
oc get pvc -n <your-namespace>
oc get pv

# Check route
oc get route -n <your-namespace>

# Check secrets
oc get secret -n <your-namespace>

# Full teardown and redeploy
helm uninstall contextforge -n <your-namespace>
oc patch pv nfsx-pv --type=json -p '[{"op":"remove","path":"/spec/claimRef"}]'
```
