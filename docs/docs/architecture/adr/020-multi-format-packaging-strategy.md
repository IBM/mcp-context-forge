# ADR-0020: Multi-Format Packaging Strategy

- *Status:* Accepted
- *Date:* 2025-10-27
- *Deciders:* Core Engineering Team

## Context

ContextForge supports diverse deployment scenarios with different packaging requirements:

- **Developers** need easy installation for local development (pip install)
- **Serverless platforms** (Lambda, Cloud Run) need container images or deployment packages
- **Kubernetes/OpenShift** operators need Helm charts with configurable values
- **Edge deployments** need lightweight static binaries
- **CI/CD pipelines** need multi-arch container images
- **Enterprise users** need signed releases with SBOM and provenance

Each deployment target has different constraints:

- PyPI packages work for Python environments
- Container images work for Kubernetes, serverless containers
- Helm charts simplify Kubernetes deployments
- Static binaries work for edge devices without Python runtime
- Multi-arch support needed for amd64 (x86_64) and arm64 (Apple Silicon, AWS Graviton)

## Decision

We will package ContextForge in **multiple formats** to support all deployment scenarios:

### 1. PyPI Packages (Python Distribution)

**Core packages:**

- `mcp-contextforge-gateway` - Core gateway application
- `mcp-contextforge-gateway-ui` - Admin UI (installs as plugin)
- `mcp-contextforge-translate` - Protocol bridge utility
- `mcp-contextforge-wrapper` - MCP client wrapper
- `mcp-contextforge-reverse-proxy` - NAT traversal proxy

**Plugin packages:**

- `mcp-contextforge-plugin-framework` - Plugin framework
- Individual plugins: `mcp-contextforge-plugin-{name}` (40+ packages)
- Meta package: `mcp-contextforge-plugins-all` (installs all plugins)

**MCP Server packages:**

- Individual servers: `mcp-server-{name}` (Python servers)
- Rust plugin wheels with PyO3 (cross-compiled for amd64/arm64)

**Installation:**
```bash
# Core gateway
pip install mcp-contextforge-gateway

# With all plugins
pip install mcp-contextforge-gateway mcp-contextforge-plugins-all

# Standalone utility
pip install mcp-contextforge-translate
```

### 2. Container Images (Docker/Podman)

**Images hosted on GitHub Container Registry (ghcr.io):**

- `ghcr.io/contextforge-org/mcp-gateway:latest` - Core gateway
- `ghcr.io/contextforge-org/mcp-gateway-ui:latest` - Gateway + UI
- `ghcr.io/contextforge-org/translate:latest` - Translate utility
- `ghcr.io/contextforge-org/wrapper:latest` - Wrapper utility
- `ghcr.io/contextforge-org/reverse-proxy:latest` - Reverse proxy
- Per-server images: `ghcr.io/contextforge-org/mcp-server-{name}:latest`

**Multi-arch support:**

- `linux/amd64` (x86_64) - Standard Intel/AMD servers
- `linux/arm64` (aarch64) - Apple Silicon, AWS Graviton, Raspberry Pi

**Image features:**

- Minimal base images (Alpine Linux where possible)
- Non-root user for security
- Health check endpoints configured
- Multi-stage builds for smaller images
- Signed with cosign (keyless OIDC)
- SBOM included (Syft, SPDX format)

**Usage:**
```bash
# Run core gateway
docker run -p 4444:4444 ghcr.io/contextforge-org/mcp-gateway:latest

# Run on ARM64 (Apple Silicon)
docker run --platform linux/arm64 ghcr.io/contextforge-org/mcp-gateway:latest
```

### 3. Helm Charts (Kubernetes Deployment)

**Chart repository:**

- OCI registry: `oci://ghcr.io/contextforge-org/helm-charts/mcp-stack`
- Artifact Hub: Public listing for discoverability

**Chart features:**

- Configurable resource limits and requests
- Horizontal Pod Autoscaler (HPA) support
- PostgreSQL and Redis dependencies (optional)
- Ingress configuration (nginx, Traefik, Istio)
- ConfigMap for environment variables
- Secrets management integration
- Pod disruption budgets
- Network policies
- Service mesh compatibility (Istio, Linkerd)

**Installation:**
```bash
# Add Helm repo
helm repo add contextforge oci://ghcr.io/contextforge-org/helm-charts

# Install with default values
helm install mcp-stack contextforge/mcp-stack

# Install with custom values (production)
helm install mcp-stack contextforge/mcp-stack \
  -f production-values.yaml \
  --set replicaCount=5 \
  --set hpa.enabled=true
```

### 4. Static Binaries (Go/Rust Servers)

**Binary targets:**

