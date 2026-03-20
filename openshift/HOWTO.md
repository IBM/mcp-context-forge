# OpenShift Operator HOWTO

Deploy and operate ContextForge on OpenShift using the ContextForge operator,
Crunchy PGO for PostgreSQL, and the OpsTree Redis operator.

## Prerequisites

- OpenShift 4.x cluster with `oc` CLI authenticated as `cluster-admin`
- Two namespaces: `contextforge-dev` (builds) and `contextforge-run` (runtime)
- Docker Hub pull secret (to avoid rate limits on upstream images)

### Namespace setup

```bash
oc new-project contextforge-dev
oc new-project contextforge-run
```

### Docker Hub pull secret

Create in `contextforge-dev`, then copy to any namespace that pulls from Docker Hub:

```bash
oc create secret docker-registry dockerhub-pull-secret \
  -n contextforge-dev \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=YOUR_USER \
  --docker-password=YOUR_TOKEN

# Copy to runtime namespace and link to default SA
oc get secret dockerhub-pull-secret -n contextforge-dev -o json \
  | jq 'del(.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.namespace)' \
  | oc apply -n contextforge-run -f -
oc secrets link default dockerhub-pull-secret --for=pull -n contextforge-run
```

### SCC grants

The default service account in the runtime namespace needs `anyuid` for the
upstream Postgres image (which runs an init process as root):

```bash
oc adm policy add-scc-to-user anyuid -z default -n contextforge-run
```

Crunchy PGO creates per-cluster service accounts that also need `anyuid`.
These are created automatically when you apply the PostgresCluster CR — grant
them after the SA appears:

```bash
oc adm policy add-scc-to-user anyuid \
  -z contextforge-perf-postgres-instance \
  -z contextforge-perf-postgres-repohost \
  -z contextforge-perf-postgres-pgbackrest \
  -n contextforge-run
```

## Install operators

### Crunchy PGO (PostgreSQL)

Install from OperatorHub (Red Hat Operators catalog, `stable-v5` channel).
It installs cluster-wide.

### OpsTree Redis Operator

Install from OperatorHub (Community Operators catalog). After installation,
the operator SA may be missing RBAC for some CRDs. If the operator pod
crash-loops with "cannot list resource" errors, apply:

```bash
cat <<'EOF' | oc apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: redis-operator-missing-perms
rules:
  - apiGroups: ["redis.redis.opstreelabs.in"]
    resources: ["redisreplications", "redissentinels",
                "redisreplications/status", "redissentinels/status",
                "redisreplications/finalizers", "redissentinels/finalizers"]
    verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: redis-operator-missing-perms
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: redis-operator-missing-perms
subjects:
  - kind: ServiceAccount
    name: redis-operator
    namespace: openshift-operators
EOF
```

**Important:** Use the OpsTree-provided Redis image (`quay.io/opstree/redis:v7.0.12`),
not the upstream `redis:7.0` — the operator's health check expects a script only
present in their image.

## Build the images

### Build pipelines (contextforge-dev)

The build pipelines are defined in `openshift/builds/build-pipelines.yaml`.
Process and apply the template:

```bash
cd openshift/builds
oc process -f build-pipelines.yaml -p GIT_REF=main | oc apply -n contextforge-dev -f -
```

Trigger all builds:

```bash
for bc in contextforge nginx-cache contextforge-operator; do
  oc start-build "$bc" -n contextforge-dev --follow &
done
wait
```

### Build the wxo-plugins image

The plugins image uses a binary build — upload local files directly:

```bash
TMPDIR=$(mktemp -d)
cp -a /path/to/wxo-plugins/* "$TMPDIR/"
cp openshift/builds/Dockerfile.wxo-plugins "$TMPDIR/Dockerfile"
find "$TMPDIR" \( -name '__pycache__' -o -name '.pytest_cache' \) -type d -exec rm -rf {} +

oc start-build wxo-plugins -n contextforge-dev --from-dir="$TMPDIR" --follow
rm -rf "$TMPDIR"
```

To update plugins, repeat the above. The gateway pods pick up the new image
on their next restart.

## Provision PostgreSQL and Redis

### Storage

Crunchy PGO requires persistent volumes. On bare-metal clusters without a CSI
driver, create hostPath PVs with proper SELinux labels:

