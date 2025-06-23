# 🚀 Deploying the MCP Gateway Stack with Helm

*Full-length guide - includes Secrets, ConfigMaps, and verification steps.*

---

## ✅ Pre-flight Checks

Run these checks **before** touching the cluster.

```bash
# What cluster am I connected to?
kubectl config current-context
kubectl cluster-info

# Do I have the right permissions?
kubectl auth can-i create namespace
kubectl auth can-i create deployment -n default
kubectl auth can-i create clusterrolebinding

# Kubernetes version (must be ≥ 1.23)
kubectl version -o json | jq -r '.serverVersion.gitVersion'

# Storage availability
kubectl get sc

# Ingress controller present?
kubectl get pods -A | grep -E 'ingress|traefik|nginx' || echo "No ingress controller found"
```

??? failure "Troubleshooting common issues"
    - **No ingress controller?**

      Ask the cluster admin to deploy one, ex: https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml

    - **No RWX StorageClass?**

      Install one, e: NFS-Subdir-External-Provisioner or use `hostPath` in Minikube/kind.

    - **Missing permissions?**

      Ask a cluster-admin or choose a namespace where you have `Role/RoleBinding`.

---

## 🔐 Prepare the Private Namespace

```bash
# Create namespace
kubectl create namespace mcp-private --dry-run=client -o yaml | kubectl apply -f -

# Label / annotate
kubectl label namespace mcp-private environment=prod --overwrite
kubectl annotate namespace mcp-private "config.kubernetes.io/owner=mcp" --overwrite
```

### Default-deny NetworkPolicy

```bash
cat <<'EOF' | kubectl apply -n mcp-private -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-by-default
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
EOF
```

```bash
# Quick sanity check
kubectl get ns mcp-private
kubectl get networkpolicy -n mcp-private
kubectl get sa default -n mcp-private -o yaml
```

---

## 🔑 Create Secrets and ConfigMaps

> **Important:** Keep real values out of Git. Use sealed-secrets, SOPS, or your vault of choice in production.

```bash
# --- 1. Environment variables (local shell) ---
export BASIC_AUTH_USER=admin
export BASIC_AUTH_PASSWORD=changeme
export JWT_SECRET_KEY=$(openssl rand -base64 32)   # or provide your own

# --- 2. Kubernetes Secret ---
kubectl create secret generic mcp-gateway-secret \
  --namespace mcp-private \
  --from-literal=BASIC_AUTH_USER="$BASIC_AUTH_USER" \
  --from-literal=BASIC_AUTH_PASSWORD="$BASIC_AUTH_PASSWORD" \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET_KEY"

# --- 3. Optional ConfigMap for app settings ---
cat <<'EOF' | kubectl apply -n mcp-private -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-gateway-config
data:
  LOG_LEVEL: "info"
EOF
```

### Verify Secrets / ConfigMaps

```bash
# Inspect (values are base64)
kubectl get secret mcp-gateway-secret -n mcp-private -o yaml
kubectl get configmap mcp-gateway-config -n mcp-private -o yaml

# Decode and check a single key
kubectl get secret mcp-gateway-secret -n mcp-private -o jsonpath='{.data.BASIC_AUTH_USER}' | base64 -d
kubectl get secret mcp-gateway-secret -n mcp-private -o jsonpath='{.data.BASIC_AUTH_PASSWORD}' | base64 -d
```

---

## ⚙️ Clone and Customize the Helm Chart

```bash
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge/charts/mcp-stack
cp values.yaml my-values.yaml
```

Edit **`my-values.yaml`**:

```yaml
# ── MCP Context Forge ────────────────────────────────
mcpContextForge:
  image:
    repository: ghcr.io/ibm/mcp-context-forge
    tag: v1.0.0
  ingress:
    enabled: true
    host: gateway.local            # Change to your FQDN
    className: nginx

  # Mount secret as env
  envFrom:
    - secretRef:
        name: mcp-gateway-secret
    - configMapRef:
        name: mcp-gateway-config

# ── PostgreSQL ───────────────────────────────────────
postgres:
  credentials:
    user: admin
    password: S3cuReP@ss           # Use K8s Secret in prod
  persistence:
    size: 10Gi

# ── Optional components ─────────────────────────────
pgadmin:
  enabled: false

redisCommander:
  enabled: false

# ── RBAC ────────────────────────────────────────────
rbac:
  create: true
```