- Go servers: Cross-compiled Go executables (5-15 MB)
- Rust servers: Static Rust binaries (3-10 MB)
- Platforms: linux-amd64, linux-arm64, darwin-amd64, darwin-arm64, windows-amd64

**Distribution:**

- GitHub Releases with checksums
- Signed with GPG and cosign
- SLSA Build Level 3 provenance

**Usage:**
```bash
# Download and run Go server
curl -LO https://github.com/contextforge-org/mcp-servers-go/releases/download/v1.0.0/mcp-server-time-linux-amd64
chmod +x mcp-server-time-linux-amd64
./mcp-server-time-linux-amd64 --port 9000
```

## Consequences

### Positive

- 🎯 **Right tool for the job** - Each deployment gets optimal packaging format
- 🐍 **Easy development** - pip install for local development
- 🐳 **Cloud-native** - Container images for Kubernetes, serverless
- ☸️ **Simplified K8s** - Helm charts with best practices and HPA
- 🚀 **Edge deployments** - Static binaries for minimal environments
- 🌍 **Multi-arch support** - Works on x86_64 and ARM64 (Apple Silicon, Graviton)
- 🔒 **Supply chain security** - Signed releases, SBOM, provenance

### Negative

- 🔧 **Maintenance overhead** - Multiple build pipelines and release processes
- 📦 **Storage costs** - Container images and binaries consume registry space
- 🔄 **Version synchronization** - Must keep package versions aligned
- 📚 **Documentation** - Need installation guides for each format

### Neutral

- 🏗️ **CI/CD complexity** - GitHub Actions workflows per format
- 📊 **Metrics** - Track downloads per format to understand usage

## Package Matrix

| Format | Core Gateway | Utilities | Plugins | MCP Servers | Helm | Use Case |
|--------|--------------|-----------|---------|-------------|------|----------|
| **PyPI** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Python only | ❌ No | Local dev, pip install |
| **Containers** | ✅ Yes | ✅ Yes | ✅ Bundled | ✅ All languages | ❌ No | K8s, serverless, Docker |
| **Helm** | ✅ Yes | ✅ Optional | ✅ Optional | ✅ Optional | ✅ Yes | Kubernetes production |
| **Binaries** | ❌ No | ⚠️ Future | ❌ No | ✅ Go/Rust only | ❌ No | Edge, embedded systems |

## Multi-Arch Build Strategy

**Container images:**
```bash
# Build multi-arch image with BuildKit
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/contextforge-org/mcp-gateway:latest \
  --push .
```

**Python wheels (Rust plugins):**
```bash
# Cross-compile Rust plugin for multiple architectures
cargo build --release --target x86_64-unknown-linux-gnu
cargo build --release --target aarch64-unknown-linux-gnu
maturin build --release --target x86_64-unknown-linux-gnu
maturin build --release --target aarch64-unknown-linux-gnu
```

**Go binaries:**
```bash
# Cross-compile Go server
GOOS=linux GOARCH=amd64 go build -o mcp-server-time-linux-amd64
GOOS=linux GOARCH=arm64 go build -o mcp-server-time-linux-arm64
GOOS=darwin GOARCH=arm64 go build -o mcp-server-time-darwin-arm64
```

## Supply Chain Security

**All releases include:**

1. **Digital signatures** - GPG signed tags and releases
2. **Container signing** - cosign with keyless OIDC (Sigstore)
3. **SBOM** - Software Bill of Materials (Syft, SPDX format)
4. **Provenance** - SLSA Build Level 3 attestation
5. **Vulnerability scanning** - Trivy and Grype in CI/CD
6. **Checksums** - SHA256 for all binary artifacts

**Verification:**
```bash
# Verify container signature
cosign verify ghcr.io/contextforge-org/mcp-gateway:latest

# Verify binary checksum
sha256sum -c checksums.txt
```

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **PyPI only** | Doesn't work for Go/Rust servers, inconvenient for Kubernetes |
| **Containers only** | Poor developer experience, overkill for pip install |
| **Single monolithic package** | Too large, includes unnecessary dependencies |
| **OS-specific packages (deb, rpm)** | Narrow distribution, doesn't work for all platforms |
| **Snap/Flatpak** | Limited adoption, primarily for desktop apps |

## Status

This decision is implemented. All formats are available through respective registries.

## References

- PyPI: https://pypi.org/project/mcp-contextforge-gateway/
- Container Registry: https://github.com/orgs/contextforge-org/packages
- Helm Charts: `oci://ghcr.io/contextforge-org/helm-charts/mcp-stack`
- GitHub Releases: https://github.com/contextforge-org/*/releases
- CI/CD: .github/workflows/
