# cforge gateway - Deployment Tool

## Overview

The `cforge gateway` command is a powerful deployment tool for MCP Gateway and its external plugins. It provides a unified, declarative way to build, configure, and deploy the complete MCP stack from a single YAML configuration file.

### Why We Created It

Before `cforge gateway`, deploying MCP Gateway with external plugins required:

- **Manual container builds** for each plugin from different repositories
- **Complex mTLS certificate generation** and distribution
- **Hand-crafted Kubernetes manifests** or Docker Compose files
- **Environment variable management** across multiple services
- **Coordination** between gateway configuration and plugin deployments

`cforge gateway` solves these challenges by:

✅ **Automating the entire deployment pipeline** from source to running services
✅ **Managing mTLS certificates** automatically with proper distribution
✅ **Generating deployment manifests** (Kubernetes or Docker Compose) from a single source
✅ **Supporting multiple build modes** (Dagger for performance, plain Python for portability)
✅ **Validating configurations** before deployment
✅ **Integrating with CI/CD** workflows and secret management

---

## Features

### Build System

- **Dual-mode execution**: Dagger (optimal performance) or plain Python (fallback)
- **Git-based plugin builds**: Clone and build plugins from any Git repository
- **Pre-built image support**: Use existing Docker images
- **Multi-stage build support**: Build specific stages from Dockerfiles
- **Build caching**: Intelligent caching to speed up rebuilds

### Deployment Targets

- **Kubernetes**: Full manifest generation with ConfigMaps, Secrets, Services, Deployments
- **Docker Compose**: Complete stack with networking and volume management
- **Local development**: Quick testing with exposed ports
- **Production-ready**: Resource limits, health checks, and best practices

### Security

- **Automatic mTLS**: Generate and distribute certificates for gateway ↔ plugin communication
- **Certificate rotation**: Configurable validity periods
- **Secret management**: Integration with environment files and CI/CD vaults
- **Network isolation**: Proper service-to-service communication

### Workflow Automation

- **Validation**: Pre-flight checks before deployment
- **Build**: Build containers from source or pull pre-built images
- **Certificate generation**: Create mTLS cert hierarchy
- **Deployment**: Apply manifests to target environment
- **Verification**: Health check deployed services
- **Destruction**: Clean teardown

---

## Future Directions

The `cforge gateway` tool is actively evolving to support broader MCP ecosystem workflows. Planned enhancements include:

### MCP Server Lifecycle Management

Currently, `cforge gateway` focuses on deploying external plugins. Future versions will support the complete lifecycle of MCP servers:

- **Build & Deploy MCP Servers**: Build MCP servers from Git repositories, similar to current plugin support
- **Automatic Registration**: Deploy MCP servers and automatically register them with the gateway as peers
- **Plugin Attachment**: Attach and configure plugins for registered MCP servers, enabling policy enforcement and filtering at the server level
- **Configuration Generation**: Generate MCP server configurations from templates
- **Multi-Server Deployments**: Deploy multiple MCP servers as a coordinated fleet

This will enable declarative deployment of complete MCP ecosystems from a single configuration file:

```yaml
# Future concept
mcp_servers:
  - name: GitHubMCPServer
    repo: https://github.com/org/mcp-server-github.git
    auto_register: true          # Auto-register as gateway peer
    expose_tools: ["*"]          # Expose all tools through gateway
    expose_resources: ["repos"]  # Expose specific resources

    # Attach plugins to this MCP server
    plugins:
      - OPAPluginFilter          # Apply OPA policies to this server
      - PIIFilterPlugin          # Filter PII from responses
```

### Live MCP Server Discovery

Automatic discovery and registration of running MCP servers:

- **mDNS/Zeroconf Discovery**: Automatically discover MCP servers on the local network
- **Service Mesh Integration**: Integrate with Kubernetes service discovery
- **Dynamic Registration**: Register servers at runtime without redeployment
- **Health-Based Registration**: Automatically register/deregister based on health checks

### Container Security Policies

Attach security policies to built containers for enhanced compliance and governance:

- **OPA Policy Bundles**: Include Open Policy Agent (OPA) policies with container builds
- **SBOM Generation**: Automatically generate Software Bill of Materials (SBOM) for built images
- **Vulnerability Scanning**: Integrate Trivy/Grype scans into build pipeline
- **Policy Enforcement**: Define and enforce security policies (allowed packages, CVE thresholds, etc.)
- **Signing & Attestation**: Sign built images with Cosign/Sigstore
- **Runtime Security**: Define AppArmor/SELinux profiles for deployed containers

Example future configuration:

```yaml
# Future concept
security:
  policies:
    enabled: true
    opa_bundle: ./policies/container-security.rego
    sbom: true
    vulnerability_scan:
      enabled: true
      fail_on: critical
      allowlist: ["CVE-2024-1234"]
  signing:
    enabled: true
    keyless: true  # Sigstore keyless signing
```

These enhancements will make `cforge gateway` a comprehensive tool for building, securing, deploying, and managing the entire MCP infrastructure stack.

---

## Quick Start

### Installation

The `cforge` CLI is installed with the MCP Gateway package:

```bash
pip install -e .
```

Verify installation:

```bash
cforge --help
cforge gateway --help
```

### Basic Workflow

```bash
# 1. Validate your configuration
cforge gateway validate examples/deployment-configs/deploy-compose.yaml

# 2. Build containers (if building from source)
cforge gateway build examples/deployment-configs/deploy-compose.yaml

# 3. Generate mTLS certificates (if needed)
cforge gateway certs examples/deployment-configs/deploy-compose.yaml

# 4. Deploy the stack
cforge gateway deploy examples/deployment-configs/deploy-compose.yaml

# 5. Verify deployment health
cforge gateway verify examples/deployment-configs/deploy-compose.yaml

# 6. (Optional) Tear down
cforge gateway destroy examples/deployment-configs/deploy-compose.yaml
```

---

## Commands

### `cforge gateway validate`

Validates the deployment configuration file without making any changes.

```bash
cforge gateway validate <config-file>
```

**Example:**
```bash
cforge gateway validate deploy.yaml
```

**Output:**
- ✅ Configuration syntax validation
- ✅ Plugin name uniqueness check
- ✅ Required field verification
- ✅ Build configuration validation (image XOR repo)

---

### `cforge gateway build`

Builds container images for gateway and/or plugins from source repositories.

```bash
cforge gateway build <config-file> [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--plugins-only` | Only build plugin containers, skip gateway | `false` |
| `--plugin NAME`, `-p NAME` | Build specific plugin(s) only (can specify multiple) | All plugins |
| `--no-cache` | Disable Docker build cache | `false` |
| `--copy-env-templates` | Copy `.env.template` files from plugin repos | `true` |

