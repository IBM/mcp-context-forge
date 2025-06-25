# MCP Gateway Stack – Helm Chart

Deploy the full **MCP Gateway Stack**-MCP Context Forge gateway, PostgreSQL, Redis, and optional PgAdmin & Redis‑Commander UIs-on any Kubernetes distribution with a single Helm release. The chart lives in [`charts/mcp-stack`](https://github.com/IBM/mcp-context-forge/tree/main/charts/mcp-stack).

---

## Table of Contents

1. [Architecture](#architecture)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Verify Deployment](#verify-deployment)
5. [Customising `values.yaml`](#customising-valuesyaml)
6. [Upgrade & Rollback](#upgrade--rollback)
7. [Uninstall](#uninstall)
8. [CI/CD & OCI Push](#cicd--oci-push)
9. [Troubleshooting](#troubleshooting)
10. [Common Values Reference](#common-values-reference)
11. [Further Reading](#further-reading)
12. [Contributing](#contributing)

---

## Architecture

```
          ┌─────────────────────────────┐
          │      NGINX Ingress          │
          └──────────┬───────────┬──────┘
                     │/          │/
      ┌──────────────▼─────┐ ┌────▼───────────┐
      │  MCP Context Forge │ │ PgAdmin (opt.) │
      └─────────┬──────────┘ └────┬───────────┘
                │                 │
   ┌────────────▼──────┐ ┌────────▼────────────┐
   │    PostgreSQL     │ │ Redis Commander(opt)│
   └────────┬──────────┘ └────────┬────────────┘
            │                     │
      ┌─────▼────┐          ┌─────▼────┐
      │   PV     │          │  Redis   │
      └──────────┘          └──────────┘
```

---

## Prerequisites

* **Kubernetes ≥ 1.23** – Minikube, kind, EKS, AKS, GKE, OpenShift …
* **Helm 3** – Install via Homebrew, Chocolatey, or cURL script
* **kubectl** – Configured to talk to the target cluster
* **Ingress controller** – NGINX, Traefik, or cloud‑native (or disable via values)
* **RWX StorageClass** – Required for PostgreSQL PVC unless `postgres.persistence.enabled=false`

### Pre‑flight checklist

```bash
# Check current context and cluster
kubectl config current-context
kubectl cluster-info

# Verify permissions
kubectl auth can-i create namespace
kubectl auth can-i create deployment -n default
kubectl auth can-i create clusterrolebinding

# Ensure server version ≥ v1.23
kubectl version -o json | jq -r '.serverVersion.gitVersion'

# Confirm a RWX StorageClass exists
kubectl get sc

# Confirm an ingress controller is running
kubectl get pods -A | grep -E 'ingress|traefik|nginx' || echo "No ingress controller found"
```

---

## Quick Start

```bash
# Clone the repo and enter the chart directory
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge/charts/mcp-stack

# (Optional) customise values
cp values.yaml my-values.yaml
vim my-values.yaml

# Install / upgrade (idempotent)
helm upgrade --install mcp-stack . \
  --namespace mcp \
  --create-namespace \
  -f my-values.yaml \
  --wait --timeout 30m
```

If you are running locally, add the line below to `/etc/hosts` (or enable the Minikube *ingress‑dns* addon):

```text
$(minikube ip)  gateway.local
```

---

## Verify Deployment

```bash
# All resources should be Running / Completed
kubectl get all -n mcp
helm status mcp-stack -n mcp

# Check ingress (if enabled)
kubectl get ingress -n mcp
curl http://gateway.local/health

# No ingress? Port‑forward instead
kubectl port-forward svc/mcp-stack-app 8080:80 -n mcp
curl http://localhost:8080/health
```

---

## Customising `values.yaml`

Below is a minimal example. Copy the default file and adjust for your environment.

```yaml
mcpContextForge:
  image:
    repository: ghcr.io/ibm/mcp-context-forge
    tag: 0.2.0
  ingress:
    enabled: true
    host: gateway.local   # replace with real DNS
    className: nginx
  envFrom:
    - secretRef:
        name: mcp-gateway-secret
    - configMapRef:
        name: mcp-gateway-config

postgres:
  credentials:
    user: admin
    password: S3cuReP@ss   # use a Secret in production
  persistence:
    size: 10Gi

pgadmin:
  enabled: false

redisCommander:
  enabled: false

rbac:
  create: true
```

Validate your changes with:

```bash
helm lint .
```

---

## Upgrade & Rollback

```bash
# Upgrade only the gateway image
ahelm upgrade mcp-stack . -n mcp \
  --set mcpContextForge.image.tag=v1.2.3 \
  --wait

# Preview changes (requires helm‑diff plugin)
helm plugin install https://github.com/databus23/helm-diff
helm diff upgrade mcp-stack . -n mcp -f my-values.yaml

# Roll back to revision 1
helm rollback mcp-stack 1 -n mcp
```

---

## Uninstall

```bash
helm uninstall mcp-stack -n mcp

# Optional cleanup
akubectl delete pvc --all -n mcp
kubectl delete namespace mcp
```

---

## CI/CD & OCI Push

```bash
# Lint and package
helm lint .
helm package . -d dist/

# Push the package to GitHub Container Registry (only for mcp-context-forge release managers!)
helm push dist/mcp-stack-*.tgz oci://ghcr.io/ibm/mcp-context-forge
```

Use the OCI URL below in Argo CD or Flux:

```
oci://ghcr.io/ibm/mcp-context-forge
```

---

## Troubleshooting

| Symptom                  | Possible Cause                        | Quick Fix                                          |
| ------------------------ | ------------------------------------- | -------------------------------------------------- |
| `ImagePullBackOff`       | Image missing or private              | Check image tag & ensure pull secret is configured |
| Ingress 404 / no address | Controller not ready or host mismatch | `kubectl get ingress`, verify DNS / `/etc/hosts`   |
| `CrashLoopBackOff`       | Bad configuration / missing env vars  | `kubectl logs` and `kubectl describe pod …`        |
| Env vars missing         | Secret/ConfigMap not mounted          | Confirm `envFrom` refs and resource existence      |
| RBAC access denied       | Roles/Bindings not created            | Set `rbac.create=true` or add roles manually       |

---

## Common Values Reference

| Key                               | Default         | Description                    |
| --------------------------------- | --------------- | ------------------------------ |
| `mcpContextForge.image.tag`       | `latest`        | Gateway image version          |
| `mcpContextForge.ingress.enabled` | `true`          | Create Ingress resource        |
| `mcpContextForge.ingress.host`    | `gateway.local` | External host                  |
| `postgres.credentials.user`       | `admin`         | DB username                    |
| `postgres.persistence.enabled`    | `true`          | Enable PVC                     |
| `postgres.persistence.size`       | `10Gi`          | PostgreSQL volume size         |
| `pgadmin.enabled`                 | `false`         | Deploy PgAdmin UI              |
| `redisCommander.enabled`          | `false`         | Deploy Redis‑Commander UI      |
| `rbac.create`                     | `true`          | Auto‑create Role & RoleBinding |

For every setting see the [full annotated `values.yaml`](https://github.com/IBM/mcp-context-forge/blob/main/charts/mcp-stack/values.yaml).

---

## Further Reading

* Helm: [https://helm.sh/docs/](https://helm.sh/docs/)
* Helm Diff plugin: [https://github.com/databus23/helm-diff](https://github.com/databus23/helm-diff)
* Helm OCI registries: [https://helm.sh/docs/topics/registries/](https://helm.sh/docs/topics/registries/)
* Kubernetes Ingress: [https://kubernetes.io/docs/concepts/services-networking/ingress/](https://kubernetes.io/docs/concepts/services-networking/ingress/)
* Network Policies: [https://kubernetes.io/docs/concepts/services-networking/network-policies/](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
* Argo CD: [https://argo-cd.readthedocs.io/](https://argo-cd.readthedocs.io/)
* Flux: [https://fluxcd.io/](https://fluxcd.io/)

---

## Contributing

1. Fork the repo and create a feature branch.
2. Update templates or `values.yaml`.
3. Test with `helm lint` and `helm template`.
4. Open a pull request-thank you!
