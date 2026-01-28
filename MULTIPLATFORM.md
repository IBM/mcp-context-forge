# Multiplatform Container Builds

This project supports building container images for multiple CPU architectures:

- **amd64** (x86_64) - Intel/AMD processors
- **arm64** (aarch64) - Apple Silicon, AWS Graviton, Raspberry Pi 4+
- **s390x** - IBM Z mainframes
- **ppc64le** - IBM POWER systems

## Quick Start

```bash
# Build for your local architecture only
make container-build

# Validate multiplatform build (all 4 architectures)
make container-build-multi

# Build and push to a registry
make container-build-multi REGISTRY=ghcr.io/your-org

# Inspect a multiplatform manifest
make container-inspect-manifest REGISTRY=ghcr.io/ibm/mcp-context-forge:latest
```

## Containerfiles

| File | Base Image | Platforms | Size | Use Case |
|------|------------|-----------|------|----------|
| `Containerfile.lite` | ubi10-minimal | amd64, arm64, s390x, ppc64le | ~150MB | Multiplatform builds, CI/CD |
| `Containerfile.scratch` | scratch | amd64 only* | ~100MB | Smallest possible image |

*`Containerfile.scratch` uses `dnf --installroot` which fails under QEMU emulation, so it only works for native builds.

### Using the scratch-based image

```bash
make container-build CONTAINER_FILE=Containerfile.scratch
```

## How It Works

### Local Builds

The local Docker daemon can only store images for **one architecture at a time**. When you run:

```bash
make container-build
```

It builds an image for your current machine's architecture and loads it into Docker.

### Multiplatform Builds

Multiplatform images are **manifest lists** - an index pointing to multiple platform-specific images stored in a registry. They cannot be stored locally.

```bash
# This validates the build works for all platforms (cached in buildx)
make container-build-multi

# This builds AND pushes to a registry
make container-build-multi REGISTRY=localhost:5000
```

When someone pulls the image, Docker automatically selects the correct architecture:

```bash
# On amd64 machine - pulls amd64 image
docker pull ghcr.io/ibm/mcp-context-forge:latest

# On arm64 machine - pulls arm64 image
docker pull ghcr.io/ibm/mcp-context-forge:latest

# On s390x machine - pulls s390x image
docker pull ghcr.io/ibm/mcp-context-forge:latest

# On ppc64le machine - pulls ppc64le image
docker pull ghcr.io/ibm/mcp-context-forge:latest
```

## GitHub Actions

The `.github/workflows/docker-multiplatform.yml` workflow:

1. **Lints** the Dockerfile with Hadolint
2. **Builds** each platform in parallel:
   - amd64 on `ubuntu-latest` (native)
   - arm64 on `ubuntu-24.04-arm` (native)
   - s390x on `ubuntu-latest` with QEMU (emulated, slower)
   - ppc64le on `ubuntu-latest` with QEMU (emulated, slower)
3. **Creates** a multiplatform manifest
4. **Scans** for vulnerabilities (Trivy, Grype)
5. **Signs** with Cosign (keyless OIDC)

### Build Times

| Platform | Runner | Estimated Time |
|----------|--------|----------------|
| amd64 | Native | ~5-8 min |
| arm64 | Native | ~5-8 min |
| s390x | QEMU | ~30-45 min |
| ppc64le | QEMU | ~30-45 min |

## Architecture Differences

### s390x and ppc64le Specific

The s390x and ppc64le architectures require OpenSSL instead of BoringSSL for grpcio. This is handled automatically in the Containerfile:

```dockerfile
RUN if [ "$(uname -m)" = "s390x" ] || [ "$(uname -m)" = "ppc64le" ]; then \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='True'" > /etc/profile.d/use-openssl.sh; \
    fi
```

### Why ubi10-minimal?

The original `Containerfile.scratch` used `dnf --installroot` to create a minimal rootfs from scratch. This approach:

- Produces the smallest possible image (~100MB)
- Keeps the RPM database for security scanning
- **Fails under QEMU emulation** (dnf spawns subprocesses that QEMU can't handle)

The `Containerfile.lite` uses `ubi10-minimal` as the runtime base:

- Slightly larger (~150MB) but still minimal
- Works with QEMU emulation for cross-platform builds
- Uses `microdnf` which is more QEMU-friendly
- Maintains RPM database for security scanning

## Inspecting Manifests

```bash
# Using make
make container-inspect-manifest REGISTRY=ghcr.io/ibm/mcp-context-forge:latest

# Using docker directly
docker buildx imagetools inspect ghcr.io/ibm/mcp-context-forge:latest
```

Example output:

```
Name:      ghcr.io/ibm/mcp-context-forge:latest
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:abc123...

Manifests:
  Name:      ghcr.io/ibm/mcp-context-forge:latest@sha256:def456...
  MediaType: application/vnd.oci.image.manifest.v1+json
  Platform:  linux/amd64

  Name:      ghcr.io/ibm/mcp-context-forge:latest@sha256:ghi789...
  MediaType: application/vnd.oci.image.manifest.v1+json
  Platform:  linux/arm64

  Name:      ghcr.io/ibm/mcp-context-forge:latest@sha256:jkl012...
  MediaType: application/vnd.oci.image.manifest.v1+json
  Platform:  linux/s390x

  Name:      ghcr.io/ibm/mcp-context-forge:latest@sha256:mno345...
  MediaType: application/vnd.oci.image.manifest.v1+json
  Platform:  linux/ppc64le
```

## Local Registry Testing

To test multiplatform images locally:

```bash
# Start a local registry
docker run -d -p 5000:5000 --name registry registry:2

# Build and push
make container-build-multi REGISTRY=localhost:5000

# Inspect
make container-inspect-manifest REGISTRY=localhost:5000/mcpgateway/mcpgateway:latest

# Pull specific platform
docker pull --platform linux/arm64 localhost:5000/mcpgateway/mcpgateway:latest
```

## Troubleshooting

### Build fails on s390x or ppc64le with QEMU

If you see errors like:
```
ERROR: process "/dev/.buildkit_qemu_emulator /bin/bash ..." did not complete successfully
```

This usually means a command doesn't work under QEMU emulation. The `Containerfile.lite` is designed to avoid these issues by using `ubi10-minimal` + `microdnf`.

### Buildx builder not found

```bash
# Create the builder
docker buildx create --name mcpgateway-builder --driver docker-container

# Use it
docker buildx use mcpgateway-builder
```

### No space left on device

Buildx caches can grow large. Clean them:

```bash
docker buildx prune -f
```