**Examples:**
```bash
# Build everything
cforge gateway build deploy.yaml

# Build only plugins
cforge gateway build deploy.yaml --plugins-only

# Build specific plugin
cforge gateway build deploy.yaml --plugin OPAPluginFilter

# Build multiple plugins with no cache
cforge gateway build deploy.yaml --plugin OPAPluginFilter --plugin LLMGuardPlugin --no-cache
```

**What it does:**
1. Clones Git repositories (if `repo` specified)
2. Checks out specified branch/tag/commit (`ref`)
3. Builds Docker images from `containerfile` in `context` directory
4. Tags images appropriately for deployment
5. Copies `.env.template` files to `deploy/env/` for customization

---

### `cforge gateway certs`

Generates mTLS certificate hierarchy for secure gateway ↔ plugin communication.

```bash
cforge gateway certs <config-file>
```

**Example:**
```bash
cforge gateway certs deploy.yaml
```

**What it generates:**
```
certs/mcp/
├── ca/
│   ├── ca.crt          # Root CA certificate
│   └── ca.key          # Root CA private key
├── gateway/
│   ├── client.crt      # Gateway client certificate
│   ├── client.key      # Gateway client private key
│   └── ca.crt          # CA cert (for verification)
└── plugins/
    ├── PluginName1/
    │   ├── server.crt  # Plugin server certificate
    │   ├── server.key  # Plugin server private key
    │   └── ca.crt      # CA cert (for verification)
    └── PluginName2/
        ├── server.crt
        ├── server.key
        └── ca.crt
```

**Certificate Properties:**
- Validity: Configurable (default: 825 days)
- CN for gateway: `mcp-gateway`
- CN for plugins: `mcp-plugin-{PluginName}`
- SANs: `{PluginName}, mcp-plugin-{PluginName}, localhost`

---

### `cforge gateway deploy`

Deploys the complete MCP stack to the target environment.

```bash
cforge gateway deploy <config-file> [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--output-dir DIR`, `-o DIR` | Custom output directory for manifests | `deploy/` |
| `--dry-run` | Generate manifests without deploying | `false` |
| `--skip-build` | Skip container build step | `false` |
| `--skip-certs` | Skip certificate generation | `false` |

**Examples:**
```bash
# Full deployment
cforge gateway deploy deploy.yaml

# Dry-run (generate manifests only)
cforge gateway deploy deploy.yaml --dry-run

# Deploy with existing images and certs
cforge gateway deploy deploy.yaml --skip-build --skip-certs

# Custom output directory
cforge gateway deploy deploy.yaml --output-dir ./my-deployment
```

**Deployment Process:**
1. **Validate** configuration
2. **Build** containers (unless `--skip-build`)
3. **Generate certificates** (unless `--skip-certs` or already exist)
4. **Generate manifests** (Kubernetes or Docker Compose)
5. **Apply** to target environment:
   - **Kubernetes**: `kubectl apply -f`
   - **Docker Compose**: `docker-compose up -d`

**Generated Files:**
```
deploy/
├── env/                          # Environment files
│   ├── .env.gateway
│   ├── .env.PluginName1
│   └── .env.PluginName2
├── manifests/                    # Kubernetes OR
│   ├── namespace.yaml
│   ├── configmaps.yaml
│   ├── secrets.yaml
│   ├── gateway-deployment.yaml
│   ├── gateway-service.yaml
│   ├── plugin-deployments.yaml
│   └── plugin-services.yaml
└── docker-compose.yaml           # Docker Compose
```

---

### `cforge gateway verify`

Verifies that the deployed stack is healthy and running.

```bash
cforge gateway verify <config-file> [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--wait` | Wait for deployment to be ready | `true` |
| `--timeout SECONDS` | Wait timeout in seconds | `300` |

**Examples:**
```bash
# Verify deployment (wait up to 5 minutes)
cforge gateway verify deploy.yaml

# Quick check without waiting
cforge gateway verify deploy.yaml --no-wait

# Custom timeout
cforge gateway verify deploy.yaml --timeout 600
```

**Checks:**
- Container/pod readiness
- Health endpoint responses
- Service connectivity
- mTLS handshake (if enabled)

---

### `cforge gateway destroy`

Tears down the deployed MCP stack.

```bash
cforge gateway destroy <config-file> [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--force` | Skip confirmation prompt | `false` |

**Examples:**
```bash
# Destroy with confirmation
cforge gateway destroy deploy.yaml

# Force destroy without prompt
cforge gateway destroy deploy.yaml --force
```

**What it removes:**
- **Kubernetes**: Deletes all resources in namespace
- **Docker Compose**: Stops and removes containers, networks, volumes

⚠️ **Note:** This does NOT delete generated certificates or build artifacts. To clean those:
```bash
rm -rf certs/ deploy/
```

---

### `cforge gateway generate`

Generates deployment manifests without deploying them.

```bash
cforge gateway generate <config-file> [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--output DIR`, `-o DIR` | Output directory for manifests | `deploy/` |

**Examples:**
```bash
# Generate manifests
cforge gateway generate deploy.yaml

# Custom output directory
cforge gateway generate deploy.yaml --output ./manifests
```

**Use cases:**
- GitOps workflows (commit generated manifests)
- Manual review before deployment
- Integration with external deployment tools
- CI/CD pipeline artifact generation

---

### `cforge gateway version`

Shows version and runtime information.

```bash
cforge gateway version
```

**Output:**
```
┌─ Version Info ─────────────────┐
│ MCP Deploy                     │
│ Version: 1.0.0                 │
│ Mode: dagger                   │
│ Environment: local             │
└────────────────────────────────┘
```

---

## Global Options

These options apply to all commands:

| Option | Description | Default |
|--------|-------------|---------|
| `--dagger` | Enable Dagger mode (auto-downloads CLI if needed) | `false` (uses plain Python) |
| `--verbose`, `-v` | Verbose output | `false` |

**Examples:**
```bash
# Use plain Python mode (default)
cforge gateway deploy deploy.yaml

# Enable Dagger mode for optimized builds
cforge gateway --dagger deploy deploy.yaml

# Verbose mode
cforge gateway -v build deploy.yaml

# Combine options
cforge gateway --dagger -v deploy deploy.yaml
```

---

## Configuration Reference

### Deployment Configuration

Top-level deployment settings:

```yaml
deployment:
  type: kubernetes | compose        # Required: Deployment target
  project_name: my-project          # Docker Compose only
  namespace: mcp-gateway            # Kubernetes only
```

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `type` | string | ✅ | Deployment type: `kubernetes` or `compose` | - |
| `project_name` | string | ❌ | Docker Compose project name | - |
| `namespace` | string | ❌ | Kubernetes namespace | - |

---

### Gateway Configuration

Gateway server settings:

