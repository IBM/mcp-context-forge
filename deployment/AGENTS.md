# deployment/AGENTS.md

Infrastructure and deployment guidance for AI coding assistants.

## Directory Structure

```
deployment/
├── README.md
├── CHARTS.md           # Helm chart reference
├── k8s/                # Kubernetes manifests
├── knative/            # Knative serverless configs
├── ansible/            # Ansible playbooks
└── terraform/          # Terraform IaC

infra/                  # Local development infrastructure
├── postgres/           # PostgreSQL Docker setup
├── nginx/              # Nginx reverse proxy
└── monitoring/         # Prometheus/Grafana
```

## Container Operations

From repository root:

```bash
# Build
make container-build              # Auto-detect Docker/Podman

# Run
make container-run-ssl-host       # Run with TLS on :4444, host networking

# Manage
make container-stop               # Stop and remove container
make container-logs               # Show container logs

# Security
make security-scan                # Run Trivy + Grype vulnerability scans
```

## Kubernetes Deployment

### Using Helm (Recommended)

See `charts/AGENTS.md` for Helm chart usage.

```bash
cd charts/mcp-stack
make install
```

### Using Raw Manifests

The `k8s/` directory contains raw Kubernetes manifests:

```bash
kubectl apply -f deployment/k8s/
```

## Knative Serverless

The `knative/` directory contains Knative Service definitions for serverless deployment.

## Terraform

The `terraform/` directory contains infrastructure-as-code for cloud providers.

## Ansible

The `ansible/` directory contains playbooks for traditional server deployment.

## Local Infrastructure

The `infra/` directory provides Docker Compose components for local development:

```bash
# Start PostgreSQL
docker-compose -f infra/postgres/docker-compose.yml up -d

# Start Redis
docker-compose -f infra/redis/docker-compose.yml up -d

# Start monitoring stack
docker-compose -f infra/monitoring/docker-compose.yml up -d
```

## TLS/SSL

```bash
# Generate self-signed certificates
make certs

# Run with TLS
make serve-ssl                    # Gunicorn on :4444 with TLS
make container-run-ssl-host       # Container with TLS
```

Certificates are stored in `./certs/`.

## Environment Configuration

Key deployment environment variables:

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/db

# Redis
REDIS_URL=redis://host:6379

# Server
HOST=0.0.0.0
PORT=4444

# TLS (for serve-ssl)
SSL_CERTFILE=certs/server.crt
SSL_KEYFILE=certs/server.key
```

## Documentation

- [Container Deployment](docs/docs/deployment/container.md)
- [Kubernetes Deployment](docs/docs/deployment/kubernetes.md)
- [Cloud Deployments](docs/docs/deployment/) - AWS, Azure, GCP, Fly.io guides

## Key Files

- `Makefile` (root) - Container build/run commands
- `Containerfile` / `Dockerfile` - Container image definition
- `deployment/k8s/` - Kubernetes manifests
- `charts/mcp-stack/` - Helm chart
- `infra/` - Local development infrastructure
