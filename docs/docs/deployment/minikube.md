# ⚡️ Minikube

1. **Install Minikube and kubectl** (Docker or Podman driver required).
2. Start a local cluster with Ingress and DNS addons.
3. Load the `ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1` image into Minikube.
4. Apply your Kubernetes manifests.
5. Access the Gateway at [http://gateway.local](http://gateway.local) or `127.0.0.1:80` via NGINX Ingress.

Minikube provides a self-contained environment, enabling you to replicate production features like persistent volumes and TLS on your local machine.

---

## 📋 Prerequisites

| Requirement          | Notes                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------- |
| **CPU / RAM**        | Minimum **2 vCPU + 2 GiB**; recommended 4 vCPU / 6 GiB for smoother operation.                             |
| **Disk**             | At least 20 GiB of free space.                                                                             |
| **Container driver** | Docker 20.10+ or Podman 4.7+; Docker is the simplest choice on macOS and Windows.                          |
| **kubectl**          | Automatically configured by `minikube start`; alternatively, use `minikube kubectl -- ...` if not installed. |

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

## 🚀 Step 1 - Install Minikube and kubectl

> **Make target**

```bash
make minikube-install
```

This target checks for existing installations of `minikube` and `kubectl`. If missing, it installs them using:

* **Homebrew** on macOS
* The official binary on Linux
* **Chocolatey** on Windows

<details>
<summary>Manual installation (optional)</summary>

### macOS (Homebrew)

```bash
brew install minikube kubernetes-cli
```

### Linux (Generic binary)

```bash
# Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64

# kubectl (latest stable)
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
```

### Windows (PowerShell + Chocolatey)

```powershell
choco install -y minikube kubernetes-cli
```

</details>

---

## ⚙️ Step 2 - Start the cluster

> **Make target**

```bash
make minikube-start
```

<details>
<summary>Equivalent manual command</summary>

```bash
minikube start \
  --driver=docker \
  --cpus=4 --memory=6g \
  --addons=ingress,ingress-dns \
  --profile=mcpgw
```

</details>

* `--driver=docker` avoids nested virtualization on macOS and Windows Home.
* `ingress` provides an NGINX LoadBalancer on localhost.
* `ingress-dns` resolves `*.local` domains when you add the Minikube IP to your OS DNS list.
* `--cpus` and `--memory` can be set to `max` to utilize all available resources.

**Check cluster status:**

```bash
make minikube-status
# or:
minikube status -p mcpgw
kubectl get pods -n ingress-nginx
```

---

## 🏗 Step 3 - Load the Gateway image

> **Make target**

```bash
make minikube-image-load
```

This target builds the `ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1` image and loads it into Minikube.

### Alternative methods

* **Pre-cache a remote image:**

  ```bash
  minikube cache add ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1
  minikube cache reload
  ```

* **Load a local tarball:**

  ```bash
  docker save ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1 | minikube image load -
  ```

---

## 📄 Step 4 - Apply Kubernetes manifests

> **Make target**

```bash
make minikube-k8s-apply
```

This applies the Kubernetes manifests. Alternative manual step:

```bash
# PostgreSQL
kubectl apply -f deployment/k8s/postgres-config.yaml
kubectl apply -f deployment/k8s/postgres-pv.yaml
kubectl apply -f deployment/k8s/postgres-pvc.yaml
kubectl apply -f deployment/k8s/postgres-deployment.yaml
kubectl apply -f deployment/k8s/postgres-service.yaml

# Redis
kubectl apply -f deployment/k8s/redis-deployment.yaml
kubectl apply -f deployment/k8s/redis-service.yaml

# MCP Gateway
kubectl apply -f deployment/k8s/mcp-context-forge-deployment.yaml
kubectl apply -f deployment/k8s/mcp-context-forge-service.yaml
kubectl apply -f deployment/k8s/mcp-context-forge-ingress.yaml
```

If you've enabled `ingress-dns`, set the Ingress `host:` to `gateway.local`. Otherwise, omit the `host:` and access via NodePort.

**Note:** Minikube automatically configures the `kubectl` context upon cluster creation. If not, set it manually:

```bash
kubectl config use-context minikube
# or:
minikube kubectl -- apply -f ...
```

---

## 🧪 Step 5 - Verify deployment status

Before hitting your endpoint, confirm the application is up and healthy.

### 🔍 Check pod status

```bash
kubectl get pods
```

Expect output like:

```
NAME                                      READY   STATUS    RESTARTS   AGE
postgres-5b66bdf445-rp8kl                 1/1     Running   0          15s
redis-668976c4f9-2hljd                    1/1     Running   0          15s
mcp-context-forge-6d87f8c5d8-nnmgx        1/1     Running   0          10s
```

---

### 📜 Check logs (optional)

```bash
kubectl logs deploy/mcp-context-forge
```

This can help diagnose startup errors or missing dependencies (e.g. bad env vars, Postgres connection issues).

---

### 🚥 Wait for rollout (optional)

```bash
kubectl rollout status deploy/mcp-context-forge
```

If the pod gets stuck in `CrashLoopBackOff`, run:

```bash
kubectl describe pod <pod-name>
```

And:

```bash
kubectl logs <pod-name>
```

---

### ✅ Confirm Ingress is live

```bash
kubectl get ingress
```

Should show something like:

```
NAME                        CLASS    HOSTS           ADDRESS        PORTS   AGE
mcp-context-forge-ingress   nginx    gateway.local   192.168.49.2   80      1m
```

If `ADDRESS` is empty, the ingress controller may still be warming up.

You may want to add this to `/etc/hosts`. Ex:

```
192.168.49.2 gateway.local
```

---

## 🌐 Step 6 - Test access

```bash
# Via NodePort:
curl $(minikube service mcp-context-forge --url)/health

# Via DNS:
curl http://gateway.local/health
```

---

## 🧹 Cleaning up

| Action              | Make target            | Manual command                                               |
| ------------------- | ---------------------- | ------------------------------------------------------------ |
| Pause cluster       | `make minikube-stop`   | `minikube stop -p mcpgw`                                     |
| Delete cluster      | `make minikube-delete` | `minikube delete -p mcpgw`                                   |
| Remove cached image | -                      | `minikube cache delete ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1` |

---

## 🛠 Non-Make cheatsheet

| Task                     | Command                                               |
| ------------------------ | ----------------------------------------------------- |
| Start with Podman driver | `minikube start --driver=podman --network-plugin=cni` |
| Open dashboard           | `minikube dashboard`                                  |
| SSH into node            | `minikube ssh`                                        |
| Enable metrics-server    | `minikube addons enable metrics-server`               |
| Upgrade Minikube (macOS) | `minikube delete && brew upgrade minikube`            |

---

## 📚 Further reading

1. Minikube **Quick Start** guide (official)
   [https://minikube.sigs.k8s.io/docs/start/](https://minikube.sigs.k8s.io/docs/start/)

2. Minikube **Docker driver** docs
   [https://minikube.sigs.k8s.io/docs/drivers/docker/](https://minikube.sigs.k8s.io/docs/drivers/docker/)

3. Enable NGINX Ingress in Minikube
   [https://kubernetes.io/docs/tasks/access-application-cluster/ingress-minikube/](https://kubernetes.io/docs/tasks/access-application-cluster/ingress-minikube/)

4. Load / cache images inside Minikube
   [https://minikube.sigs.k8s.io/docs/handbook/pushing/](https://minikube.sigs.k8s.io/docs/handbook/pushing/)

5. Using Minikube's built-in kubectl
   [https://minikube.sigs.k8s.io/docs/handbook/kubectl/](https://minikube.sigs.k8s.io/docs/handbook/kubectl/)

6. Allocate max CPU/RAM flags
   [https://minikube.sigs.k8s.io/docs/faq/#how-can-i-allocate-maximum-resources-to-minikube](https://minikube.sigs.k8s.io/docs/faq/#how-can-i-allocate-maximum-resources-to-minikube)

7. Ingress-DNS addon overview
   [https://minikube.sigs.k8s.io/docs/handbook/addons/ingress-dns/](https://minikube.sigs.k8s.io/docs/handbook/addons/ingress-dns/)

8. Stack Overflow: loading local images into Minikube
   [https://stackoverflow.com/questions/42564058/how-can-i-use-local-docker-images-with-minikube](https://stackoverflow.com/questions/42564058/how-can-i-use-local-docker-images-with-minikube)

---

Minikube gives you the fastest, vendor-neutral sandbox for experimenting with MCP Gateway-and everything above doubles as CI instructions for self-hosted GitHub runners or ephemeral integration tests.