```yaml
gateway:
  # Build Configuration (choose ONE)
  image: mcpgateway/mcpgateway:latest    # Pre-built image
  # OR
  repo: https://github.com/org/repo.git  # Build from source
  ref: main                              # Git branch/tag/commit
  context: .                             # Build context directory
  containerfile: Containerfile           # Dockerfile path
  target: production                     # Multi-stage build target

  # Runtime Configuration
  port: 4444                             # Internal port
  host_port: 4444                        # Host port mapping (compose only)

  # mTLS Client Configuration (gateway → plugins)
  mtls_enabled: true                     # Enable mTLS
  mtls_verify: true                      # Verify server certs
  mtls_check_hostname: false             # Verify hostname

  # Container Registry Configuration (optional)
  registry:
    enabled: true                        # Enable registry push
    url: registry.example.com            # Registry URL
    namespace: myproject                 # Registry namespace/org
    push: true                           # Push after build
    image_pull_policy: IfNotPresent      # Kubernetes imagePullPolicy

  # Environment Variables
  env_vars:
    LOG_LEVEL: INFO
    MCPGATEWAY_UI_ENABLED: "true"
    AUTH_REQUIRED: "true"
    # ... (see full reference below)

  # Kubernetes-specific
  replicas: 2                            # Number of replicas
  service_type: ClusterIP                # Service type
  service_port: 4444                     # Service port
  memory_request: 256Mi                  # Memory request
  memory_limit: 512Mi                    # Memory limit
  cpu_request: 100m                      # CPU request
  cpu_limit: 500m                        # CPU limit
  image_pull_policy: IfNotPresent        # Image pull policy
```

**Build Configuration Fields:**

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `image` | string | ❌* | Pre-built Docker image | - |
| `repo` | string | ❌* | Git repository URL | - |
| `ref` | string | ❌ | Git branch/tag/commit | `main` |
| `context` | string | ❌ | Build context subdirectory | `.` |
| `containerfile` | string | ❌ | Containerfile/Dockerfile path | `Containerfile` |
| `target` | string | ❌ | Multi-stage build target | - |

\* **Either `image` OR `repo` must be specified**

**Runtime Configuration Fields:**

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `port` | integer | ❌ | Internal container port | `4444` |
| `host_port` | integer | ❌ | Host port mapping (compose only) | - |
| `env_vars` | object | ❌ | Environment variables | `{}` |
| `mtls_enabled` | boolean | ❌ | Enable mTLS client | `true` |
| `mtls_verify` | boolean | ❌ | Verify server certificates | `true` |
| `mtls_check_hostname` | boolean | ❌ | Verify hostname in cert | `false` |
| `registry` | object | ❌ | Container registry configuration | - |

**Container Registry Configuration Fields:**

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `enabled` | boolean | ❌ | Enable registry integration | `false` |
| `url` | string | ❌* | Registry URL (e.g., `docker.io`, `quay.io`, OpenShift registry) | - |
| `namespace` | string | ❌* | Registry namespace/organization/project | - |
| `push` | boolean | ❌ | Push image to registry after build | `true` |
| `image_pull_policy` | string | ❌ | Kubernetes imagePullPolicy (`Always`, `IfNotPresent`, `Never`) | `IfNotPresent` |

\* Required when `enabled: true`

**Kubernetes-specific Fields:**

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `replicas` | integer | ❌ | Number of pod replicas | `1` |
| `service_type` | string | ❌ | Service type (ClusterIP, NodePort, LoadBalancer) | `ClusterIP` |
| `service_port` | integer | ❌ | Service port | `4444` |
| `memory_request` | string | ❌ | Memory request | `256Mi` |
| `memory_limit` | string | ❌ | Memory limit | `512Mi` |
| `cpu_request` | string | ❌ | CPU request | `100m` |
| `cpu_limit` | string | ❌ | CPU limit | `500m` |
| `image_pull_policy` | string | ❌ | Image pull policy | `IfNotPresent` |

---

### Plugin Configuration

External plugin settings (array of plugin objects):

```yaml
plugins:
  - name: MyPlugin                       # Required: Unique plugin name

    # Build Configuration (choose ONE)
    image: myorg/myplugin:latest        # Pre-built image
    # OR
    repo: https://github.com/org/repo.git  # Build from source
    ref: main
    context: plugins/myplugin
    containerfile: Containerfile
    target: builder

    # Runtime Configuration
    port: 8000                           # Internal port
    expose_port: true                    # Expose on host (compose only)

    # mTLS Server Configuration (plugin server)
    mtls_enabled: true                   # Enable mTLS server

    # Container Registry Configuration (optional)
    registry:
      enabled: true                      # Enable registry push
      url: registry.example.com          # Registry URL
      namespace: myproject               # Registry namespace/org
      push: true                         # Push after build
      image_pull_policy: IfNotPresent    # Kubernetes imagePullPolicy

    # Environment Variables
    env_vars:
      LOG_LEVEL: DEBUG
      CUSTOM_SETTING: value

    # Plugin Manager Overrides (client-side)
    plugin_overrides:
      priority: 10
      mode: enforce
      description: "My custom plugin"
      tags: ["security", "filter"]

    # Kubernetes-specific
    replicas: 1
    service_type: ClusterIP
    service_port: 8000
    memory_request: 128Mi
    memory_limit: 256Mi
    cpu_request: 50m
    cpu_limit: 200m
    image_pull_policy: IfNotPresent
```

**Required Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique plugin identifier (used for cert CN, service names, etc.) |

**Build Configuration:** Same as Gateway (see above)

**Runtime Configuration:**

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `port` | integer | ❌ | Internal container port | `8000` |
| `expose_port` | boolean | ❌ | Expose port on host (compose only) | `false` |
| `env_vars` | object | ❌ | Environment variables | `{}` |
| `mtls_enabled` | boolean | ❌ | Enable mTLS server | `true` |
| `registry` | object | ❌ | Container registry configuration (same fields as gateway) | - |
| `plugin_overrides` | object | ❌ | Plugin manager config overrides | `{}` |

**Plugin Overrides:**

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `priority` | integer | Plugin execution priority (lower = earlier) | - |
| `mode` | string | `enforce`, `monitor`, or `dry-run` | - |
| `description` | string | Plugin description | - |
| `tags` | array | Plugin tags for categorization | - |
| `hooks` | array | Enabled hooks: `prompt_pre_fetch`, `tool_pre_invoke`, etc. | All hooks |

**Kubernetes-specific:** Same as Gateway (see above)

---

### Certificate Configuration

mTLS certificate generation settings:

