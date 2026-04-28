# Packaging & Distribution

This guide covers how to package ContextForge for deployment in various environments, including building production containers and generating releases.

---

## 📦 Production Container (Podman or Docker)

Build an OCI-compliant container image using:

```bash
make podman        # builds using Containerfile.lite with Podman
# or manually
podman build -t mcpgateway:latest -f Containerfile.lite .
```

Or with Docker (if Podman is not available):

```bash
make docker        # builds using Containerfile.lite with Docker
# or manually
docker build -t mcpgateway:latest -f Containerfile.lite .
```

`Containerfile.lite` is the canonical multi-stage build (UBI builder → ubi-minimal
runtime) supporting amd64, arm64, s390x, and ppc64le, with optional Rust runtime
support (`--build-arg ENABLE_RUST=true`) and profiling tools
(`--build-arg ENABLE_PROFILING=true`).

---

## 🔐 Run with TLS (self-signed)

```bash
make podman-run-ssl
```

This uses self-signed certs from `./certs/` and runs HTTPS on port `4444`.

---

## 🛠 Container Run (HTTP)

```bash
make podman-run
```

This runs the container without TLS on port `4444`.

---

## 📝 Versioning

ContextForge uses semantic versioning (`MAJOR.MINOR.PATCH`) and the version is defined in:

```python
mcpgateway/__init__.py
```

You can bump the version manually or automate it via Git tags or CI/CD.

---

## 📁 Release Artifacts

If you need to ship ZIPs or wheels use the project build tooling:

```bash
make dist
# or
python3 -m build
```

Outputs land under `dist/`. You can then:

* Push to PyPI (internal or public)
* Upload to GitHub Releases
* Package in a `.deb`, `.rpm`, etc.

---

## 📂 What's in the Container?

A typical image includes:

* Gunicorn running with `mcpgateway.main:app`
* All code, static files, and compiled assets

> You can override settings using environment variables at runtime.
