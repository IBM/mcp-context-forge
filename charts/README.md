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

You can use the `helm template` and `yq` and check your templates. Example:

```bash
helm lint .
helm template . | yq '.spec.template.spec.containers[0] | {readinessProbe,livenessProbe}'
helm template mcp-stack . -f my-values.yaml > /tmp/all.yaml
```

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

## Features

* 🗂️ Multi-service stack – Deploys MCP Gateway (`n` replicas), Fast-Time-Server (`n` replicas), Postgres 17, Redis, PGAdmin 4 and Redis-Commander out of the box.
* 🎛️ Idiomatic naming – All objects use helper templates (`mcp-stack.fullname`, chart labels) so release names and overrides stay collision-free.
* 🔐 Secrets & credentials – `mcp-stack-gateway-secret` (Basic-Auth creds, JWT signing key, encryption salt, …) and `postgres-secret` (DB user / password / database name), both injected via `envFrom`.
* ⚙️ Config as code – `mcp-stack-gateway-config` (\~40 tunables) and `postgres-config` for the DB name.
* 🔗 Derived URLs – Pods build `DATABASE_URL` and `REDIS_URL` from explicit host/port/user/pass variables—no hard-coding.
* ❤️‍🩹 Health management – Readiness and liveness probes on every deployment; the Gateway also has a startupProbe.
* 🚦 Resource safeguards – CPU and memory requests/limits set for all containers.
* 💾 Stateful storage – PV + PVC for Postgres (`/var/lib/postgresql/data`), storage class selectable.
* 🌐 Networking & access – ClusterIP services, optional NGINX Ingress, and `NOTES.txt` with port-forward plus safe secret-fetch commands (password, bearer token, `JWT_SECRET_KEY`).
* 📈 Replicas & availability – Gateway (3) and Fast-Time-Server (2) provide basic HA; stateful components run single-instance.
* 📦 Helm best-practice layout – Clear separation of Deployments, Services, ConfigMaps, Secrets, PVC/PV and Ingress; chart version 0.2.0.

---

## TODO / Future roadmap

1. 🔄 Post-deploy hook to register MCP Servers with MCP Gateway
2. ⏳ Add startup probes for slow-booting services
3. 🛡️ Implement Kubernetes NetworkPolicies to restrict internal traffic
4. ⚙️ Add Horizontal Pod Autoscaler (HPA) support
5. 📊 Expose Prometheus metrics and add scrape annotations
6. 📈 Bundle Grafana dashboards via ConfigMaps (optional)
7. 🔐 Integrate External Secrets support (e.g., AWS Secrets Manager)
8. 🧪 Add Helm test hooks to validate deployments
9. 🔍 Add `values.schema.json` for values validation and better UX
10. 🧰 Move static configuration to templated `ConfigMaps` where possible
11. 📁 Include persistent storage toggle in `values.yaml` for easier local/dev setup
12. 🧼 Add Helm pre-delete hook for cleanup tasks (e.g., deregistering from external systems)
13. 🧩 Package optional CRDs if needed in the future (e.g., for custom integrations)

## Debug / start fresh (delete namespace)

```bash
# 0. Create and customize the values
cp values.yaml my-values.yaml

# 1. Verify the release name and namespace
helm list -A | grep mcp-stack

# 2. Uninstall the Helm release (removes Deployments, Services, Secrets created by the chart)
helm uninstall mcp-stack -n mcp-private

# 3. Delete any leftover PersistentVolumeClaims *if* you don't need the data
kubectl delete pvc --all -n mcp-private

# 4. Remove the namespace itself (skips if you want to keep it)
kubectl delete namespace mcp-private

# 5. Optional: confirm nothing is left
helm list -A | grep mcp-stack   # should return nothing
kubectl get ns | grep mcp-private  # should return nothing

# 6. Re-create the namespace (if you deleted it)
kubectl create namespace mcp-private

# 7. Re-install the chart with your values file
helm upgrade --install mcp-stack . \
  --namespace mcp-private \
  -f my-values.yaml \
  --wait --timeout 15m --debug

# 8. Check status
kubectl get all -n mcp-private
helm status mcp-stack -n mcp-private --show-desc
```