```yaml
certificates:
  # Local certificate generation (default)
  validity_days: 825                     # Certificate validity period
  auto_generate: true                    # Auto-generate if missing
  ca_path: ./certs/mcp/ca               # CA certificate directory
  gateway_path: ./certs/mcp/gateway     # Gateway cert directory
  plugins_path: ./certs/mcp/plugins     # Plugins cert directory

  # OR use cert-manager (Kubernetes only)
  use_cert_manager: true                 # Use cert-manager for certificates
  cert_manager_issuer: mcp-ca-issuer    # Issuer/ClusterIssuer name
  cert_manager_kind: Issuer              # Issuer or ClusterIssuer
```

| Field | Type | Required | Description | Default |
|-------|------|----------|-------------|---------|
| `validity_days` | integer | ❌ | Certificate validity in days | `825` |
| `auto_generate` | boolean | ❌ | Auto-generate certificates locally if missing | `true` |
| `ca_path` | string | ❌ | CA certificate directory (local mode) | `./certs/mcp/ca` |
| `gateway_path` | string | ❌ | Gateway client cert directory (local mode) | `./certs/mcp/gateway` |
| `plugins_path` | string | ❌ | Plugin server certs base directory (local mode) | `./certs/mcp/plugins` |
| `use_cert_manager` | boolean | ❌ | Use cert-manager for certificate management (Kubernetes only) | `false` |
| `cert_manager_issuer` | string | ❌ | cert-manager Issuer/ClusterIssuer name | `mcp-ca-issuer` |
| `cert_manager_kind` | string | ❌ | cert-manager issuer kind: `Issuer` or `ClusterIssuer` | `Issuer` |

#### cert-manager Integration (Kubernetes Only)

