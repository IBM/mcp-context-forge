# 🚀 Deploying the MCP Gateway Stack to IBM Cloud Kubernetes Service with Argo CD

!!! warning "Preview"
    This guide is in preview and will continue to evolve. Content is accurate but may receive refinements as the Helm chart and GitOps flows mature.

!!! abstract "What you'll achieve"

    * Build or pull the OCI image(s) for MCP Gateway
    * Push them to **IBM Container Registry (ICR)**
    * Provision an **IKS** cluster with VPC-native networking
    * Install & bootstrap **Argo CD** for GitOps management
    * Deploy the MCP Stack Helm chart via Argo CD
    * Configure MCP Gateway with servers and tools
    * Connect clients (VS Code Copilot, LangChain Agent, Claude Desktop)
    * Set up observability, scaling, and managed databases

## Solution Architecture

```mermaid
flowchart TD
    %% ---------------- Git ----------------
    subgraph Git
        repo["Helm values<br/>+ Argo App CR"]
    end

    %% ---------------- CI/CD --------------
    subgraph "CI/CD"
        build["Build &amp; Push<br/>OCI Image"]
    end

    %% ---------------- IBM Cloud ----------
    subgraph "IBM Cloud"
        vpc["VPC + Subnets"]
        iks["IKS Cluster"]
        icr["ICR<br/>eu.icr.io"]
        argocd["Argo CD"]
        helm["Helm Release<br/>mcp-stack"]
        gateway["MCP Gateway Pods"]
        db["PostgreSQL PVC"]
        redis["Redis PVC"]
        kms["Key Protect KMS"]
        secrets["Secrets Manager"]
        logs["Cloud Logs"]
    end

    %% ---------------- Clients ------------
    subgraph Clients
        vscode["VS Code Copilot"]
        claude["Claude Desktop"]
        langchain["LangChain Agent"]
    end

    %% ---------- Styling for IBM Cloud ----
    classDef cloud fill:#f5f5f5,stroke:#c6c6c6;
    class vpc,iks,icr,argocd,helm,gateway,db,redis,kms,secrets,logs cloud;

    %% ------------ Edges ------------------
    repo   -- "git push"      --> build
    build  -- "docker push"   --> icr
    repo   -- "App CR"        --> argocd
    argocd -- "helm upgrade"  --> iks
    icr    -- "ImagePull"     --> iks
    iks    --> db
    iks    --> redis
    helm   -- "Deploy"        --> gateway
    secrets-- "TLS certs"     --> iks
    kms    -- "encryption"    --> iks
    logs   -- "audit logs"    --> iks
    gateway-- "SSE/stdio"     --> vscode
    gateway-- "wrapper"       --> claude
    gateway-- "HTTP API"      --> langchain
```

---

## Prerequisites

