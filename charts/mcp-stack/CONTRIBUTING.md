# Contributing to MCP Stack Helm Chart

Thank you for your interest in contributing to the MCP Stack Helm Chart! This document provides guidelines and information for contributors.

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Setup](#development-setup)
4. [Chart Development Guidelines](#chart-development-guidelines)
5. [Testing](#testing)
6. [Submitting Changes](#submitting-changes)
7. [Release Process](#release-process)
8. [Getting Help](#getting-help)

## Code of Conduct

This project follows the [IBM Code of Conduct](https://github.com/IBM/mcp-context-forge/blob/main/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- **Kubernetes cluster** (v1.21+) - Minikube, kind, or cloud-managed
- **Helm 3.x** - [Installation guide](https://helm.sh/docs/intro/install/)
- **kubectl** - Configured to access your cluster
- **Git** - For version control

### Repository Structure

```
charts/mcp-stack/
├── Chart.yaml              # Chart metadata
├── values.yaml             # Default configuration values
├── values.schema.json      # JSON schema for values validation
├── templates/              # Kubernetes manifest templates
│   ├── _helpers.tpl        # Template helpers
│   ├── deployment-*.yaml   # Application deployments
│   ├── service-*.yaml      # Kubernetes services
│   ├── configmap-*.yaml    # Configuration maps
│   ├── secret-*.yaml       # Secret templates
│   ├── ingress.yaml        # Ingress configuration
│   ├── hpa-*.yaml          # Horizontal Pod Autoscaler
│   ├── job-migration.yaml  # Database migration job
│   └── NOTES.txt           # Installation notes
├── README.md               # Chart documentation
├── CHANGELOG.md            # Chart changelog
├── CONTRIBUTING.md         # This file
└── .helmignore             # Files to ignore when packaging
```

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR-USERNAME/mcp-context-forge.git
cd mcp-context-forge/charts/mcp-stack
```

### 2. Set Up Development Environment

```bash
# Add the upstream remote
git remote add upstream https://github.com/IBM/mcp-context-forge.git

# Create a development branch
git checkout -b feature/your-feature-name

# Install chart dependencies (if any)
helm dependency update
```

### 3. Make Your Changes

Edit the chart files as needed. Common changes include:

- **Templates**: Modify Kubernetes manifests in `templates/`
- **Values**: Update default values in `values.yaml`
- **Schema**: Update validation in `values.schema.json`
- **Documentation**: Update `README.md` and template comments

## Chart Development Guidelines

### Helm Chart Best Practices

1. **Follow Helm conventions**:
   - Use lowercase names and hyphens (kebab-case)
   - Prefix template names with chart name
   - Use meaningful labels and annotations

2. **Template Guidelines**:
   - Use `_helpers.tpl` for reusable template snippets
   - Include proper indentation and comments
   - Use `{{- }}` for whitespace control
   - Quote string values in templates

3. **Values Structure**:
   - Group related settings logically
   - Use nested objects for complex configurations
   - Provide sensible defaults
   - Document all values with comments

4. **Resource Management**:
   - Always set resource requests and limits
   - Use appropriate probe configurations
   - Include security contexts where needed
   - Follow least-privilege principle

### Naming Conventions

- **Resources**: Use `{{ include "mcp-stack.fullname" . }}-<component>`
- **Labels**: Use standard Kubernetes labels via `{{ include "mcp-stack.labels" . }}`
- **Selectors**: Match deployment labels consistently
- **Ports**: Use descriptive port names (`http`, `postgres`, `redis`)

### Documentation Standards

- **Inline Comments**: Explain complex template logic
- **values.yaml**: Comment all configuration options
- **README.md**: Keep installation/configuration docs current
- **NOTES.txt**: Provide helpful post-installation guidance

## Testing

### 1. Lint the Chart

```bash
# Run Helm linting
helm lint .

# Check for common issues
helm template . | kubectl apply --dry-run=client -f -
```

### 2. Template Testing

```bash
# Test template rendering
helm template mcp-stack . -f values.yaml

# Test with custom values
helm template mcp-stack . -f test-values.yaml

# Validate against schema
helm template mcp-stack . --validate
```

### 3. Installation Testing

```bash
# Test installation
helm install mcp-stack-test . --namespace test --create-namespace --dry-run

# Test upgrade
helm upgrade mcp-stack-test . --namespace test --dry-run

# Test with different configurations
helm install mcp-stack-test . -f my-values.yaml --namespace test --create-namespace
```

### 4. Integration Testing

```bash
# Deploy to test cluster
helm install mcp-stack-test . --namespace test --create-namespace --wait

# Verify deployment
kubectl get all -n test
helm test mcp-stack-test -n test  # If test hooks are defined

# Clean up
helm uninstall mcp-stack-test -n test
kubectl delete namespace test
```

### 5. Values Schema Testing

```bash
# Test schema validation
helm lint . --strict
helm template . --values invalid-values.yaml  # Should fail with schema errors
```

## Submitting Changes

### 1. Pre-submission Checklist

- [ ] Chart passes `helm lint` without warnings
- [ ] All templates render correctly with default values
- [ ] `values.schema.json` is updated if values structure changed
- [ ] Documentation is updated (README.md, comments)
- [ ] Chart version is bumped appropriately (see [Versioning](#versioning))
- [ ] CHANGELOG.md is updated with your changes
- [ ] Changes are tested on a real Kubernetes cluster

### 2. Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
type(scope): description

[optional body]

[optional footer]
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

**Examples**:
```
feat(templates): add horizontal pod autoscaler support
fix(ingress): resolve path routing issues
docs(readme): update installation instructions
```

### 3. Pull Request Process

1. **Create Pull Request**:
   - Use a descriptive title
   - Reference related issues
   - Fill out the PR template completely

2. **PR Requirements**:
   - Pass all CI checks
   - Include tests for new functionality
   - Maintain or improve chart documentation
   - Follow chart versioning guidelines

3. **Review Process**:
   - Address reviewer feedback promptly
   - Keep PR focused and reasonably sized
   - Squash commits if requested

## Release Process

### Versioning

This chart follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Incompatible API changes
- **MINOR** (0.X.0): Backwards-compatible functionality additions
- **PATCH** (0.0.X): Backwards-compatible bug fixes

### Chart Version Updates

When making changes:

1. **Patch** (0.2.1): Bug fixes, documentation updates
2. **Minor** (0.3.0): New features, new configuration options
3. **Major** (1.0.0): Breaking changes, major refactoring

Update both `version` and `appVersion` in `Chart.yaml`:

```yaml
version: 0.4.0          # Chart version
appVersion: "0.4.0"     # Application version
```

### Release Checklist

1. Update `Chart.yaml` version
2. Update `CHANGELOG.md` with new version
3. Test thoroughly on multiple environments
4. Create release PR
5. Tag release after merge
6. Package and publish chart

## Getting Help

### Resources

- **Documentation**: [MCP Context Forge Docs](https://ibm.github.io/mcp-context-forge/)
- **Helm Documentation**: [https://helm.sh/docs/](https://helm.sh/docs/)
- **Kubernetes Documentation**: [https://kubernetes.io/docs/](https://kubernetes.io/docs/)

### Support Channels

- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Discussions**: [GitHub Discussions](https://github.com/IBM/mcp-context-forge/discussions)
- **Main Project**: [MCP Context Forge](https://github.com/IBM/mcp-context-forge)

### Common Issues

1. **Template Errors**: Check indentation and YAML syntax
2. **Values Validation**: Ensure values match schema
3. **Resource Conflicts**: Use unique names with fullname template
4. **Permission Issues**: Check RBAC settings and service accounts

## Thank You

Your contributions help make the MCP ContextForge Stack easier to deploy and manage for everyone. We appreciate your time and effort in improving this project!

---

*This document is based on the [MCP Context Forge](https://github.com/IBM/mcp-context-forge) project and follows established open-source contribution practices.*