[cert-manager](https://cert-manager.io) is a Kubernetes-native certificate management controller that automates certificate issuance and renewal.

**Benefits:**
- ✅ **Automatic Renewal**: Certificates renewed before expiry (default: at 2/3 of lifetime)
- ✅ **Native Kubernetes**: Certificates defined as Kubernetes Custom Resources
- ✅ **Simplified Operations**: No manual certificate generation or rotation
- ✅ **GitOps Friendly**: Certificate definitions version-controlled

**Prerequisites:**
1. Install cert-manager in your cluster:
   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
   ```

2. Create namespace and CA Issuer (one-time setup):
   ```bash
   # Create namespace first
   kubectl create namespace mcp-gateway-test

   # Apply CA Issuer
   kubectl apply -f examples/deployment-configs/cert-manager-issuer-example.yaml
   ```

**Configuration:**
```yaml
certificates:
  use_cert_manager: true
  cert_manager_issuer: mcp-ca-issuer
  cert_manager_kind: Issuer
  validity_days: 825
```

When `use_cert_manager: true`:
- Local certificate generation is skipped
- cert-manager Certificate CRDs are generated for gateway and plugins
- cert-manager automatically creates Kubernetes TLS secrets
- Certificates are auto-renewed before expiry

**Important**: The cert-manager Issuer and CA certificate are long-lived infrastructure. When you destroy your MCP deployment, the Issuer remains (by design) for reuse across deployments.

---

### Infrastructure Services

PostgreSQL and Redis are **automatically deployed** with the MCP Gateway stack using hardcoded defaults:

**PostgreSQL (always deployed):**
- Image: `postgres:17`
- Database: `mcp`
- User: `postgres`
- Password: `mysecretpassword` (override with `POSTGRES_PASSWORD` env var)
- Port: `5432`
- Kubernetes: Uses 10Gi PVC

**Redis (always deployed):**
- Image: `redis:latest`
- Port: `6379`

**Connection strings (auto-configured):**
```bash
DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/mcp
REDIS_URL=redis://redis:6379/0
```

These services are included in all deployments and cannot currently be disabled or customized via the deployment YAML. To customize PostgreSQL password:

```bash
# Set before deploying
export POSTGRES_PASSWORD=your-secure-password
cforge gateway deploy deploy.yaml
```

---

## Example Configurations

### Example 1: Docker Compose (No mTLS)

**File:** `examples/deployment-configs/deploy-compose.yaml`

Simple local deployment for development and testing:

```yaml
deployment:
  type: compose
  project_name: mcp-stack-test

gateway:
  image: mcpgateway/mcpgateway:latest
  port: 4444
  host_port: 4444

  env_vars:
    LOG_LEVEL: DEBUG
    MCPGATEWAY_UI_ENABLED: "true"
    AUTH_REQUIRED: "false"

  mtls_enabled: false

plugins:
  - name: OPAPluginFilter
    repo: https://github.com/terylt/mcp-context-forge.git
    ref: feat/use_mtls_plugins
    context: plugins/external/opa

    expose_port: true
    mtls_enabled: false

    plugin_overrides:
      priority: 10
      mode: "enforce"

certificates:
  auto_generate: true
```

**Use case:** Quick local testing without security overhead

**Deploy:**
```bash
cforge gateway deploy examples/deployment-configs/deploy-compose.yaml
```

**Access:**
- Gateway: http://localhost:4444
- Admin UI: http://localhost:4444/admin
- Plugin (exposed): http://localhost:8000

---

### Example 2: Docker Compose (With mTLS)

**File:** `examples/deployment-configs/deploy-compose.mtls.yaml`

Secure local deployment with mutual TLS:

```yaml
deployment:
  type: compose
  project_name: mcp-stack-test

gateway:
  image: mcpgateway/mcpgateway:latest
  port: 4444
  host_port: 4444

  mtls_enabled: true          # ← Enable mTLS client
  mtls_verify: true
  mtls_check_hostname: false  # Don't verify hostname for localhost

plugins:
  - name: OPAPluginFilter
    repo: https://github.com/terylt/mcp-context-forge.git
    ref: feat/use_mtls_plugins
    context: plugins/external/opa

    mtls_enabled: true         # ← Enable mTLS server

    plugin_overrides:
      priority: 10
      mode: "enforce"

certificates:
  validity_days: 825
  auto_generate: true          # Auto-generate mTLS certs
```

**Use case:** Local testing with production-like security

**Deploy:**
```bash
# Certificates are auto-generated during deploy
cforge gateway deploy examples/deployment-configs/deploy-compose.mtls.yaml
```

**How mTLS works:**
1. `cforge gateway certs` generates CA + gateway client cert + plugin server certs
2. Gateway connects to plugins using client certificate
3. Plugins verify gateway's client certificate against CA
4. All communication is encrypted and mutually authenticated

---

### Example 3: Kubernetes (Pre-built Images)

**File:** `examples/deployment-configs/deploy-k8s.yaml`

Production-ready Kubernetes deployment using pre-built images:

```yaml
deployment:
  type: kubernetes
  namespace: mcp-gateway-prod

gateway:
  image: mcpgateway/mcpgateway:latest
  image_pull_policy: IfNotPresent

  replicas: 2                  # High availability
  service_type: LoadBalancer
  service_port: 4444

  memory_request: 256Mi
  memory_limit: 512Mi
  cpu_request: 100m
  cpu_limit: 500m

  mtls_enabled: true

plugins:
  - name: OPAPluginFilter
    image: mcpgateway-opapluginfilter:latest
    image_pull_policy: IfNotPresent

    replicas: 2
    service_type: ClusterIP

    memory_request: 128Mi
    memory_limit: 256Mi
    cpu_request: 50m
    cpu_limit: 200m

    mtls_enabled: true

    plugin_overrides:
      priority: 10
      mode: "enforce"

infrastructure:
  postgres:
    enabled: true
    storage_size: 20Gi
    storage_class: fast-ssd
  redis:
    enabled: true

certificates:
  auto_generate: true
```

**Use case:** Production deployment with HA and resource limits

**Deploy:**
```bash
# Deploy to Kubernetes
cforge gateway deploy examples/deployment-configs/deploy-k8s.yaml

# Verify
kubectl get all -n mcp-gateway-prod

# Check logs
kubectl logs -n mcp-gateway-prod -l app=mcp-gateway
```

---

### Example 4: Kubernetes (Build from Source)

Building plugins from Git repositories in Kubernetes:

```yaml
deployment:
  type: kubernetes
  namespace: mcp-gateway-dev

gateway:
  image: mcpgateway/mcpgateway:latest

plugins:
  - name: OPAPluginFilter
    # Build from source
    repo: https://github.com/terylt/mcp-context-forge.git
    ref: feat/use_mtls_plugins
    context: plugins/external/opa
    containerfile: Containerfile

    # Push to registry (configure with env vars)
    # See DOCKER_REGISTRY in deploy process

    replicas: 1
    mtls_enabled: true

certificates:
  auto_generate: true
```

**Deploy:**
```bash
# Build locally and push to registry
export DOCKER_REGISTRY=myregistry.io/myorg
cforge gateway build deploy-k8s-build.yaml

# Deploy to Kubernetes
cforge gateway deploy deploy-k8s-build.yaml --skip-build
```

---

### Example 5: Kubernetes with cert-manager

**File:** `examples/deployment-configs/deploy-k8s-cert-manager.yaml`

Production deployment using cert-manager for automated certificate management:

```yaml
deployment:
  type: kubernetes
  namespace: mcp-gateway-test

gateway:
  image: mcpgateway/mcpgateway:latest
  image_pull_policy: IfNotPresent

  port: 4444
  service_type: ClusterIP
  service_port: 4444

  replicas: 1
  memory_request: 256Mi
  memory_limit: 512Mi
  cpu_request: 100m
  cpu_limit: 500m

  env_vars:
    LOG_LEVEL: DEBUG
    MCPGATEWAY_UI_ENABLED: "true"

  mtls_enabled: true
  mtls_verify: true
  mtls_check_hostname: false

plugins:
  - name: OPAPluginFilter
    image: mcpgateway-opapluginfilter:latest
    image_pull_policy: IfNotPresent

    port: 8000
    service_type: ClusterIP

    replicas: 1
    memory_request: 128Mi
    memory_limit: 256Mi

    mtls_enabled: true

    plugin_overrides:
      priority: 10
      mode: "enforce"

# cert-manager configuration
certificates:
  # Use cert-manager for automatic certificate management
  use_cert_manager: true

  # Reference the Issuer created in prerequisites
  cert_manager_issuer: mcp-ca-issuer
  cert_manager_kind: Issuer

  # Certificate validity (auto-renewed at 2/3 of lifetime)
  validity_days: 825

  # Local paths not used when use_cert_manager=true
  auto_generate: false
```

**Prerequisites:**

1. Install cert-manager:
   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
   ```

2. Create namespace and CA Issuer (one-time setup):
   ```bash
   # Create namespace first
   kubectl create namespace mcp-gateway-test

   # Apply CA Issuer
   kubectl apply -f examples/deployment-configs/cert-manager-issuer-example.yaml
   ```

**Deploy:**
```bash
# Deploy (no need to generate certificates manually)
cforge gateway deploy examples/deployment-configs/deploy-k8s-cert-manager.yaml

# Verify cert-manager created certificates
kubectl get certificates -n mcp-gateway-test
kubectl get secrets -n mcp-gateway-test | grep mcp-
```

**How it works:**
1. `cforge gateway deploy` skips local certificate generation
2. Generates cert-manager Certificate CRDs for gateway and plugins
3. Applies Certificate CRDs to Kubernetes
4. cert-manager automatically creates TLS secrets
5. Pods use the secrets created by cert-manager
6. cert-manager auto-renews certificates before expiry

**Certificate lifecycle:**
- **Creation**: cert-manager generates certificates when CRDs are applied
- **Renewal**: Automatic renewal at 2/3 of lifetime (550 days for 825-day cert)
- **Deletion**: Certificates deleted when stack is destroyed, Issuer remains

---

## mTLS Configuration Guide

### Understanding mTLS in MCP Gateway

**mTLS (Mutual TLS)** provides:
- **Encryption**: All gateway ↔ plugin traffic is encrypted
- **Authentication**: Both parties prove their identity
- **Authorization**: Only trusted certificates can communicate

### Certificate Hierarchy

```
CA (Root Certificate Authority)
├── Gateway Client Certificate
│   └── Used by gateway to connect to plugins
└── Plugin Server Certificates (one per plugin)
    └── Used by plugins to authenticate gateway
```

### Enabling mTLS

**In your configuration:**

```yaml
gateway:
  mtls_enabled: true              # Enable mTLS client
  mtls_verify: true               # Verify server certificates
  mtls_check_hostname: false      # Skip hostname verification (for localhost/IPs)

plugins:
  - name: MyPlugin
    mtls_enabled: true            # Enable mTLS server
```

### Certificate Generation

**Automatic (recommended):**
```yaml
certificates:
  auto_generate: true             # Auto-generate during deploy
  validity_days: 825              # ~2.3 years
```

**Manual:**
```bash
# Generate certificates explicitly
cforge gateway certs deploy.yaml

# Certificates are created in:
# - certs/mcp/ca/          (CA)
# - certs/mcp/gateway/     (gateway client cert)
# - certs/mcp/plugins/*/   (plugin server certs)
```

### Environment Variables

The deployment tool automatically sets these environment variables:

**Gateway (client):**
```bash
PLUGINS_CLIENT_MTLS_CERTFILE=/certs/gateway/client.crt
PLUGINS_CLIENT_MTLS_KEYFILE=/certs/gateway/client.key
PLUGINS_CLIENT_MTLS_CA_BUNDLE=/certs/gateway/ca.crt
PLUGINS_CLIENT_MTLS_VERIFY=true
PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME=false
```

**Plugin (server):**
```bash
PLUGINS_SERVER_SSL_CERTFILE=/certs/server.crt
PLUGINS_SERVER_SSL_KEYFILE=/certs/server.key
PLUGINS_SERVER_SSL_CA_CERTS=/certs/ca.crt
PLUGINS_SERVER_SSL_CERT_REQS=2    # CERT_REQUIRED
```

### Troubleshooting mTLS

**Problem: Certificate verification fails**

Check certificate validity:
```bash
openssl x509 -in certs/mcp/gateway/client.crt -noout -dates
openssl x509 -in certs/mcp/plugins/MyPlugin/server.crt -noout -dates
```

**Problem: Hostname mismatch errors**

Solution: Set `mtls_check_hostname: false` in gateway config, or use service DNS names

**Problem: Connection refused**

- Verify plugin has `mtls_enabled: true`
- Check plugin logs for certificate errors
- Ensure certificates are mounted correctly

**Problem: Expired certificates**

Regenerate:
```bash
rm -rf certs/
cforge gateway certs deploy.yaml
```

Then redeploy to distribute new certificates.

---

## Container Registry Integration

### Overview

The container registry feature allows you to build images locally and automatically push them to container registries (Docker Hub, Quay.io, OpenShift internal registry, private registries, etc.). This is essential for:

✅ **Kubernetes/OpenShift deployments** - Avoid ImagePullBackOff errors
✅ **Team collaboration** - Share images across developers and environments
✅ **CI/CD pipelines** - Build once, deploy everywhere
✅ **Production deployments** - Use trusted registry sources

### How It Works

1. **Build**: Images are built locally using docker/podman
2. **Tag**: Images are automatically tagged with the registry path
3. **Push**: Images are pushed to the registry (if `push: true`)
4. **Deploy**: Kubernetes manifests reference the registry images

### Configuration

Add a `registry` section to your gateway and/or plugin configurations:

```yaml
gateway:
  repo: https://github.com/yourorg/yourrepo.git

  # Container registry configuration
  registry:
    enabled: true                      # Enable registry integration
    url: registry.example.com          # Registry URL
    namespace: myproject                # Registry namespace/org/project
    push: true                          # Push after build (default: true)
    image_pull_policy: IfNotPresent    # Kubernetes imagePullPolicy
```

**Configuration Fields:**

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `enabled` | Yes | Enable registry push | `true` |
| `url` | Yes* | Registry URL | `docker.io`, `quay.io`, `registry.mycompany.com` |
| `namespace` | Yes* | Registry namespace/organization/project | `myusername`, `myorg`, `mcp-gateway-test` |
| `push` | No | Push image after build | `true` (default) |
| `image_pull_policy` | No | Kubernetes imagePullPolicy | `IfNotPresent` (default) |

\* Required when `enabled: true`

### Common Registry Examples

#### Docker Hub

```yaml
registry:
  enabled: true
  url: docker.io
  namespace: myusername
  push: true
  image_pull_policy: IfNotPresent
```

**Authentication:**
```bash
docker login
```

#### Quay.io

```yaml
registry:
  enabled: true
  url: quay.io
  namespace: myorganization
  push: true
  image_pull_policy: IfNotPresent
```

**Authentication:**
```bash
podman login quay.io
```

#### OpenShift Internal Registry

```yaml
registry:
  enabled: true
  url: default-route-openshift-image-registry.apps-crc.testing
  namespace: mcp-gateway-test
  push: true
  image_pull_policy: Always
```

**Authentication:**
```bash
# OpenShift Local (CRC)
podman login $(oc registry info) -u $(oc whoami) -p $(oc whoami -t)

# OpenShift on cloud
oc registry login
```

#### Private Registry

```yaml
registry:
  enabled: true
  url: registry.mycompany.com
  namespace: devteam
  push: true
  image_pull_policy: IfNotPresent
```

**Authentication:**
```bash
podman login registry.mycompany.com -u myusername
```

### Image Naming

When registry is enabled, images are automatically tagged with the full registry path:

**Local tag (without registry):**
```
mcpgateway-gateway:latest
mcpgateway-opapluginfilter:latest
```

**Registry tag (with registry enabled):**
```
registry.example.com/myproject/mcpgateway-gateway:latest
registry.example.com/myproject/mcpgateway-opapluginfilter:latest
```

### Image Pull Policies

Choose the appropriate policy for your use case:

| Policy | Description | Best For |
|--------|-------------|----------|
| `Always` | Pull image every time pod starts | Development, testing latest changes |
| `IfNotPresent` | Pull only if image doesn't exist locally | Production, stable releases |
| `Never` | Never pull, only use local images | Air-gapped environments |

### Workflow Example

#### OpenShift Local Deployment

```bash
# 1. Authenticate to OpenShift registry
podman login $(oc registry info) -u $(oc whoami) -p $(oc whoami -t)

# 2. Build and push images
cforge gateway deploy examples/deployment-configs/deploy-openshift-local-registry.yaml

# The tool will:
# - Build images locally
# - Tag with registry paths
# - Push to OpenShift internal registry
# - Generate manifests with registry image references
# - Deploy to cluster

# 3. Verify images were pushed
oc get imagestreams -n mcp-gateway-test

# Output:
# NAME                          IMAGE REPOSITORY
# mcpgateway-gateway           default-route-.../mcp-gateway-test/mcpgateway-gateway
# mcpgateway-opapluginfilter   default-route-.../mcp-gateway-test/mcpgateway-opapluginfilter
```

#### CI/CD Pipeline Example

```bash
# In your CI/CD pipeline:

# 1. Authenticate to registry
echo "$REGISTRY_PASSWORD" | docker login $REGISTRY_URL -u $REGISTRY_USER --password-stdin

# 2. Build and push
cforge gateway build deploy-prod.yaml

# 3. Images are automatically pushed to registry

# 4. Deploy to Kubernetes (manifests already reference registry images)
cforge gateway deploy deploy-prod.yaml --skip-build --skip-certs
```

### Per-Component Configuration

Each component (gateway and plugins) can have different registry settings:

```yaml
gateway:
  repo: https://github.com/myorg/gateway.git
  registry:
    enabled: true
    url: quay.io
    namespace: myorg
    push: true

plugins:
  - name: MyPlugin
    repo: https://github.com/myorg/plugin.git
    registry:
      enabled: true
      url: docker.io              # Different registry
      namespace: myusername        # Different namespace
      push: true

  - name: InternalPlugin
    repo: https://github.com/myorg/internal-plugin.git
    # No registry - use local image only
    registry:
      enabled: false
```

This allows you to:
- Push gateway to one registry, plugins to another
- Skip registry push for some components
- Use different namespaces per component
- Mix local and registry images

### Tag-Only Mode

To tag images without pushing (useful for testing):

```yaml
registry:
  enabled: true
  url: registry.example.com
  namespace: myproject
  push: false                    # Tag but don't push
```

**Use cases:**
- Test registry configuration before pushing
- Generate manifests with registry paths for GitOps
- Manual push workflow

### Troubleshooting

#### Authentication Errors

**Error:** `Failed to push to registry: unauthorized`

**Solution:** Authenticate to the registry before building:
```bash
# Docker Hub
docker login

# Quay.io
podman login quay.io

# Private registry
podman login registry.mycompany.com -u myusername

# OpenShift
podman login $(oc registry info) -u $(oc whoami) -p $(oc whoami -t)
```

#### ImagePullBackOff in Kubernetes

**Error:** Pods show `ImagePullBackOff` status

**Possible causes:**
1. Image doesn't exist in registry (push failed)
2. Registry authentication not configured in Kubernetes
3. Network connectivity issues
4. Wrong image path/tag

**Solutions:**

**1. Verify image exists:**
```bash
# OpenShift
oc get imagestreams -n mcp-gateway-test

# Docker Hub/Quay
podman search your-registry.com/namespace/image-name
```

**2. Configure Kubernetes pull secrets:**
```bash
# Create docker-registry secret
kubectl create secret docker-registry regcred \
  --docker-server=registry.example.com \
  --docker-username=myusername \
  --docker-password=mypassword \
  --docker-email=myemail@example.com \
  -n mcp-gateway-test

# Update deployment to use secret (manual step, or add to template)
```

**3. For OpenShift, grant pull permissions:**
```bash
# Allow default service account to pull from namespace
oc policy add-role-to-user system:image-puller \
  system:serviceaccount:mcp-gateway-test:default \
  -n mcp-gateway-test
```

#### Push Failed: Too Large

**Error:** `image push failed: blob upload exceeds max size`

**Solution:** Some registries have size limits. Options:
1. Use multi-stage builds to reduce image size
2. Switch to a registry with larger limits
3. Split into smaller images

#### Registry URL Format

**Correct formats:**
```yaml
url: docker.io                                    # Docker Hub
url: quay.io                                      # Quay.io
url: gcr.io                                       # Google Container Registry
url: registry.mycompany.com                       # Private registry
url: default-route-openshift-image-registry.apps-crc.testing  # OpenShift
```

**Incorrect formats:**
```yaml
url: https://docker.io                           # No protocol
url: docker.io/myusername                        # No namespace in URL
url: registry:5000                               # Include port in URL, not namespace
```

### Best Practices

✅ **DO:**
- Authenticate to registry before building
- Use specific version tags in production (not `:latest`)
- Test registry configuration with `push: false` first
- Use `image_pull_policy: Always` for development
- Use `image_pull_policy: IfNotPresent` for production
- Organize images by namespace/project

❌ **DON'T:**
- Commit registry credentials to Git
- Use `latest` tag in production
- Mix local and registry images without testing
- Skip authentication step
- Use `push: true` for testing without verifying first

### Example Configurations

Full examples available in:
- `examples/deployment-configs/deploy-openshift-local.yaml` - Registry config commented
- `examples/deployment-configs/deploy-openshift-local-registry.yaml` - Full registry setup

---

## Deployment Modes

### Plain Python Mode (Default)

**What is it?**
Pure Python implementation using standard tools (`docker`, `kubectl`, `git`, etc.). This is the **default mode** to avoid automatic downloads.

**When to use:**
- ✅ Default choice (no surprises)
- ✅ Environments without Dagger support
- ✅ Air-gapped networks
- ✅ Simple deployments
- ✅ Debugging/troubleshooting

**Requirements:**
- Python 3.11+
- Docker CLI
- `kubectl` (for Kubernetes deployments)
- `git` (for building from source)

**Usage:**
```bash
# Plain Python mode (default, no flag needed)
cforge gateway deploy deploy.yaml
```

**Characteristics:**
- Sequential builds
- Standard caching
- No external dependencies beyond Docker/kubectl

---

### Dagger Mode (Opt-in)

**What is Dagger?**
Dagger is a programmable CI/CD engine that runs pipelines in containers. It provides:
- **Reproducible builds**: Same results everywhere
- **Parallel execution**: Faster builds
- **Intelligent caching**: Only rebuild what changed
- **Cross-platform**: Works on any system with Docker

**When to use:**
- ✅ Local development (fastest builds)
- ✅ CI/CD pipelines (GitHub Actions, GitLab CI, etc.)
- ✅ Team environments (consistent results)
- ✅ When you want optimized build performance

**Requirements:**
- Docker or compatible container runtime
- `dagger-io` Python package (optional, installed separately)
- **Note**: First use will auto-download the Dagger CLI (~100MB)

**Enable:**
```bash
# Install dagger-io package first
pip install dagger-io

# Use Dagger mode (opt-in with --dagger flag)
cforge gateway --dagger deploy deploy.yaml
```

**Performance benefits:**
- 2-3x faster builds with caching
- Parallel plugin builds
- Efficient layer reuse

**Important**: Using `--dagger` will automatically download the Dagger CLI binary on first use if not already present. Use plain Python mode if you want to avoid automatic downloads

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Deploy MCP Gateway

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install cforge
        run: pip install -e .

      - name: Validate configuration
        run: cforge gateway validate deploy/deploy-prod.yaml

      - name: Build containers
        run: cforge gateway build deploy/deploy-prod.yaml
        env:
          DOCKER_REGISTRY: ${{ secrets.DOCKER_REGISTRY }}

      - name: Generate certificates
        run: cforge gateway certs deploy/deploy-prod.yaml

      - name: Deploy to Kubernetes
        run: cforge gateway deploy deploy/deploy-prod.yaml --skip-build
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG }}

      - name: Verify deployment
        run: cforge gateway verify deploy/deploy-prod.yaml
