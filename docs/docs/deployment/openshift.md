# ✨ Red Hat OpenShift

OpenShift (both **OKD** and **Red Hat OpenShift Container Platform**) adds opinionated security (SCC), integrated routing, and optional build pipelines on top of Kubernetes.  Deploying MCP Gateway therefore means (1) building or pulling a compatible image, (2) wiring database + cache back-ends, (3) obeying the default *restricted-v2* SCC, and (4) exposing the service through a **Route** instead of an Ingress.  This guide walks through each step, offers ready-made YAML snippets, and explains the differences from the vanilla Kubernetes.

---

## 📋 Prerequisites

* `oc` CLI - log in as a developer to a project/namespace you can create objects in.
* A storage class for PVCs (or local PVs) to back the Postgres template.
* Either **Podman** or **Docker** on your workstation **if you build locally**.
* Access to an image registry that your cluster can pull from (e.g. `quay.io`).

---

## 🛠️ Build & push images

### Option A - Use Make

| Target             | Builds                  | Dockerfile             | Notes                    |
| ------------------ | ----------------------- | ---------------------- | ------------------------ |
| `make podman`      | `mcpgateway-dev:latest` | **Containerfile**      | Rootless Podman build    |
| `make podman-prod` | `mcpgateway:latest`     | **Containerfile.lite** | UBI 9-micro, multi-stage |
| `make docker`      | `mcpgateway-dev:latest` | **Containerfile**      | Docker Desktop           |
| `make docker-prod` | `mcpgateway:latest`     | **Containerfile.lite** | Same slim image          |

Push afterwards, for example:

```bash
podman tag mcpgateway:latest quay.io/YOUR_NS/mcpgateway:latest
podman push quay.io/YOUR_NS/mcpgateway:latest
```

> **Apple-silicon note** - `Containerfile.lite` uses `ubi9-micro` (x86\_64). Buildx/QEMU works, but the image will run under emulation on macOS. If you need native arm64 choose the dev image or add `--platform linux/arm64`.

### Option B - Raw CLI equivalents

```bash
# Dev (Containerfile)
podman build -t mcpgateway-dev:latest -f Containerfile .

# Prod (UBI micro, AMD64, squashed layers)
docker build --platform=linux/amd64 --squash \
  -t mcpgateway:latest -f Containerfile.lite .
```

---

## 🔑 Secrets & ConfigMaps

Create a ConfigMap from your `.env` file:

```bash
oc create configmap mcpgateway-env --from-env-file=.env   # Populates envFrom
```

OpenShift lets you inject **all keys** via `envFrom:` in the pod template.

If you keep sensitive values (e.g. `JWT_SECRET_KEY`) separate, store them in a Secret and reference both resources under `envFrom:`.

---

## 🗄 PostgreSQL & Redis back-ends

### PostgreSQL (persistent template)

```bash
oc new-app -f https://raw.githubusercontent.com/openshift/origin/master/examples/db-templates/postgresql-persistent-template.json \
  -p POSTGRESQL_USER=postgres,POSTGRESQL_PASSWORD=secret,POSTGRESQL_DATABASE=mcp
```

The template creates a DeploymentConfig, Service and a 1 Gi PVC bound to the cluster's default storage class.

### Redis

On OpenShift 4.x use the **Redis Enterprise Operator** from OperatorHub (UI or CLI) then create a RedisEnterpriseCluster CR; it provisions StatefulSets plus PVCs out-of-the-box.

---

## 📦 Deployment & Service (gateway)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcpgateway
  template:
    metadata:
      labels:
        app: mcpgateway
    spec:
      securityContext:            # Must satisfy restricted-v2 SCC
        runAsNonRoot: true
      containers:

      - name: gateway
        image: quay.io/YOUR_NS/mcpgateway:latest
        ports:

        - containerPort: 4444
        envFrom:

        - configMapRef:
            name: mcpgateway-env
        readinessProbe:
          httpGet:
            path: /health
            port: 4444
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health
            port: 4444
          initialDelaySeconds: 15
          periodSeconds: 20
        securityContext:
          allowPrivilegeEscalation: false
          runAsUser: 1001        # UBI non-root UID works with restricted SCC