Validate:

```bash
helm lint .
```

---

## 🚀 Install the Stack

```bash
helm upgrade --install mcp-stack . \
  --namespace mcp-private \
  --create-namespace=false \
  -f my-values.yaml \
  --wait --timeout 30m --debug
```

---

## ✅ Verify the Deployment

```bash
kubectl get all -n mcp-private
helm status mcp-stack -n mcp-private --show-desc

# If there are failures inspect any failing pods, example:
# Describe (events are at the bottom)
kubectl describe pod postgres-5cc7df45cb-p4msg -n mcp-private

# Most recent container log
kubectl logs postgres-5cc7df45cb-p4msg -n mcp-private --tail=100

# Previous log (the one that crashed)
kubectl logs postgres-5cc7df45cb-p4msg -n mcp-private --tail=100 -p
```

### Ingress test

```bash
kubectl get ingress -n mcp-private
curl http://gateway.local/health

# or
# Ingress (if you enabled it in values.yaml)
kubectl get ingress -n mcp-private

# Cluster-internal services
kubectl get svc     -n mcp-private

# Forward a port and test it
kubectl port-forward -n mcp-private svc/mcp-stack-app 8080:80
```

### Secret injection test

```bash
# Pick a running pod
POD=$(kubectl get pods -n mcp-private -l app.kubernetes.io/instance=mcp-stack -o jsonpath='{.items[0].metadata.name}')

# Check env variables inside the pod
kubectl exec -n mcp-private "$POD" -- printenv | grep -E 'BASIC_AUTH|JWT_SECRET_KEY' || echo "❌ env vars missing"

# Validate that secret was mounted via envFrom
kubectl exec -n mcp-private "$POD" -- /bin/sh -c 'echo $BASIC_AUTH_USER'
```

### RBAC test

```bash
kubectl auth can-i list pods \
  --as=system:serviceaccount:mcp-private:mcp-stack-sa \
  -n mcp-private
```

??? failure "ServiceAccount returns 'no'?"

    1. **Does the SA exist?**


    ```bash
    kubectl get sa mcp-stack-sa -n mcp-private
    ```

    2. **Role / RoleBinding created?**

    ```bash
    kubectl get role,rolebinding -n mcp-private | grep mcp-stack
    ```

    3. **Role verbs correct?**

    ```bash
    kubectl describe role <name> -n mcp-private
    ```


---

## 🩺 Debug and Rollback

???+ example "Useful commands"

    ```bash
    # Logs from all containers
    kubectl logs -l app.kubernetes.io/instance=mcp-stack -n mcp-private --all-containers

    # Describe a specific pod
    kubectl describe pod <pod-name> -n mcp-private

    # PVC events
    kubectl describe pvc -n mcp-private

    # What will change (requires plugin)
    helm plugin install https://github.com/databus23/helm-diff
    helm diff upgrade mcp-stack . -n mcp-private -f my-values.yaml

    # Roll back
    helm rollback mcp-stack 1 -n mcp-private
    ```


??? danger "Common issues and quick fixes"

    | Symptom              | Likely Cause                   | Fix                                        |
    |----------------------|--------------------------------|--------------------------------------------|
    | `ImagePullBackOff`   | Wrong image/tag or no registry | Check `values.yaml` image settings         |
    | Ingress 404          | Wrong host or class            | Verify host DNS, ingressClassName          |
    | Env vars missing     | Secret not mounted             | Check `envFrom` in `values.yaml`           |
    | RBAC 'no' response   | Missing verbs in Role          | Add `get,list,watch` or set `rbac.create`  |

---

## 🧹 Clean-up

```bash
helm uninstall mcp-stack -n mcp-private
kubectl delete namespace mcp-private
```

## Delete all and start again

```bash
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

---

## 📚 References

* [Helm](https://helm.sh/docs/)
* [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
* [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
* [Helm Diff Plugin](https://github.com/databus23/helm-diff)

---

✅ *MCP Gateway deployed with Secrets, ConfigMaps, RBAC, verification, and rollback baked in.*