```

---

### GitLab CI

```yaml
stages:
  - validate
  - build
  - deploy

variables:
  CONFIG_FILE: deploy/deploy-prod.yaml

validate:
  stage: validate
  script:
    - pip install -e .
    - cforge gateway validate $CONFIG_FILE

build:
  stage: build
  script:
    - pip install -e .
    - cforge gateway build $CONFIG_FILE
  artifacts:
    paths:
      - deploy/

deploy:
  stage: deploy
  script:
    - pip install -e .
    - cforge gateway deploy $CONFIG_FILE --skip-build
  environment:
    name: production
  only:
    - main
```

---

## Best Practices

### Configuration Management

✅ **DO:**
- Version control your `deploy.yaml`
- Use Git tags/branches for plugin versions (`ref: v1.2.3`)
- Separate configs for dev/staging/prod
- Document custom `env_vars` in comments

❌ **DON'T:**
- Hardcode secrets in YAML (use environment files)
- Use `ref: main` in production (pin versions)
- Commit generated certificates to Git

### Environment Variables

✅ **DO:**
```bash
# Review and customize .env files after build
cforge gateway build deploy.yaml
# Edit deploy/env/.env.gateway
# Edit deploy/env/.env.PluginName
cforge gateway deploy deploy.yaml --skip-build
```

❌ **DON'T:**
```bash
# Deploy without reviewing environment
cforge gateway deploy deploy.yaml  # May use default/insecure values
```

### Certificate Management

✅ **DO:**
- Let `cforge` auto-generate certificates
- Rotate certificates before expiry
- Use separate CAs for dev/staging/prod
- Backup CA private key securely

❌ **DON'T:**
- Share certificates between environments
- Commit CA private key to Git
- Use expired certificates

### Resource Limits

✅ **DO:**
```yaml
gateway:
  memory_request: 256Mi
  memory_limit: 512Mi      # 2x request for burst capacity
  cpu_request: 100m
  cpu_limit: 500m          # Allow bursting