---
apiVersion: v1
kind: Service
metadata:
  name: mcpgateway
spec:
  selector:
    app: mcpgateway
  ports:

  - port: 80
    targetPort: 4444
```

*The readiness/liveness probes follow OpenShift's health-check guidance*.

---

## 🌍 Route (public URL)

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: mcpgateway
spec:
  to:
    kind: Service
    name: mcpgateway
  port:
    targetPort: 80
  tls:
    termination: edge
```

Routes are OpenShift's native form of ingress; the router automatically provisions a hostname such as `mcpgateway-myproj.apps.cluster.example.com`.

---

## 📑 Putting it together

```bash
# Apply manifests
oc apply -f postgres-template.yaml        # or Operator YAML
oc apply -f redis-operator.yaml           # if using Redis Operator
oc apply -f mcpgateway-deployment.yaml
oc apply -f mcpgateway-route.yaml
```

Verify:

```bash
oc get pods
oc get route mcpgateway -o jsonpath='{.spec.host}{"\n"}'
curl https://$(oc get route mcpgateway -o jsonpath='{.spec.host}')/health
```

---

## 🔄 OpenShift BuildConfig (optional)

If you prefer in-cluster builds, create a `BuildConfig` with the *docker* strategy. You can override the Dockerfile path via `spec.strategy.dockerStrategy.dockerfilePath`. Then trigger:

```bash
oc start-build mcpgateway --from-dir=.
```

The resulting image lands in an internal **ImageStream**, and the Deployment can auto-deploy the new tag.

---

## 🗃 Persistence & PVCs

The Postgres template already generates a PVC; you can create extra PVCs manually or via the web console. A general PVC manifest is shown in OpenShift Storage docs.

---

## 🚦 Non-Make cheat-sheet

| Action                  | Command                                                   |
| ----------------------- | --------------------------------------------------------- |
| Build dev image (local) | `podman build -t mcpgateway-dev -f Containerfile .`       |
| Build prod (UBI lite)   | `docker build -t mcpgateway -f Containerfile.lite .`      |
| Push to Quay            | `podman push mcpgateway quay.io/NS/mcpgateway`            |
| Create project          | `oc new-project mcp-demo`                                 |
| Load .env               | `oc create configmap mcpgateway-env --from-env-file=.env` |
| Deploy                  | `oc apply -f mcpgateway-deployment.yaml`                  |
| Expose                  | `oc apply -f mcpgateway-route.yaml`                       |
| Tail logs               | `oc logs -f deployment/mcpgateway`                        |

---

## 🛠 Troubleshooting

| Issue                                                              | Fix                                                                        |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `Error: container has runAsNonRoot and image has non-numeric user` | Add `runAsUser: 1001` or pick `nonroot-v2` SCC.                            |
| PVC stuck in `Pending`                                             | Check storage class or request size > quota.                               |
| Route returns 503                                                  | Verify pod readiness probe passes and the Service targets port 80 -> 4444. |

---

## 📚 Further reading

1. [OpenShift Route documentation - creation & TLS](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/networking/configuring-routes)
2. [SCC and **restricted-v2 / nonroot-v2** behaviour](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/authentication_and_authorization/managing-pod-security-policies)
3. [ConfigMap envFrom patterns](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/building_applications/config-maps)
4. [Postgres persistent template example](https://github.com/sclorg/postgresql-container/blob/master/examples/postgresql-persistent-template.json)
5. [Redis Enterprise Operator on OCP (OperatorHub)](https://redis.io/docs/latest/operate/kubernetes/deployment/openshift/openshift-operatorhub/)
6. [Health-check probes in OpenShift](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/building_applications/application-health)
7. [BuildConfig Docker strategy & `dockerfilePath`](https://docs.okd.io/4.18/cicd/builds/build-strategies.html#builds-strategy-dockerfilepath_build-strategies)
