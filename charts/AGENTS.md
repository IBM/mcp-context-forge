# charts/AGENTS.md

Helm chart development guidance for AI coding assistants.

## Chart Structure

```
charts/
├── README.md
└── mcp-stack/              # Main Helm chart
    ├── Chart.yaml          # Chart metadata
    ├── values.yaml         # Default configuration
    ├── values.schema.json  # JSON Schema for validation
    ├── Makefile            # Developer automation
    ├── README.md           # Generated chart docs
    ├── CHANGELOG.md        # Version history
    ├── CONTRIBUTING.md     # Contribution guidelines
    └── templates/          # Kubernetes manifests
        ├── _helpers.tpl    # Template helpers
        ├── deployment-*.yaml
        ├── service-*.yaml
        ├── configmap-*.yaml
        ├── secret-*.yaml
        ├── ingress.yaml
        ├── hpa-*.yaml
        └── NOTES.txt
```

## Prerequisites

- `helm` (3.14+)
- `kubectl` with configured context
- Optional: `helm-docs`, `yamllint`, `kubeval`, `ajv-cli`, `cosign`

## Quick Commands

From `charts/mcp-stack/`:

```bash
# Info
make info                     # Print chart/app versions
make version                  # Print chart version

# Lint & Validate
make lint                     # helm lint --strict
make lint-yaml                # yamllint (if available)
make lint-values              # Validate values against schema
make validate-all             # Run all lint steps

# Template & Dry-run
make test-template            # Render templates → tmp/rendered.yaml
make test-template-values     # Render with my-values.yaml
make test-dry-run             # helm install --dry-run --debug
make test-kubeval             # Validate manifests with kubeval
make test-all                 # Template + dry-run + kubeval

# Install/Upgrade
make install                  # Install with defaults
make install-dev              # Install with my-values.yaml
make upgrade                  # Upgrade release
make upgrade-dev              # Upgrade with my-values.yaml
make uninstall                # Uninstall and wait

# Debug
make status                   # Release status
make history                  # Release history
make rollback                 # Rollback release
make debug                    # Context, releases, resources
make describe                 # Describe chart resources
make logs                     # Show pod logs
make logs-follow              # Follow pod logs
make port-forward             # Forward localhost:4444 → service:80
make shell                    # Interactive shell into gateway

# Package & Registry
make package                  # Package to dist/
make push                     # Push to OCI registry
make sign                     # Sign with cosign

# Docs & Schema
make docs                     # Generate README via helm-docs
make schema                   # Generate values.schema.json
make schema-validate          # Validate values against schema
```

## Common Workflows

### Local Validation
```bash
cd charts/mcp-stack
make validate-all
make test-template
make test-dry-run  # Optional
```

### First-time Install
```bash
NAMESPACE=mcp-dev RELEASE_NAME=mcp-dev make install
# Or with custom values:
# Create my-values.yaml, then:
make install-dev
```

### Upgrade
```bash
make upgrade-dev  # Uses my-values.yaml if present
```

### Debug
```bash
make status
make logs
make port-forward  # Then browse http://localhost:4444
```

## Values Override Example

Create `my-values.yaml`:

```yaml
mcpContextForge:
  image:
    tag: "latest"
    pullPolicy: IfNotPresent
  ingress:
    enabled: true
    className: nginx
    host: gateway.local
  config:
    DEV_MODE: "true"
    RELOAD: "false"
  secret:
    BASIC_AUTH_USER: admin
    BASIC_AUTH_PASSWORD: changeme
    JWT_SECRET_KEY: my-test-key

postgres:
  enabled: true
  credentials:
    user: admin
    password: test123
  persistence:
    storageClassName: standard
    size: 5Gi

redis:
  enabled: true
```

## Security

- Use `mcpContextForge.secret.*` for auth settings in dev
- Prefer external `Secret` objects for production
- Configure TLS at ingress or service mesh
- Never commit secrets to values files

## CI/CD

```bash
# In pipelines
make lint
make validate-all

# On tagged releases
make package push

# Optional signing
make sign
```

## Troubleshooting

```bash
# Inspect applied values
helm get values <release> -n <namespace>

# Inspect manifests
helm get manifest <release> -n <namespace>

# Check events
kubectl describe pod <pod> -n <namespace>
kubectl describe ingress <ingress> -n <namespace>
```

## Key Files

- `Chart.yaml` - Chart metadata, versions, dependencies
- `values.yaml` - All configurable values with defaults
- `values.schema.json` - JSON Schema for values validation
- `templates/_helpers.tpl` - Reusable template functions
- `Makefile` - Developer automation commands