```

❌ **DON'T:**
```yaml
gateway:
  # Missing resource limits = unbounded usage
  # OR
  memory_limit: 256Mi      # Too tight, may OOM
```

### High Availability

✅ **DO:**
```yaml
gateway:
  replicas: 2              # Multiple replicas
  service_type: LoadBalancer

plugins:
  - name: CriticalPlugin
    replicas: 2            # HA for critical plugins
```

❌ **DON'T:**
```yaml
gateway:
  replicas: 1              # Single point of failure in production
```

---

## Troubleshooting

### Build Issues

**Problem: Git clone fails**
```
Error: Failed to clone repository
```

**Solution:**
- Check `repo` URL is correct
- Verify Git credentials/SSH keys
- Ensure network connectivity
- For private repos, configure Git auth

---

**Problem: Docker build fails**
```
Error: Build failed for plugin MyPlugin
```

**Solution:**
1. Check `context` and `containerfile` paths
2. Verify Containerfile syntax
3. Review plugin repository structure
4. Try building manually:
   ```bash
   git clone <repo>
   cd <context>
   docker build -f <containerfile> .
   ```

---

### Deployment Issues

**Problem: Pod/container fails to start**
```
Error: CrashLoopBackOff
```

**Solution:**
1. Check logs:
   ```bash
   # Kubernetes
   kubectl logs -n <namespace> <pod-name>

   # Docker Compose
   docker-compose -f deploy/docker-compose.yaml logs <service>
   ```
2. Verify environment variables in `deploy/env/`
3. Check resource limits (may be too low)
4. Verify image was built/pulled correctly

---

**Problem: mTLS connection fails**
```
Error: SSL certificate verification failed
```

**Solution:**
1. Regenerate certificates:
   ```bash
   rm -rf certs/
   cforge gateway certs deploy.yaml
   ```
2. Redeploy to distribute new certs:
   ```bash
   cforge gateway deploy deploy.yaml --skip-build --skip-certs
   ```
3. Check certificate expiry:
   ```bash
   openssl x509 -in certs/mcp/gateway/client.crt -noout -dates
   ```

---

### Verification Issues

**Problem: Deployment verification timeout**
```
Error: Verification failed: timeout waiting for deployment
```

**Solution:**
1. Increase timeout:
   ```bash
   cforge gateway verify deploy.yaml --timeout 600
   ```
2. Check pod/container status manually
3. Review resource availability (CPU/memory)
4. Check for image pull errors

---

## FAQ

**Q: Can I use pre-built images instead of building from source?**

A: Yes! Just specify `image` instead of `repo`:
```yaml
plugins:
  - name: MyPlugin
    image: myorg/myplugin:v1.0.0
