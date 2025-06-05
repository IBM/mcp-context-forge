# 🚀 Helm Quick-Start Guide (any Kubernetes cluster)

This doc shows how to use Helm to install, upgrade, and remove the MCP Gateway with PostgreSQL, Redis, PgAdmin and Redis on **any** Kubernetes cluster—local (*kind*, Docker Desktop, Minikube), on-prem (RKE, Rancher), or managed (*EKS*, *AKS*, *GKE*, *Openshift*, etc.).

---

## 📋 Prerequisites

| Requirement                   | Notes & Minimum Versions                                                                       |
| ----------------------------- | ---------------------------------------------------------------------------------------------- |
| **Kubernetes**                | Cluster reachable by `kubectl`; tested on v1.23 – v1.30                                        |
| **Helm 3**                    | [https://helm.sh/docs/intro/install/](https://helm.sh/docs/intro/install/)                     |
| **kubectl**                   | `kubectl version --short` should return client *and* server                                    |
| **Container registry access** | If images are private, configure `imagePullSecrets` or `docker login` on all nodes             |
| **(Ingress)**                 | Either an Ingress controller **or** a cloud LB Service class, depending on how you expose HTTP |

---

## 1 — Install Helm & kubectl

### macOS (Homebrew)

```bash
brew install helm kubernetes-cli
```

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
# kubectl:
curl -LO "https://dl.k8s.io/release/$(curl -sSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -m 0755 kubectl /usr/local/bin
```

### Windows (PowerShell + Chocolatey)

```powershell
choco install -y kubernetes-helm kubernetes-cli
```

Verify:

```bash
helm version
kubectl version --short
kubectl config get-contexts   # choose your target context
```

---

## 2 — Lint and (optionally) package

```bash
# Static template check
helm lint charts/mcp-stack

# Optional: package into dist/ for CI or air-gapped clusters
mkdir -p dist
helm package charts/mcp-stack -d dist
```

---

## 3 — Deploy / Upgrade

### 3-A Minimal install (namespace `mcp`)

```bash
helm upgrade --install mcp-stack charts/mcp-stack \
  --namespace mcp --create-namespace \
  --wait     # blocks until Deployments & Jobs are ready
```

### 3-B With environment overrides file

```bash
helm upgrade --install mcp-stack charts/mcp-stack \
  -n mcp --create-namespace \
  -f envs/prod-values.yaml \
  --set mcpContextForge.image.tag=v1.2.3
```

*(The chart's `values.yaml` documents every knob—replicas, resources, ingress host, DB credentials, persistence, …)*

---

## 4 — Verify

```bash
# All resources in the namespace
kubectl get all -n mcp

# Release status
helm status mcp-stack -n mcp

# Tail logs
kubectl logs -n mcp deploy/mcp-stack-app -f
```

### Ingress / Service exposure

* **Ingress controller present** → run `kubectl get ingress -n mcp`.
* **No Ingress** → change `mcpContextForge.service.type` to `LoadBalancer` or `NodePort`.

---

## 5 — Updates & Rollbacks

### Rolling upgrade

```bash
helm upgrade mcp-stack charts/mcp-stack -n mcp \
  --set mcpContextForge.image.tag=v1.3.0
```

### Diff before upgrade (requires plugin)

```bash
helm plugin install https://github.com/databus23/helm-diff   # once
helm diff upgrade mcp-stack charts/mcp-stack -n mcp -f values.yaml
```

### Roll back

```bash
helm rollback mcp-stack <REVISION> -n mcp
# list revisions:
helm history mcp-stack -n mcp
```

---

## 6 — Uninstall

```bash
helm uninstall mcp-stack -n mcp
# Optional: delete namespace / PVCs
kubectl delete ns mcp
```

Persistent volumes created with the namespace remain until you delete the PVC/PV objects (or the storage class policy garbage-collects them).

---

## 7 — Troubleshooting Cheatsheet

| Symptom                              | Quick check                                           |                                                      |
| ------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------- |
| Pods stuck in `ImagePullBackOff`     | `kubectl describe pod …` → pull secret / repo access  |                                                      |
| `CrashLoopBackOff`                   | `kubectl logs …` → env vars, DB connectivity          |                                                      |
| Ingress 404 / no address             | \`kubectl get svc -A                                  | grep ingress\` – controller running? LB provisioned? |
| Helm hook failures (Jobs)            | `kubectl get jobs -n mcp && kubectl logs job/<name>`  |                                                      |
| Template error during `helm install` | `helm lint charts/mcp-stack` or run \`helm template … | yq\`                                                 |

---

## 8 — CI/CD tips

* **Package once** → push chart (`.tgz`) to OCI registry (`helm push` with `oci://` URLs) or `chartmuseum`.
* **Values per environment** → `values-dev.yaml`, `values-prod.yaml`, etc.
* **GitOps** → use Argo CD / Flux to watch the chart + values in Git and auto-sync.

---

## 🌐 Further reading

* Helm docs – [https://helm.sh/docs/](https://helm.sh/docs/)
* Kubernetes Ingress concepts – [https://kubernetes.io/docs/concepts/services-networking/ingress/](https://kubernetes.io/docs/concepts/services-networking/ingress/)
* Persistent Volumes – [https://kubernetes.io/docs/concepts/storage/persistent-volumes/](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

---

Deploying with Helm turns your stack into a versioned, repeatable artefact—ideal for local dev, staging, and production alike.