| Requirement                                                                                 | Minimum | Reference                                                        |
| ------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------- |
| **IBM Cloud CLI**                                                                           | ≥ 2.16  | [https://clis.cloud.ibm.com](https://clis.cloud.ibm.com)         |
| CLI plugins - `container-registry`, `kubernetes-service`, `vpc-infrastructure`, `secrets-manager`, `logs` | latest  | `ibmcloud plugin install ...`                                      |
| **kubectl**                                                                                 | ≥ 1.25  | [https://kubernetes.io/](https://kubernetes.io/)                 |
| **Helm 3**                                                                                  | ≥ 3.12  | [https://helm.sh/](https://helm.sh/)                             |
| **git**, **podman**/**docker**                                                              | -       | distro packages                                                  |
| **Argo CD CLI**                                                                             | ≥ 2.9   | [https://argo-cd.readthedocs.io](https://argo-cd.readthedocs.io) |
| IBM Cloud account with VPC quota                                                            | -       | free tier works                                                  |

!!! info "Quick sanity check"
    ```bash
    kubectl version --short
    helm version
    ibmcloud --version
    ```

---

## 1. Clone & Prepare the Repository

```bash
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge

# Optional local build for testing
podman build -t mcp-context-forge:dev -f Containerfile .
```

!!! note "Production deployments"
    Production deployments can pull the signed image directly:
    ```
    ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
    ```

---

## 2. IBM Cloud Account Setup

### 2.1. Authentication, Region & Resource Group

```bash
ibmcloud login --sso                       # or: ibmcloud login --apikey "$IBMCLOUD_API_KEY"
ibmcloud target -r eu-de -g Default
```

### 2.2. Install Required CLI Plugins

```bash
ibmcloud plugin install container-registry -f
ibmcloud plugin install kubernetes-service -f
ibmcloud plugin install vpc-infrastructure -f
ibmcloud plugin install secrets-manager -f
ibmcloud plugin install logs -f
```

### 2.3. Create VPC and Networking (one-time)

```bash
# Create VPC
ibmcloud is vpc-create mcp-vpc --resource-group Default

# Create subnet in each zone for HA
ibmcloud is subnet-create mcp-subnet-eu-de-1 \
    $(ibmcloud is vpc mcp-vpc --output json | jq -r '.id') \
    --zone eu-de-1 --ipv4-cidr-block 10.10.1.0/24

ibmcloud is subnet-create mcp-subnet-eu-de-2 \
    $(ibmcloud is vpc mcp-vpc --output json | jq -r '.id') \
    --zone eu-de-2 --ipv4-cidr-block 10.10.2.0/24

ibmcloud is subnet-create mcp-subnet-eu-de-3 \
    $(ibmcloud is vpc mcp-vpc --output json | jq -r '.id') \
    --zone eu-de-3 --ipv4-cidr-block 10.10.3.0/24
```

!!! tip "Bring-your-own VPC"
    You can reuse an existing VPC; just skip the commands above and note the IDs.

### 2.4. Provision IBM Cloud Services

| Service                | Purpose                        | CLI Command                                                                              |
| ---------------------- | ------------------------------ | -------------------------------------------------------------------------------------- |
| **Secrets Manager**    | wildcard TLS certs, JWT secret | `ibmcloud resource service-instance-create mcp-secrets secrets-manager standard eu-de` |
| **Key Protect (KMS)**  | CSI envelope encryption        | `ibmcloud resource service-instance-create mcp-kms kms tiered-pricing eu-de`            |
| **Cloud Logs**         | audit & app logs               | `ibmcloud resource service-instance-create mcp-logs logs standard eu-de`                |
| **Container Registry** | host OCI images                | `ibmcloud cr namespace-add mcp-gw`                                                      |

### 2.5. Push Images to IBM Container Registry

```bash
# Login to Container Registry
ibmcloud cr login

# Tag and push the image
podman tag mcp-context-forge:dev eu.icr.io/mcp-gw/mcpgateway:0.9.0
podman push eu.icr.io/mcp-gw/mcpgateway:0.9.0

# Verify the image
ibmcloud cr images --restrict mcp-gw
```

---

## 3. Create IBM Kubernetes Service (IKS) Cluster

### 3.1. Provision the Cluster

```bash
# Get subnet IDs
SUBNET_1=$(ibmcloud is subnets --output json | jq -r '.[] | select(.name=="mcp-subnet-eu-de-1") | .id')
SUBNET_2=$(ibmcloud is subnets --output json | jq -r '.[] | select(.name=="mcp-subnet-eu-de-2") | .id')
SUBNET_3=$(ibmcloud is subnets --output json | jq -r '.[] | select(.name=="mcp-subnet-eu-de-3") | .id')

# Create the cluster with HA across zones
ibmcloud ks cluster create vpc-gen2 \
  --name mcp-cluster \
  --vpc-id $(ibmcloud is vpc mcp-vpc --output json | jq -r '.id') \
  --subnet-id $SUBNET_1 \
  --subnet-id $SUBNET_2 \
  --subnet-id $SUBNET_3 \
  --flavor bx2.4x16 \
  --workers 1 \
  --zones eu-de-1,eu-de-2,eu-de-3 \
  --kms-instance $(ibmcloud resource service-instance mcp-kms --output json | jq -r '.[0].guid')
```

!!! warning "Cluster Provisioning Time"
    Cluster creation takes 15-30 minutes. Monitor progress with:
    ```bash
    ibmcloud ks cluster get --cluster mcp-cluster
    ```

### 3.2. Configure kubectl Access

```bash
ibmcloud ks cluster config --cluster mcp-cluster
kubectl config current-context   # should display mcp-cluster
kubectl get nodes                # verify nodes are Ready
```

### 3.3. Enable Storage Classes

```bash
# List available storage classes
ibmcloud ks storage ls --cluster mcp-cluster

# Enable File Storage (for RWX volumes)
ibmcloud ks storage file enable --cluster mcp-cluster

# Verify storage classes
kubectl get sc
```

---

## 4. Prepare Kubernetes Namespaces and RBAC

```bash
# Create application namespace
kubectl create namespace mcp
kubectl label namespace mcp app=mcp-gateway environment=prod

# Create Argo CD namespace
kubectl create namespace argocd
```

### 4.1. Optional Network Policies

```bash
cat <<'EOF' | kubectl apply -n mcp -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-by-default
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  egress:

  - to: []
    ports:

    - protocol: TCP
      port: 53

    - protocol: UDP
      port: 53

  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
  ingress:

  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx

    - namespaceSelector:
        matchLabels:
          name: argocd
EOF
```

---

## 5. Install and Configure Argo CD

### 5.1. Install Argo CD Server

```bash
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for rollout to complete
kubectl -n argocd rollout status deploy/argocd-server
```

### 5.2. Initial Login and Configuration

```bash
# Port forward Argo CD UI (run in background)
kubectl -n argocd port-forward svc/argocd-server 8080:443 &

# Get initial admin password
PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret \
          -o jsonpath='{.data.password}' | base64 -d)

# Login to Argo CD CLI
argocd login localhost:8080 \
      --username admin --password "$PASSWORD" --insecure

echo "Argo CD admin password: $PASSWORD"
```

!!! tip "Change Default Password"
    Browse to [http://localhost:8080](http://localhost:8080) and change the admin password via the UI.

---

## 6. Configure Git Repository Structure

### 6.1. Create Argo CD Application Definition

Create **`argocd/apps/mcp-stack.yaml`** in your Git repository:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mcp-stack
  namespace: argocd
  finalizers:

    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/IBM/mcp-context-forge
    path: charts/mcp-stack
    targetRevision: main
    helm:
      valueFiles:

        - values.yaml
        - envs/iks/values.yaml   # custom overrides
  destination:
    server: https://kubernetes.default.svc
    namespace: mcp
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:

    - CreateNamespace=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
  revisionHistoryLimit: 10
```

### 6.2. Create Custom Values Override

Create **`charts/mcp-stack/envs/iks/values.yaml`**:

```yaml
# MCP Gateway Configuration
mcpContextForge:
  replicaCount: 2

  image:
    repository: eu.icr.io/mcp-gw/mcpgateway
    tag: "0.9.0"
    pullPolicy: IfNotPresent

  # Service configuration
  service:
    type: ClusterIP
    port: 80
    targetPort: 4444

  # Ingress configuration
  ingress:
    enabled: true
    className: "public-iks-k8s-nginx"
    annotations:
      kubernetes.io/ingress.class: "public-iks-k8s-nginx"
      cert-manager.io/cluster-issuer: "letsencrypt-prod"
    hosts:

      - host: mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>
        paths:

          - path: /
            pathType: Prefix
    tls:

      - secretName: mcp-gateway-tls
        hosts:

          - mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>

  # Environment variables
  env:

    - name: AUTH_REQUIRED
      value: "true"

    - name: HOST
      value: "0.0.0.0"

    - name: PORT
      value: "4444"

    - name: LOG_LEVEL
      value: "INFO"

    - name: CACHE_TYPE
      value: "redis"

  # Resource limits
  resources:
    limits:
      cpu: 1000m
      memory: 1Gi
    requests:
      cpu: 500m
      memory: 512Mi

  # Health checks
  livenessProbe:
    httpGet:
      path: /health
      port: http
    initialDelaySeconds: 30
    periodSeconds: 10

  readinessProbe:
    httpGet:
      path: /health
      port: http
    initialDelaySeconds: 5
    periodSeconds: 5

  # Horizontal Pod Autoscaler
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80

# PostgreSQL Configuration
postgres:
  enabled: true
  auth:
    username: mcpgateway
    database: mcpgateway
    existingSecret: postgres-secret

  primary:
    persistence:
      enabled: true
      storageClass: "ibmc-vpc-block-metro-10iops-tier"
      size: 20Gi

    resources:
      limits:
        cpu: 1000m
        memory: 1Gi
      requests:
        cpu: 500m
        memory: 512Mi

# Redis Configuration
redis:
  enabled: true
  auth:
    enabled: true
    existingSecret: redis-secret

  master:
    persistence:
      enabled: true
      storageClass: "ibmc-vpc-block-metro-10iops-tier"
      size: 8Gi

    resources:
      limits:
        cpu: 500m
        memory: 512Mi
      requests:
        cpu: 250m
        memory: 256Mi

# RBAC
rbac:
  create: true

# ServiceAccount
serviceAccount:
  create: true
  annotations:
    iks.ibm.com/pod-security-policy: "ibm-privileged-psp"

# PodSecurityPolicy for IKS
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1001
  fsGroup: 1001

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1001
  capabilities:
    drop:

    - ALL

# Network Policy
networkPolicy:
  enabled: true
  ingress:

    - from:
      - namespaceSelector:
          matchLabels:
            name: ingress-nginx
      ports:

      - protocol: TCP
        port: 4444
  egress:

    - to: []
      ports:

      - protocol: TCP
        port: 53

      - protocol: UDP
        port: 53

    - to:
      - namespaceSelector:
          matchLabels:
            name: kube-system
```

!!! important "Replace Placeholder"
    Replace `<CLUSTER_INGRESS_SUBDOMAIN>` with your actual cluster's ingress subdomain:
    ```bash
    ibmcloud ks cluster get --cluster mcp-cluster | grep "Ingress Subdomain"
    ```

### 6.3. Create Required Secrets

```bash
# Generate strong passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
JWT_SECRET=$(openssl rand -hex 32)
BASIC_AUTH_PASSWORD=$(openssl rand -base64 16)

# Create PostgreSQL secret
kubectl create secret generic postgres-secret -n mcp \
  --from-literal=postgres-password="$POSTGRES_PASSWORD"

# Create Redis secret
kubectl create secret generic redis-secret -n mcp \
  --from-literal=redis-password="$REDIS_PASSWORD"

# Create MCP Gateway config
kubectl create secret generic mcp-gateway-secret -n mcp \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET" \
  --from-literal=BASIC_AUTH_PASSWORD="$BASIC_AUTH_PASSWORD" \
  --from-literal=DATABASE_URL="postgresql+psycopg://mcpgateway:$POSTGRES_PASSWORD@mcp-stack-postgres:5432/mcpgateway" \
  --from-literal=REDIS_URL="redis://:$REDIS_PASSWORD@mcp-stack-redis:6379/0"

# Store passwords securely for later use
echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> ~/mcp-credentials.env
echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> ~/mcp-credentials.env
echo "JWT_SECRET=$JWT_SECRET" >> ~/mcp-credentials.env
echo "BASIC_AUTH_PASSWORD=$BASIC_AUTH_PASSWORD" >> ~/mcp-credentials.env
chmod 600 ~/mcp-credentials.env
```

---

## 7. Deploy via Argo CD

### 7.1. Create and Sync the Application

```bash
# Create the application
argocd app create -f argocd/apps/mcp-stack.yaml

# Sync the application
argocd app sync mcp-stack

# Wait for synchronization
argocd app wait mcp-stack --health
```

### 7.2. Verify Deployment

```bash
# Check all resources in the mcp namespace
kubectl get all -n mcp

# Check pod logs
kubectl logs -n mcp deployment/mcp-stack-mcpcontextforge -f

# Check ingress
kubectl get ingress -n mcp

# Check persistent volumes
kubectl get pv,pvc -n mcp
```

---

## 8. Test and Configure MCP Gateway

### 8.1. Generate API Token

```bash
# Generate JWT token for API access
source ~/mcp-credentials.env
export MCPGATEWAY_BEARER_TOKEN=$(kubectl exec -n mcp deployment/mcp-stack-mcpcontextforge -- \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username admin --exp 0 --secret "$JWT_SECRET")

echo "Bearer token: $MCPGATEWAY_BEARER_TOKEN"
```

### 8.2. Test API Endpoints

```bash
# Get cluster ingress subdomain
INGRESS_SUBDOMAIN=$(ibmcloud ks cluster get --cluster mcp-cluster --output json | jq -r '.ingressHostname')
GATEWAY_URL="https://mcp-gateway.$INGRESS_SUBDOMAIN"

# Test health endpoint
curl -s "$GATEWAY_URL/health"

# Test authenticated endpoints
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     "$GATEWAY_URL/version" | jq

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     "$GATEWAY_URL/tools" | jq

# Open admin UI
echo "Admin UI: $GATEWAY_URL/admin"
echo "Username: admin"
echo "Password: $BASIC_AUTH_PASSWORD"
```

### 8.3. Add MCP Servers

You can add MCP servers through the Admin UI or API:

```bash
# Example: Add a time server via API
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "time_server",
       "url": "http://time-server:8000/sse",
       "description": "Time utilities server"
     }' \
     "$GATEWAY_URL/gateways"

# Create a virtual server with selected tools
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "production_tools",
       "description": "Production tool set",
       "associatedTools": ["1", "2"]
     }' \
     "$GATEWAY_URL/servers"
```

---

## 9. Configure AI Clients

### 9.1. VS Code Copilot Integration

Add this to your VS Code `settings.json`:

```json
{
  "chat.mcp.enabled": true,
  "mcp.servers": {
    "mcp-gateway": {
      "type": "sse",
      "url": "https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/servers/UUID_OF_SERVER_1/sse",
      "headers": {
        "Authorization": "Bearer <MCPGATEWAY_BEARER_TOKEN>"
      }
    }
  }
}
```

### 9.2. Claude Desktop Configuration

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "command": "python",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH": "<MCPGATEWAY_BEARER_TOKEN>",
        "MCP_SERVER_URL": "https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/servers/UUID_OF_SERVER_1/mcp"
      }
    }
  }
}
```

### 9.3. LangChain Agent Integration

```python
from mcpgateway_wrapper import MCPClient

client = MCPClient(
    catalog_urls=["https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/servers/UUID_OF_SERVER_1"],
    token="<MCPGATEWAY_BEARER_TOKEN>",
)

# List available tools
tools = client.tools_list()
print(tools)
```

---

## 10. Upgrade and Database Migration

### 10.1. Rolling Upgrades

Update the image tag in your values file and commit:

```bash
# Update values file
sed -i 's/tag: "0.7.0"/tag: "0.9.0"/' charts/mcp-stack/envs/iks/values.yaml

# Commit and push
git add charts/mcp-stack/envs/iks/values.yaml
git commit -m "Upgrade MCP Gateway to v0.9.0"
git push

# Argo CD will automatically sync the changes
argocd app sync mcp-stack
```

### 10.2. Monitor Migration

```bash
# Watch the rollout
kubectl rollout status deployment/mcp-stack-mcpcontextforge -n mcp

# Check for migration jobs
kubectl get jobs -n mcp

# Follow migration logs if present
kubectl logs -f job/mcp-stack-postgres-migrate -n mcp
```

---

## 11. Operations: Scaling, Backup, Security, Logging, Observability

### 11.1. Horizontal Pod Autoscaling

The HPA is configured automatically. Monitor it:

```bash
kubectl get hpa -n mcp
kubectl describe hpa mcp-stack-mcpcontextforge -n mcp
```

### 11.2. Manual Scaling

```bash
# Scale replicas manually
kubectl scale deployment mcp-stack-mcpcontextforge --replicas=5 -n mcp

# Or update via Helm values
helm upgrade mcp-stack charts/mcp-stack -n mcp \
  --set mcpContextForge.replicaCount=5 \
  -f charts/mcp-stack/envs/iks/values.yaml
```

### 11.3. Database Backup

```bash
# Create a backup using IBM Cloud Snapshots
ibmcloud ks storage snapshot-create --cluster mcp-cluster \
  --pvc $(kubectl get pvc -n mcp -o jsonpath='{.items[0].metadata.name}') \
  --description "MCP Gateway backup $(date +%Y%m%d)"

# List snapshots
ibmcloud ks storage snapshots --cluster mcp-cluster
```

### 11.4. Monitoring and Logs

```bash
# View application logs
kubectl logs -n mcp deployment/mcp-stack-mcpcontextforge -f

# Check resource usage
kubectl top pods -n mcp
kubectl top nodes

# Access IBM Cloud Logs
ibmcloud logs tail -r eu-de
```

## 11.5 Grafana Dashboards

If you collect Prometheus metrics from the gateway and backing services, import standard HTTP and container dashboards or create a custom dashboard for:

- Request rate, error rate, and latency for `/health`, `/version`, and `/rpc`
- Pod CPU/memory and restarts per deployment
- Database connection count, latency, and saturation
- Redis hit ratio and command latency

Store dashboards as code in your Git repo and have Argo CD apply them via ConfigMaps or Grafana's provisioning.

---

## 12. Database Migration: IBM Cloud Databases

### 12.1. Provision IBM Cloud Databases for PostgreSQL

```bash
# Create managed PostgreSQL instance
ibmcloud resource service-instance-create mcp-postgres \
    databases-for-postgresql standard eu-de \
    -p '{"members_memory_allocation_mb": 4096, "members_disk_allocation_mb": 10240}'

# Create service credentials
ibmcloud resource service-key-create mcp-postgres-creds Administrator \
    --instance-name mcp-postgres

# Get connection details
ibmcloud resource service-key mcp-postgres-creds --output json
```

### 12.2. Database Migration Process

```bash
# 1. Create backup of current database
kubectl exec -n mcp deployment/mcp-stack-postgres -- \
  pg_dump -U mcpgateway mcpgateway > /tmp/mcp-backup.sql

# 2. Get managed database connection string
CREDS=$(ibmcloud resource service-key mcp-postgres-creds --output json)
HOST=$(echo "$CREDS" | jq -r '.[0].credentials.connection.postgres.hosts[0].hostname')
PORT=$(echo "$CREDS" | jq -r '.[0].credentials.connection.postgres.hosts[0].port')
USER=$(echo "$CREDS" | jq -r '.[0].credentials.connection.postgres.authentication.username')
PASS=$(echo "$CREDS" | jq -r '.[0].credentials.connection.postgres.authentication.password')
DATABASE=$(echo "$CREDS" | jq -r '.[0].credentials.connection.postgres.database')

MANAGED_DB_URL="postgresql+psycopg://${USER}:${PASS}@${HOST}:${PORT}/${DATABASE}?sslmode=require"

# 3. Update database URL secret
kubectl patch secret mcp-gateway-secret -n mcp \
  --patch="{\"data\":{\"DATABASE_URL\":\"$(echo -n "$MANAGED_DB_URL" | base64 -w 0)\"}}"

# 4. Update PostgreSQL settings in values
cat >> charts/mcp-stack/envs/iks/values.yaml << EOF

# Disable embedded PostgreSQL
postgres:
  enabled: false

# Use external database
mcpContextForge:
  env:

    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: mcp-gateway-secret
          key: DATABASE_URL
EOF

# 5. Commit and deploy
git add charts/mcp-stack/envs/iks/values.yaml
git commit -m "Migrate to IBM Cloud Databases for PostgreSQL"
git push

# 6. Sync the application
argocd app sync mcp-stack
```

### 12.3. Setup IBM Cloud Databases for Redis

```bash
# Create managed Redis instance
ibmcloud resource service-instance-create mcp-redis \
    databases-for-redis standard eu-de \
    -p '{"members_memory_allocation_mb": 1024}'

# Create service credentials
ibmcloud resource service-key-create mcp-redis-creds Administrator \
    --instance-name mcp-redis

# Get Redis connection details
REDIS_CREDS=$(ibmcloud resource service-key mcp-redis-creds --output json)
REDIS_HOST=$(echo "$REDIS_CREDS" | jq -r '.[0].credentials.connection.rediss.hosts[0].hostname')
REDIS_PORT=$(echo "$REDIS_CREDS" | jq -r '.[0].credentials.connection.rediss.hosts[0].port')
REDIS_PASS=$(echo "$REDIS_CREDS" | jq -r '.[0].credentials.connection.rediss.authentication.password')

MANAGED_REDIS_URL="rediss://:${REDIS_PASS}@${REDIS_HOST}:${REDIS_PORT}/0"

# Update Redis URL secret
kubectl patch secret mcp-gateway-secret -n mcp \
  --patch="{\"data\":{\"REDIS_URL\":\"$(echo -n "$MANAGED_REDIS_URL" | base64 -w 0)\"}}"

# Update values to disable embedded Redis
cat >> charts/mcp-stack/envs/iks/values.yaml << EOF

# Disable embedded Redis
redis:
  enabled: false
EOF
```

---

## 13. Troubleshooting

### 13.1. Common Issues

!!! tip "Pod ImagePullBackOff"

    * Verify image name and tag in values.yaml
    * Check that worker nodes can reach ICR:
      ```bash
      kubectl describe pod <pod-name> -n mcp
      ```
    * Ensure image exists in registry:
      ```bash
      ibmcloud cr images --restrict mcp-gw
      ```

!!! tip "Ingress 404/502 Errors"

    * Verify ingress subdomain matches cluster:
      ```bash
      ibmcloud ks cluster get --cluster mcp-cluster | grep "Ingress"
      ```
    * Check ingress controller status:
      ```bash
      kubectl get pods -n kube-system | grep nginx
      ```

!!! tip "Argo CD Sync Failed"

    * Check application status:
      ```bash
      argocd app get mcp-stack
      ```
    * View detailed sync errors:
      ```bash
      kubectl describe application mcp-stack -n argocd
      ```

### 13.2. Resource Debugging

```bash
# Check cluster capacity
kubectl describe nodes

# View resource usage
kubectl top pods -n mcp
kubectl top nodes

# Check events
kubectl get events -n mcp --sort-by='.lastTimestamp'

# Debug pod issues
kubectl describe pod <pod-name> -n mcp
kubectl logs <pod-name> -n mcp --previous
```

### 13.3. Network Troubleshooting

```bash
# Test internal DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup mcp-stack-postgres.mcp.svc.cluster.local

# Test external connectivity
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -O- https://google.com

# Check network policies
kubectl get networkpolicy -n mcp
kubectl describe networkpolicy deny-by-default -n mcp
```

---

## 14. Performance Testing

Performance testing helps validate the stability, scalability, and responsiveness of the MCP Gateway under different workloads. This section outlines how to perform load tests using `hey` and how to inspect performance metrics.

---

### 14.1. Run Basic Load Test with `hey`

[`hey`](https://github.com/rakyll/hey) is a CLI load-testing tool for HTTP endpoints. You can use it to simulate traffic to the MCP Gateway's `/health` or `/version` endpoint:

```bash
# Install hey (if not already installed)
brew install hey  # on macOS
go install github.com/rakyll/hey@latest  # if using Go

# Run a basic test against the public health endpoint
hey -z 30s -c 10 https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/health
```

Options explained:

* `-z 30s`: Duration of test
* `-c 10`: Number of concurrent connections

For authenticated endpoints:

```bash
# Replace with your actual token
export TOKEN="<MCPGATEWAY_BEARER_TOKEN>"

# Target authenticated endpoint
hey -z 30s -c 10 \
  -H "Authorization: Bearer $TOKEN" \
  https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/version
```

---

### 14.2. Analyze Gateway Performance

Check metrics through Kubernetes and the API:

```bash
# Observe resource usage
kubectl top pods -n mcp
kubectl top nodes

# Inspect autoscaler activity
kubectl get hpa -n mcp
kubectl describe hpa mcp-stack-mcpcontextforge -n mcp
```

---

### 14.3. Inspect Tool-Level Metrics

Each tool invocation is tracked with:

* Response time (min/max/avg)
* Success/failure rate
* Total executions

Fetch aggregated metrics from the API:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/metrics | jq
```

You can also inspect per-tool or per-server metrics via the Admin UI at:

```
https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/admin
```

---

### 14.4. Advanced: Stress Test Specific Tool

```bash
# Invoke a specific tool multiple times in parallel
for i in {1..50}; do
  curl -s -H "Authorization: Bearer $TOKEN" \
       -X POST \
       -H "Content-Type: application/json" \
       -d '{"name":"clock_tool","arguments":{"timezone":"UTC"}}' \
       https://mcp-gateway.<CLUSTER_INGRESS_SUBDOMAIN>/rpc &
done
wait
```

---

## 15. Configuring the Kubernetes MCP Server


Run the Kubernetes MCP Server and add it to the gateway:

```
python3 -m mcpgateway.translate --stdio "npx -y kubernetes-mcp-server@latest" --expose-sse --port 8103
```


## 16. FAQ

**Q**: *How do I rotate the JWT secret without downtime?*
**A**: Update the secret and restart the MCP Gateway pods:
```bash
NEW_JWT_SECRET=$(openssl rand -hex 32)
kubectl patch secret mcp-gateway-secret -n mcp \
  --patch="{\"data\":{\"JWT_SECRET_KEY\":\"$(echo -n "$NEW_JWT_SECRET" | base64 -w 0)\"}}"
kubectl rollout restart deployment/mcp-stack-mcpcontextforge -n mcp
```

**Q**: *Can I use custom storage classes?*
**A**: Yes, update the storageClass in your values.yaml:
```yaml
postgres:
  primary:
    persistence:
      storageClass: "your-custom-storage-class"
```

**Q**: *How do I enable TLS termination at the ingress?*
**A**: Install cert-manager and configure Let's Encrypt:
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

**Q**: *How do I backup the entire application?*
**A**: Use Velero for full cluster backups or create database dumps and store them in IBM Cloud Object Storage.

---

✅ You now have a production-ready MCP Gateway stack on IBM Cloud Kubernetes Service with GitOps management, managed databases, and comprehensive observability!

## Next Steps

1. **Set up monitoring**: Deploy Prometheus and Grafana for detailed metrics
2. **Configure alerts**: Set up IBM Cloud Monitoring alerts for critical metrics
3. **Implement CI/CD**: Automate image builds and deployments with IBM Cloud Toolchain
4. **Scale across regions**: Deploy additional clusters for global availability
5. **Security hardening**: Implement pod security standards and network policies
