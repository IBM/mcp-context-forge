# 🚢 Deploying the MCP Gateway Stack with **Argo CD**

This guide shows how to operate the **MCP Gateway Stack** with a *Git‑Ops* workflow powered by [Argo CD](https://argo-cd.readthedocs.io). Once wired up, every commit to the repository becomes an automatic deployment (or rollback) to your Kubernetes cluster.

> 🌳 Git source of truth:
> `https://github.com/IBM/mcp-context-forge`
>
> * **App manifests:** `k8s/` (Kustomize‑ready)
> * **Helm chart (optional):** `charts/mcp-stack`

---

## 📋 Prerequisites

| Requirement       | Notes                                                            |
| ----------------- | ---------------------------------------------------------------- |
| Kubernetes ≥ 1.23 | Local (Minikube/kind) or managed (EKS, AKS, GKE, etc.)           |
| Argo CD ≥ 2.7     | Server & CLI (this guide installs server into the cluster)       |
| kubectl           | Configured to talk to the target cluster                         |
| Git access        | The cluster must be able to pull the repo (public or deploy‑key) |

---

## 🛠 Step 1 – Install Argo CD (once per cluster)

```bash
# Namespace + core components
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for the server component
kubectl -n argocd rollout status deploy/argocd-server
```

### Install the CLI

```bash
# macOS
brew install argocd

# Linux (single‑binary)
curl -sSL -o /tmp/argocd \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 /tmp/argocd /usr/local/bin/argocd
```

Verify:

```bash
argocd version --client
```

---

## 🔐 Step 2 – Initial Login

Forward the API/UI to your workstation (leave running):

```bash
kubectl -n argocd port-forward svc/argocd-server 8083:443
```

Fetch the one‑time admin password and log in:

```bash
PASS="$(kubectl -n argocd get secret argocd-initial-admin-secret \
          -o jsonpath='{.data.password}' | base64 -d)"
argocd login localhost:8083 \
  --username admin --password "$PASS" --insecure
```

Open the web UI → [http://localhost:8083](http://localhost:8083) (credentials above).

---

## 🚀 Step 3 – Bootstrap the Application

Create an Argo CD *Application* that tracks the **`k8s/`** folder from the main branch:

```bash
APP=mcp-gateway
REPO=https://github.com/IBM/mcp-context-forge.git

argocd app create "$APP" \
  --repo "$REPO" \
  --path k8s \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated \
  --revision main
```

Trigger the first sync:

```bash
argocd app sync "$APP"
```

Argo CD will apply all manifests and keep them in the *Synced* 🌿 / *Healthy* 💚 state.

---

## ✅ Step 4 – Verify Deployment

```bash
kubectl get pods,svc,ingress
argocd app list
argocd app get mcp-gateway
```

If using the sample Ingress:

```bash
curl http://gateway.local/health
```

Otherwise, port‑forward:

```bash
kubectl port-forward svc/mcp-context-forge 8080:80 &
curl http://localhost:8080/health
```

---

## 🔄 Day‑2 Operations

### Sync after a new commit

```bash
argocd app sync mcp-gateway
```

### View diff before syncing

```bash
argocd app diff mcp-gateway
```

### Roll back to a previous revision

```bash
argocd app history mcp-gateway
argocd app rollback mcp-gateway <REVISION>
```

### Disable / enable auto‑sync

```bash
# Pause auto‑sync
a rgocd app set mcp-gateway --sync-policy none
# Re‑enable
argocd app set mcp-gateway --sync-policy automated
```

---

## 🧹 Uninstall

```bash
# Delete the application (leaves cluster objects intact)
argocd app delete mcp-gateway --yes

# Remove Argo CD completely\ nkubectl delete ns argocd
```

---

## 🧰 Makefile Shortcuts

The repository ships with ready‑made targets:

| Target                      | Action                                                                 |
| --------------------------- | ---------------------------------------------------------------------- |
| `make argocd-install`       | Installs Argo CD server into the current cluster                       |
| `make argocd-forward`       | Port‑forwards UI/API on [http://localhost:8083](http://localhost:8083) |
| `make argocd-app-bootstrap` | Creates & auto‑syncs the *mcp‑gateway* application                     |
| `make argocd-app-sync`      | Forces a manual sync                                                   |

Run `make help` to list them all.

---

## 🧯 Troubleshooting

| Symptom            | Fix                                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| `ImagePullBackOff` | Check image name / pull secret & that the repo is public or credentials are configured in Argo CD |
| `SyncFailed`       | `argocd app logs mcp-gateway` for details; often due to immutable fields                          |
| Web UI 404         | Ensure `argocd-forward` is still running, or expose via Ingress/LoadBalancer                      |
| RBAC denied        | Argo CD needs ClusterRoleBinding for non‑default namespaces – see docs                            |

---

## 📚 Further Reading

* Argo CD Docs – [https://argo-cd.readthedocs.io](https://argo-cd.readthedocs.io)
* GitOps Pattern – [https://www.weave.works/technologies/gitops/](https://www.weave.works/technologies/gitops/)
* Kustomize – [https://kubectl.docs.kubernetes.io/references/kustomize/](https://kubectl.docs.kubernetes.io/references/kustomize/)
* Helm + Argo CD – [https://argo-cd.readthedocs.io/en/stable/user-guide/helm/](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
