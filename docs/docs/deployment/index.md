# Deployment Overview

This section explains how to deploy MCP Gateway in various environments — from local development to cloud-native platforms like Kubernetes, IBM Code Engine, AWS, and Azure.

---

## 🗺 Deployment Options

MCP Gateway supports multiple deployment strategies:

| Method | Description |
|--------|-------------|
| [Local](local.md) | Run directly on your dev machine using `make` or `uvicorn` |
| [Container](container.md) | Package and run as a container using Docker or Podman |
| [Kubernetes / OpenShift](kubernetes.md) | Deploy to any K8s-compliant platform using a Helm chart or manifests |
| [IBM Code Engine](ibm-code-engine.md) | Run in serverless containers on IBM Cloud |
| [AWS](aws.md) | Deploy to ECS, EKS, or EC2 instances |
| [Azure](azure.md) | Run using Azure Container Apps, Web Apps, or AKS |

---

## 🛠 Runtime Configuration

MCP Gateway loads configuration from:

- `.env` file (in project root or mounted at `/app/.env`)
- Environment variables (overrides `.env`)
- CLI flags (e.g., via `run.sh`)

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