```bash
# On each worker node that will host the PV:
oc debug node/workerN.example.com -- chroot /host bash -c '
  mkdir -p /var/data/crunchy-pgdata /var/data/crunchy-repo
  chcon -Rt svirt_sandbox_file_t /var/data/crunchy-pgdata /var/data/crunchy-repo
  chmod 777 /var/data/crunchy-pgdata /var/data/crunchy-repo'
```

Then create the PVs with node affinity pinned to that worker:

```bash
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: crunchy-pgdata-pv
spec:
  capacity:
    storage: 5Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /var/data/crunchy-pgdata
    type: Directory
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: [workerN.example.com]
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: crunchy-repo-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /var/data/crunchy-repo
    type: Directory
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: [workerN.example.com]
EOF
```

If your cluster has a StorageClass (ODF, etc.), skip the above — just set
`storageClassName` in the CRs below.

### PostgresCluster CR

```bash
cat <<'EOF' | oc apply -n contextforge-run -f -
apiVersion: postgres-operator.crunchydata.com/v1beta1
kind: PostgresCluster
metadata:
  name: contextforge-perf-postgres
spec:
  openshift: true
  postgresVersion: 16
  instances:
    - name: instance1
      replicas: 1
      dataVolumeClaimSpec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 5Gi
  backups:
    pgbackrest:
      repos:
        - name: repo1
          volume:
            volumeClaimSpec:
              accessModes: [ReadWriteOnce]
              resources:
                requests:
                  storage: 1Gi
  users:
    - name: contextforge
      databases:
        - contextforge
EOF
```

After the cluster is running, grant superuser to the application user
(required for Alembic migrations):

```bash
PG_POD=$(oc get pods -n contextforge-run \
  -l postgres-operator.crunchydata.com/role=master -o name | head -1)
oc exec $PG_POD -n contextforge-run -c database -- \
  psql -U postgres -d contextforge -c "ALTER USER contextforge WITH SUPERUSER;"
```

### Redis CR

```bash
cat <<'EOF' | oc apply -n contextforge-run -f -
apiVersion: redis.redis.opstreelabs.in/v1beta2
kind: Redis
metadata:
  name: contextforge-perf-redis
spec:
  kubernetesConfig:
    image: quay.io/opstree/redis:v7.0.12
    imagePullPolicy: IfNotPresent
  redisExporter:
    enabled: false
    image: quay.io/opstree/redis-exporter:v1.44.0
EOF
```

## Deploy ContextForge

### Connection secrets

Create secrets pointing to the operator-provisioned databases. The
ContextForge operator reads these via `database.external.secretRef` and
`redis.external.secretRef`.

```bash
# PostgreSQL — rewrite the Crunchy URI to use the psycopg driver
PG_URI=$(oc get secret contextforge-perf-postgres-pguser-contextforge \
  -n contextforge-run -o jsonpath='{.data.uri}' | base64 -d \
  | sed 's|^postgresql://|postgresql+psycopg://|')

oc create secret generic contextforge-db-credentials \
  -n contextforge-run --from-literal=url="$PG_URI"

# Redis
oc create secret generic contextforge-redis-credentials \
  -n contextforge-run \
  --from-literal=url="redis://contextforge-perf-redis.contextforge-run.svc:6379/0"
```

### Apply the CRD

```bash
oc apply -f openshift/operator/config/crd/bases/contextforge.io_contextforges.yaml
```

### Deploy the operator

```bash
# Assumes the operator image was built via the build pipeline above.
# The operator deployment YAML is in openshift/operator/config/manager/.
# Restart to pick up a new image:
oc rollout restart deployment/contextforge-operator -n contextforge-run
```

### ContextForge CR

