# ADR-0019: Modular Architecture Split (14 Independent Modules)

- *Status:* Accepted
- *Date:* 2025-10-27
- *Deciders:* Core Engineering Team

## Context

The ContextForge codebase has grown to support diverse use cases:
- Standalone Python module for development
- Serverless deployments (Lambda, Cloud Run, Code Engine)
- Container orchestration (Kubernetes, OpenShift)
- Multi-regional deployments with federation
- Independent utility tools (translate, wrapper, reverse-proxy)
- Plugin ecosystem with external integrations
- MCP servers in multiple languages (Python, Go, Rust)

The monolithic architecture created challenges:
- Large repository difficult to navigate
- Plugins tied to core release cycle
- Utilities that should be standalone had unnecessary dependencies
- Single CI/CD pipeline for everything
- Conflicting versioning needs (core vs. plugins vs. servers)
- Difficult to deploy only what's needed

We needed maximum deployment flexibility while maintaining cohesive functionality.

## Decision

We will split the ContextForge ecosystem into **14 independently deployable modules** that can run standalone or be composed together:

### Core Gateway (2 modules)
1. **mcp-contextforge-gateway-core** - FastAPI gateway with 33 services, 11 routers (~150K lines)
2. **mcp-contextforge-gateway-ui** - HTMX + Alpine.js admin interface

### Independent Utilities (3 modules) - Zero Gateway Dependencies
3. **mcp-contextforge-translate** - Protocol bridge: stdio ↔ SSE ↔ HTTP ↔ gRPC
4. **mcp-contextforge-wrapper** - MCP client wrapper
5. **mcp-contextforge-reverse-proxy** - NAT/firewall traversal proxy

### Plugin Ecosystem (2 modules)
6. **mcp-contextforge-plugins-python** - 40+ Python plugins + framework
7. **mcp-contextforge-plugins-rust** - High-performance PyO3 plugins

### MCP Servers (3 modules) - Zero Gateway Dependencies
8. **mcp-contextforge-mcp-servers-python** - 4 Python servers
9. **mcp-contextforge-mcp-servers-go** - 5 Go servers (static binaries, 5-15 MB)
10. **mcp-contextforge-mcp-servers-rust** - Rust servers (static binaries, 3-10 MB)

### Agent Runtimes (1 module)
11. **mcp-contextforge-agent-runtimes** - LangChain + future runtimes

### Infrastructure (2 modules)
12. **mcp-contextforge-helm** - Kubernetes Helm charts (OCI registry)
13. **mcp-contextforge-deployment-scripts** - Terraform, Ansible, Docker Compose

### Documentation (1 module)
14. **mcp-contextforge-docs** - MkDocs Material site

**Key Design Principles:**
- **Zero dependency utilities** - translate, wrapper, reverse-proxy can run without gateway
- **Zero dependency servers** - MCP servers only require MCP SDK
- **Independent versioning** - Each module has its own semver
- **Feature flags** - All features configurable via .env (can disable/enable independently)

## Consequences

### Positive

- 🔧 **Maximum deployment flexibility** - Deploy only what you need
- 📦 **Independent versioning** - Core, plugins, utilities version independently
- 🚀 **Parallel development** - Teams work on different modules without conflicts
- 🎯 **Focused repositories** - Easier navigation and contribution
- 💡 **Clear ownership** - CODEOWNERS per repository
- 🌍 **Multiple deployment targets** - Standalone, serverless, containers, K8s
- 📊 **Feature flags** - Enable/disable features via environment variables
- 🔌 **Zero-dependency utilities** - translate/wrapper/reverse-proxy fully standalone

### Negative

- 🔄 **Cross-repo dependencies** - Plugins depend on core gateway version
- 📚 **More repositories** - 14 repos to maintain vs. 1 monorepo
- 🔀 **Coordination overhead** - Breaking changes require multi-repo updates

### Neutral

- 📦 **Multiple package formats** - PyPI, containers, Helm, binaries
- 🔀 **CI/CD per module** - Each module has its own GitHub Actions workflow

## Deployment Examples

