# ⚡️ Minikube

1. Install Minikube and a container driver (Docker or Podman).
2. Start a local cluster with enough CPU/RAM and the **Ingress** addon enabled.
3. Load or build the `mcpgateway` image into the cluster.
4. Apply the same Kubernetes manifests you use in other environments.
5. Access the Gateway at [http://gateway.local](http://gateway.local) (or `127.0.0.1:80`) via NGINX Ingress.

Minikube is self-contained: one command spins up the control-plane, container runtime, CNI, and a registry‐mirroring image loader. You can therefore replicate almost any production feature—including persistent volumes and TLS—entirely on your laptop.

---

## 📋 Prerequisites

| Requirement          | Notes                                                                                                    |
| -------------------- | -------------------------------------------------------------------------------------------------------- |
| **CPU/RAM**          | Minikube recommends **2 CPUs + 2 GiB** at minimum. For smooth builds: 4 CPUs / 6 GiB.                    |
| **Disk**             | ≥20 GiB free space.                                                                                      |
| **Container driver** | Docker 20.10+ or Podman 4.7+; Docker driver is simplest on macOS/Windows.                                |
| **kubectl**          | Automatically configured by `minikube start`; or use `minikube kubectl -- …` if kubectl isn’t installed. |

---

## 🚀 Step 1 – Install Minikube

### macOS

```bash
brew install minikube
```

### Linux

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

### Windows (PowerShell)

```powershell
choco install minikube
```

A detailed Windows walkthrough (including WSL 2) is available from Ambassador Labs.

---

## ⚙️ Step 2 – Start the cluster

> **Make target**
>
> ```bash
> make minikube-start
> ```

<details>
<summary>Manual command (Docker driver)</summary>

```bash
minikube start \
  --driver=docker \
  --cpus=4 --memory=6g \
  --addons=ingress,ingress-dns \
  --profile=mcpgw
```

</details>

* `--driver=docker` avoids nested virtualization on macOS and Windows Home.
* `ingress` addon gives you NGINX with LoadBalancer semantics on localhost.
* `ingress-dns` resolves `*.local` hostnames automatically when you add Minikube’s IP to your OS DNS list.
* Flags `--cpus` and `--memory` accept **`max`** to use everything available.

> Check everything is healthy:
>
> ```bash
> minikube status
> kubectl get pods -n ingress-nginx
> ```

---

## 🏗 Step 3 – Load the Gateway image

### Option A – Build inside the Docker driver

> The Docker engine used by Minikube is **your host Docker daemon**, so `docker build` automatically makes the image visible.

```bash
make docker            # or docker build -t mcpgateway:latest -f Containerfile .
```

### Option B – Push pre-built images into Minikube cache

```bash
minikube cache add quay.io/your_ns/mcpgateway:latest   # stores & pre-loads next boot:contentReference[oaicite:10]{index=10}
minikube cache reload                                  # run if you rebuilt the tag
```

### Option C – Load a local tarball

```bash
docker save mcpgateway:latest | \
  minikube image load -                                     # alt: minikube image load mcpgateway:latest
```

Stack Overflow documents both `image load` and `cache add` patterns.

---

## 📄 Step 4 – Apply Kubernetes manifests

Reuse the YAML from `docs/kubernetes.md` (Deployment + Service + Ingress).
If you enable `ingress-dns`, define an Ingress host such as `gateway.local`; otherwise omit the `host:` and access via NodePort.

```bash
kubectl apply -f k8s/postgres.yaml      # or Helm chart for Postgres
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/mcpgateway.yaml
kubectl apply -f k8s/mcpgateway-ingress.yaml
```

Minikube auto-configures `kubectl` context on cluster creation; if not, run:

```bash
kubectl config use-context minikube    # or: minikube kubectl -- apply -f …
```



---

## 🌐 Step 5 – Test access

```bash
# IP-based
minikube service mcpgateway --url        # prints http://127.0.0.1:xxxx
curl $(minikube service mcpgateway --url)/health

# Ingress DNS (after editing system DNS => minikube ip)
curl http://gateway.local/health
```

---

## 🧹 Cleaning up

| Action               | Make                   | Manual                                    |
| -------------------- | ---------------------- | ----------------------------------------- |
| Pause cluster        | `make minikube-stop`   | `minikube stop -p mcpgw`                  |
| Delete cluster       | `make minikube-delete` | `minikube delete -p mcpgw`                |
| Remove cached images | —                      | `minikube cache delete mcpgateway:latest` |

---

## 🛠 Non-Make cheatsheet

| Task                     | Command                                               |
| ------------------------ | ----------------------------------------------------- |
| Start with Podman driver | `minikube start --driver=podman --network-plugin=cni` |
| View dashboard           | `minikube dashboard`                                  |
| SSH into node            | `minikube ssh`                                        |
| Enable metrics-server    | `minikube addons enable metrics-server`               |
| Upgrade Minikube         | `minikube delete && brew upgrade minikube`            |

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

5. Using Minikube’s built-in kubectl
   [https://minikube.sigs.k8s.io/docs/handbook/kubectl/](https://minikube.sigs.k8s.io/docs/handbook/kubectl/)

6. Allocate max CPU/RAM flags
   [https://minikube.sigs.k8s.io/docs/faq/#how-can-i-allocate-maximum-resources-to-minikube](https://minikube.sigs.k8s.io/docs/faq/#how-can-i-allocate-maximum-resources-to-minikube)

7. Ingress-DNS addon overview
   [https://minikube.sigs.k8s.io/docs/handbook/addons/ingress-dns/](https://minikube.sigs.k8s.io/docs/handbook/addons/ingress-dns/)

8. Stack Overflow: loading local images into Minikube
   [https://stackoverflow.com/questions/42564058/how-can-i-use-local-docker-images-with-minikube](https://stackoverflow.com/questions/42564058/how-can-i-use-local-docker-images-with-minikube)

---

Minikube gives you the fastest, vendor-neutral sandbox for experimenting with MCP Gateway—and everything above doubles as CI instructions for self-hosted GitHub runners or ephemeral integration tests.