```bash
cat <<'EOF' | oc apply -n contextforge-run -f -
apiVersion: contextforge.io/v1alpha1
kind: ContextForge
metadata:
  name: contextforge-perf
spec:
  gateway:
    image: image-registry.openshift-image-registry.svc:5000/contextforge-dev/contextforge:latest
    replicas: 1
    httpServer: gunicorn
    workers: 9
    sessionPoolEnabled: false
    streamableHTTPMaxEventsPerStream: 200
    httpxMaxConnections: 1000
    httpxMaxKeepaliveConnections: 500
    resources:
      requests:
        cpu: "2"
        memory: "2Gi"
      limits:
        cpu: "4"
        memory: "4Gi"
    route:
      enabled: true
      tlsTermination: edge
  database:
    external:
      secretRef:
        name: contextforge-db-credentials
  redis:
    external:
      secretRef:
        name: contextforge-redis-credentials
  nginx:
    enabled: true
    image: image-registry.openshift-image-registry.svc:5000/contextforge-dev/nginx-cache:latest
  auth:
    adminEmail: admin@example.com
  features:
    ui: true
    adminApi: true
    a2a: true
    plugins:
      enabled: true
      canOverrideAuthHeaders: true
      image: image-registry.openshift-image-registry.svc:5000/contextforge-dev/wxo-plugins:latest
    catalog: true
    rustRuntime:
      mode: "off"
EOF
```

### Add the route to ALLOWED_ORIGINS

After the route is created, patch the gateway ConfigMap so CSRF origin
validation passes for browser sessions:

```bash
ROUTE_HOST=$(oc get route contextforge-perf-gateway -n contextforge-run -o jsonpath='{.spec.host}')
oc patch configmap contextforge-perf-gateway-config -n contextforge-run \
  -p "{\"data\":{\"ALLOWED_ORIGINS\":\"https://$ROUTE_HOST\"}}"
# Restart gateway to pick up the change
oc delete pods -n contextforge-run -l app.kubernetes.io/component=gateway --force
```

### Verify

```bash
oc get contextforges -n contextforge-run
# Phase should be "Running" with Gateway/Database/Redis all "true"

ROUTE_HOST=$(oc get route contextforge-perf-gateway -n contextforge-run -o jsonpath='{.spec.host}')
curl -sk "https://$ROUTE_HOST/health"
# {"status":"healthy",...}
```

## Day-2 operations

### Reset the database

Equivalent to `make testing-down docker-clean testing-up` for the cluster:

```bash
make ocp-db-reset
# Or: make ocp-db-reset OC_CF_NS=contextforge-run
```

### Update plugins

Re-run the binary build with updated local files:

```bash
TMPDIR=$(mktemp -d)
cp -a /path/to/wxo-plugins/* "$TMPDIR/"
cp openshift/builds/Dockerfile.wxo-plugins "$TMPDIR/Dockerfile"
find "$TMPDIR" \( -name '__pycache__' -o -name '.pytest_cache' \) -type d -exec rm -rf {} +
oc start-build wxo-plugins -n contextforge-dev --from-dir="$TMPDIR" --follow
rm -rf "$TMPDIR"

# Restart gateway to pick up new image
oc delete pods -n contextforge-run -l app.kubernetes.io/component=gateway --force
```

### Rebuild the operator

After code changes to `openshift/operator/`:

```bash
git push origin jps-build-and-operator
oc start-build contextforge-operator -n contextforge-dev --follow
oc rollout restart deployment/contextforge-operator -n contextforge-run
```

### Rebuild the gateway

After code changes to the main ContextForge application:

```bash
oc start-build contextforge -n contextforge-dev --follow
oc delete pods -n contextforge-run -l app.kubernetes.io/component=gateway --force
```

### Run Playwright UI tests against the cluster

```bash
# Get the cluster's JWT secret for test auth
export JWT_SECRET_KEY=$(oc get secret contextforge-perf-jwt-secret \
  -n contextforge-run -o jsonpath='{.data.secret}' | base64 -d)
export TEST_BASE_URL=https://$(oc get route contextforge-perf-gateway \
  -n contextforge-run -o jsonpath='{.spec.host}')

# Run smoke tests
make test-ui-smoke

# Run a single test
make test-ui FILE=tests/playwright/test_admin_ui.py::TestAdminUI::test_admin_panel_loads

# Without JWT (form login, requires fresh DB or known password)
PLAYWRIGHT_DISABLE_JWT_FALLBACK=1 make test-ui-headless
```

### View operator logs

```bash
oc logs deployment/contextforge-operator -n contextforge-run -f
```

### Check gateway logs

```bash
oc logs deployment/contextforge-perf-gateway -n contextforge-run -c gateway -f
```