**Standalone Python Module (Development):**
```bash
python -m mcpgateway  # Core gateway only
# SQLite + memory cache, zero external dependencies
```

**Serverless (AWS Lambda):**
```python
# Deploy only core gateway + specific plugins
# No need for Helm, deployment scripts, or full server collection
```

**Kubernetes with Optional Components:**
```bash
# Install base gateway + UI
helm install mcp-gateway contextforge/mcp-gateway

# Optionally add nginx caching proxy
helm install nginx-proxy contextforge/nginx-proxy

# Optionally add specific MCP servers
kubectl apply -f mcp-server-docx.yaml
```

**Edge Deployment (Minimal Footprint):**
```bash
# Just the translate utility as a static Go binary
./mcptranslate --stdio "command" --port 9000
# No gateway, no Python, just protocol translation
```

## Module Independence Matrix

| Module | Gateway Dependency | Can Run Standalone | Package Formats |
|--------|-------------------|-------------------|-----------------|
| gateway-core | - | ✅ Yes | PyPI, Container |
| gateway-ui | Requires core | ❌ No | PyPI |
| translate | None | ✅ Yes | PyPI, Container, Binary |
| wrapper | None | ✅ Yes | PyPI, Container |
| reverse-proxy | None | ✅ Yes | PyPI, Container |
| plugins-python | Requires core | ❌ No | PyPI |
| plugins-rust | Requires core | ❌ No | PyPI (wheels) |
| mcp-servers-python | None | ✅ Yes | PyPI, Container |
| mcp-servers-go | None | ✅ Yes | Binary, Container |
| mcp-servers-rust | None | ✅ Yes | Binary, Container |
| agent-runtimes | Optional | ✅ Yes | PyPI, Container |
| helm | Deploys others | ✅ Yes | Helm OCI |
| deployment-scripts | Deploys others | ✅ Yes | Git repo |
| docs | None | ✅ Yes | GitHub Pages |

## Feature Flags

All gateway features are configurable via environment variables:

```bash
# Core features
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_A2A_ENABLED=true

# Performance features
COMPRESSION_ENABLED=true
CACHE_TYPE=redis|memory|database

# Plugin system
PLUGINS_ENABLED=true
PLUGIN_CONFIG_FILE=plugins/config.yaml

# Transport protocols
MCPGATEWAY_SSE_ENABLED=true
MCPGATEWAY_WEBSOCKET_ENABLED=true
```

This allows deploying the core gateway with only required features enabled, reducing memory footprint and attack surface.

## Versioning Strategy

- **Core Gateway:** Independent semver (e.g., v0.9.0)
- **UI:** Follows core version
- **Plugins:** Per-plugin semver (e.g., pii-filter-v1.2.0)
- **Standalone Tools:** Independent semver (e.g., translate-v1.0.0)
- **MCP Servers:** Per-server semver (e.g., docx-v1.0.0)
- **Helm Chart:** Chart version + app version (e.g., Chart: 1.0.0, App: 0.9.0)

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Monolithic repository** | Too large, slow CI/CD, conflicting versions, difficult navigation |
| **Single binary (Go/Rust rewrite)** | Loss of Python ecosystem, major rewrite cost, slower development |
| **Microservices architecture** | Too heavyweight for many use cases, operational complexity |
| **Monorepo with Bazel/Nx** | Complex build system, overkill for 14 modules |

## Migration Path

1. Extract utilities (translate, wrapper, reverse-proxy) to independent repos
2. Extract MCP servers (Python, Go, Rust) to independent repos
3. Extract plugins to independent repos
4. Extract infrastructure (Helm, deployment scripts) to independent repos
5. Core gateway remains with UI as optional dependency
6. Update documentation with new repository structure
7. Maintain backward compatibility during transition

## Status

This decision is accepted and planned for implementation. See GitHub issue #1340 for detailed migration plan.

## References

- Proposal: GitHub Issue #1340 (Monorepo Split Proposal)
- Current architecture: docs/docs/architecture/index.md
- CLI tools: mcpgateway --help, mcptranslate --help
- Feature flags: .env.example
