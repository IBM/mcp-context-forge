# Deployment Overview

This section explains how to deploy MCP Gateway in various environments - from local development to cloud-native platforms like Kubernetes, IBM Code Engine, AWS, and Azure.

---

## 🔐 Security First

**Before deploying to production**, review our [Security Guide](../manage/securing.md) for:

- Critical security configurations
- Production hardening checklist
- Authentication and authorization setup
- Network security best practices
- Container security requirements

---

## 🗺 Deployment Options

MCP Gateway supports multiple deployment strategies:

| Method                                | Description                                                                               |
| ------------------------------------- | ----------------------------------------------------------------------------------------- |
| [Local](local.md)                     | Run directly on your dev machine using `make`, `uvicorn`, or a virtual-env                |
| [Container](container.md)             | Package and run as a single container image using Podman or Docker                        |
| [Compose Stack](compose.md)           | Bring up Gateway + Postgres + Redis (and optional MPC servers) with Podman/Docker Compose |
| [Minikube](minikube.md)               | Launch a local single-node Kubernetes cluster and deploy the Gateway stack                |
| [Kubernetes](kubernetes.md)           | Generic manifests or Helm chart for any K8s-compliant platform                            |
| [OpenShift](openshift.md)             | OpenShift-specific deployment using Routes, SCCs, and Operator-managed back-ends          |
| [IBM Code Engine](ibm-code-engine.md) | Serverless container build & run on IBM Cloud                                             |
| [AWS](aws.md)                         | Deploy on ECS Fargate, EKS, or EC2-hosted containers                                      |
| [Azure](azure.md)                     | Run on Azure Container Apps, App Service, or AKS                                          |
| [**Security Guide**](../manage/securing.md)     | **Essential security configurations and best practices for production deployments**        |
| [**Performance Architecture**](../architecture/performance-architecture.md) | **Visual overview of Rust-powered components, caching layers, and scaling architecture** |

---

## 🛠 Runtime Configuration

MCP Gateway loads configuration from:

- `.env` file (in project root or mounted at `/app/.env`)
- Environment variables (overrides `.env`)
- CLI flags (e.g., via `run.sh`)

⚠️ **Security Note**: Never store sensitive credentials directly in environment variables. Use a secrets management system in production. See the [Security Guide](../manage/securing.md#5-secrets-management) for details.

---

## 🧪 Health Checks

All deployments should expose:

```bash
GET /health
```

This returns basic system latency metrics and can be used with cloud provider readiness probes.

---

## 📦 Container Basics

The default container image:

* Uses the Red Hat Universal Base image running as a non-root user
* Exposes port `4444`
* Runs `gunicorn` with Uvicorn workers
* Uses `.env` for all settings

> For Kubernetes, you can mount a ConfigMap or Secret as `.env`.

**Important**: For production deployments, ensure you follow the container hardening guidelines in our [Security Guide](../manage/securing.md#4-container-security).