```

---

**Q: How do I update a plugin to a new version?**

A: Update the `ref` and redeploy:
```yaml
plugins:
  - name: MyPlugin
    repo: https://github.com/org/repo.git
    ref: v2.0.0  # ← Update version
```

Then:
```bash
cforge gateway build deploy.yaml --plugin MyPlugin --no-cache
cforge gateway deploy deploy.yaml --skip-certs
```

---

**Q: Can I deploy only the gateway without plugins?**

A: Yes, just omit the `plugins` section or use an empty array:
```yaml
plugins: []
```

---

**Q: How do I add custom environment variables?**

A: Two ways:

**1. In YAML (committed to Git):**
```yaml
gateway:
  env_vars:
    CUSTOM_VAR: value
```

**2. In .env file (not committed):**
```bash
# deploy/env/.env.gateway
CUSTOM_VAR=value
```

---

**Q: Can I use cforge in a CI/CD pipeline?**

A: Absolutely! See [CI/CD Integration](#cicd-integration) section above.

---

**Q: How do I switch between Dagger and plain Python modes?**

A:
```bash
# Plain Python mode (default)
cforge gateway deploy deploy.yaml

# Dagger mode (opt-in, requires dagger-io package)
cforge gateway --dagger deploy deploy.yaml
```

**Note**: Dagger mode requires installing the `dagger-io` package and will auto-download the Dagger CLI (~100MB) on first use

---

**Q: Where are the generated manifests stored?**

A: Default: `deploy/` directory
- `deploy/docker-compose.yaml` (Compose mode)
- `deploy/manifests/` (Kubernetes mode)

Custom location:
```bash
cforge gateway deploy deploy.yaml --output-dir ./my-deploy
```

---

**Q: How do I access the gateway after deployment?**

A:
- **Docker Compose**: `http://localhost:<host_port>` (default: 4444)
- **Kubernetes LoadBalancer**: Get external IP:
  ```bash
  kubectl get svc -n <namespace> mcp-gateway
  ```
- **Kubernetes ClusterIP**: Port-forward:
  ```bash
  kubectl port-forward -n <namespace> svc/mcp-gateway 4444:4444
  ```

---

## Additional Resources

- **Main Documentation**: [ContextForge Documentation](/)
- **Plugin Development**: [Plugin Framework Guide](/plugins/framework)
- **mTLS Setup**: [mTLS Configuration Guide](/using/plugins/mtls)
- **Example Configs**: [`examples/deployment-configs/`](https://github.com/terylt/mcp-context-forge/tree/main/examples/deployment-configs)
- **Source Code**: [`mcpgateway/tools/builder/`](https://github.com/terylt/mcp-context-forge/tree/main/mcpgateway/tools/builder)

---

## Getting Help

If you encounter issues:

1. **Check logs**: Review detailed error messages
2. **Validate config**: Run `cforge gateway validate deploy.yaml`
3. **Dry-run**: Test with `cforge gateway deploy deploy.yaml --dry-run`
4. **Verbose mode**: Use `cforge gateway -v <command>` for detailed output
5. **Debug mode**: Set `export MCP_DEBUG=1` for stack traces
6. **GitHub Issues**: [Report bugs and request features](https://github.com/terylt/mcp-context-forge/issues)

---
