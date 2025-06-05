# MCP Context Forge - MCP Gateway Stack Helm Chart

Deploy a complete **MCP Gateway stack** - gateway, PostgreSQL, Redis,
and optional PgAdmin + Redis-Commander UIs-in one command.

> **Why Helm?**
> * Consistent, repeatable installs across Minikube, kind, AKS/EKS/GKE, Rancher, etc.
> * One `values.yaml` drives all environments-tune images, resources, ingress, TLS, persistence, and more.
> * Rolling upgrades & easy rollbacks (`helm history`, `helm rollback`).

---

## Contents

| Folder / File                     | Purpose                                                     |
| --------------------------------- | ----------------------------------------------------------- |
| `Chart.yaml`                      | Chart metadata                                              |
| `values.yaml`                     | All configurable parameters                                 |
| `templates/`                      | Kubernetes manifests (templated)                            |
| `README.md`                       | **← you are here**                                          |

---

## 1 - Prerequisites

| Requirement        | Notes                                                                      |
| ------------------ | -------------------------------------------------------------------------- |
| **Kubernetes ≥ 1.23** | Tested on Minikube, kind, AKS, EKS                                       |
| **Helm 3**         | `brew install helm` / `chocolatey install kubernetes-helm`                 |
| **Ingress**        | Any NGINX-compatible controller for `gateway.local` (or disable Ingress)   |
| **PV provisioner** | Host-path (Minikube) or dynamic RWX volume class for PostgreSQL persistence |

---

## 2 - Quick Start (local sandbox)

```bash
# Clone or untar the chart
git clone https://github.com/<org>/mcp-stack-chart.git
cd mcp-stack-chart

# Optional: tweak values
cp values.yaml my-values.yaml
vim my-values.yaml

# Install
helm install mcp ./mcp-stack \
  --create-namespace -n mcp \
  -f my-values.yaml
```

Verify:

```bash
kubectl get all -n mcp
kubectl get ingress -n mcp
curl http://gateway.local/health
```

> **DNS tip (Minikube):** Enable the `ingress-dns` addon *or* add
> `$(minikube ip) gateway.local` to `/etc/hosts`.

---

## 3 - Architecture

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

## 4 - Configuration (`values.yaml`)

| Key                                  | Default                         | Description                 |
| ------------------------------------ | ------------------------------- | --------------------------- |
| **global.nameOverride**              | `""`                            | Shorten resource names      |
| **mcpContextForge.image.repository** | `ghcr.io/ibm/mcp-context-forge` | Container image             |
| **mcpContextForge.service.port**     | `80`                            | Exposed port inside cluster |
| **mcpContextForge.ingress.enabled**  | `true`                          | Creates an Ingress          |
| **mcpContextForge.ingress.host**     | `gateway.local`                 | Virtual host                |
| **postgres.enabled**                 | `true`                          | Deploy PostgreSQL           |
| **postgres.persistence.size**        | `5Gi`                           | PVC size                    |
| **postgres.credentials.user**        | `admin`                         | DB user (stored in Secret)  |
| **redis.enabled**                    | `true`                          | Deploy Redis                |
| **pgadmin.enabled**                  | `false`                         | Deploy PgAdmin UI           |
| **redisCommander.enabled**           | `false`                         | Deploy Redis-Commander UI   |

*(See `values.yaml` for the full, annotated list.)*

---

## 5 - Common Tweaks

### Use a private registry

```yaml
global:
  imagePullSecrets:
    - name: regcred
mcpContextForge:
  image:
    repository: my-registry.local/mcp-context-forge
    tag: v2.0.0
```

### Enable PgAdmin & Redis-Commander

```yaml
pgadmin:
  enabled: true
redisCommander:
  enabled: true
```

### Disable persistence (ephemeral DB)

```yaml
postgres:
  persistence:
    enabled: false
```

---

## 6 - Upgrading / Rollback

```bash
# Upgrade with new image
helm upgrade mcp ./mcp-stack \
  --set mcpContextForge.image.tag=v1.1.0

# Roll back to previous revision
helm rollback mcp 1
```

---

## 7 - Uninstall

```bash
helm uninstall mcp -n mcp
```

Persistent volumes created with host-path remain; delete them manually if desired.

---

## 8 - Development & Testing

* Lint: `helm lint ./mcp-stack`
* Dry-run template rendering: `helm template mcp ./mcp-stack | less`
* Continuous reload (skaffold / tilt) possible-see `examples/dev/`.

---

## 9 - Contributing

1. Fork & create a branch.
2. Update templates or `values.yaml`.
3. Run `helm lint` and `helm template` against Minikube.
4. Submit a PR-thanks!
