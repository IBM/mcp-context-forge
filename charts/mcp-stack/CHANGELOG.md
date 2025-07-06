# Changelog

All notable changes to the MCP Stack Helm Chart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [0.3.0] - 2025-07-08 (pending)

### Added
* **values.schema.json** - Complete JSON schema validation for all chart values with proper validation rules, descriptions, and type checking
* **NetworkPolicy support** - Optional network policies for pod-to-pod communication restrictions
* **ServiceMonitor CRD** - Optional Prometheus ServiceMonitor for metrics collection
* **Pod Security Standards** - Enhanced security contexts following Kubernetes Pod Security Standards
* **Multi-architecture support** - Chart now supports ARM64 and AMD64 architectures
* **Backup and restore** - Optional backup job for PostgreSQL data with configurable retention

### Changed
* **Improved resource management** - Better default resource requests/limits based on production usage patterns
* **Enhanced probe configuration** - More flexible health check configuration with support for custom headers and paths
* **Streamlined template structure** - Consolidated related templates and improved template helper functions
* **Better secret management** - Support for external secret management systems (External Secrets Operator)

### Fixed
* **Ingress path handling** - Fixed path routing issues when deploying under subpaths
* **PVC storage class** - Resolved issues with dynamic storage class provisioning
* **Secret references** - Fixed circular dependency issues in secret template generation


## [0.2.1] - 2025-07-03 (pending)

### Added
* **Horizontal Pod Autoscaler** - Full HPA support for mcpgateway with CPU and memory metrics
* **Fast Time Server** - Optional high-performance Go-based time server deployment
* **Advanced ingress configuration** - Support for multiple ingress controllers and path-based routing
* **Migration job** - Automated database migration job using Alembic with proper startup dependencies
* **Comprehensive health checks** - Detailed readiness and liveness probes for all components

### Changed
* **Enhanced NOTES.txt** - Comprehensive post-installation guidance with troubleshooting commands
* **Improved resource defaults** - Better resource allocation based on component requirements
* **Simplified configuration** - Consolidated environment variable management via ConfigMaps and Secrets

### Fixed
* **Service selector consistency** - Fixed label selectors across all service templates
* **Template rendering** - Resolved issues with conditional template rendering
* **Secret name generation** - Fixed helper template for PostgreSQL secret name resolution


## [0.2.0] - 2025-06-24

### Added
* **Complete Helm chart** - Full-featured Helm chart for MCP Stack deployment
* **Multi-service architecture** - Deploy MCP Gateway, PostgreSQL, Redis, PgAdmin, and Redis Commander
* **Configurable deployments** - Comprehensive values.yaml with ~100 configuration options
* **Template helpers** - Reusable template functions for consistent naming and labeling
* **Ingress support** - NGINX ingress controller support with SSL termination
* **Persistent storage** - PostgreSQL persistent volume claims with configurable storage classes
* **Resource management** - CPU and memory limits/requests for all components
* **Health monitoring** - Readiness and liveness probes for reliable deployments

### Infrastructure
* **Container registry** - Chart packages published to GitHub Container Registry
* **Documentation** - Comprehensive README with installation and configuration guide
* **Template validation** - Helm lint and template testing in CI/CD pipeline
* **Multi-environment support** - Development, staging, and production value configurations

### Components
* **MCP Gateway** - FastAPI-based gateway with configurable replicas and scaling
* **PostgreSQL 17** - Production-ready database with backup and recovery options
* **Redis** - In-memory cache for sessions and temporary data
* **PgAdmin** - Web-based PostgreSQL administration interface
* **Redis Commander** - Web-based Redis management interface
* **Migration Jobs** - Automated database schema migrations with Alembic

### Security
* **RBAC support** - Kubernetes role-based access control configuration
* **Secret management** - Secure handling of passwords, JWT keys, and connection strings
* **Network policies** - Optional pod-to-pod communication restrictions
* **Security contexts** - Non-root containers with proper security settings

### Configuration
* **Environment-specific values** - Separate configuration for different deployment environments
* **External dependencies** - Support for external PostgreSQL and Redis instances
* **Scaling configuration** - Horizontal pod autoscaling and resource optimization
* **Monitoring integration** - Prometheus metrics and health check endpoints

### Changed
* **Naming convention** - Consistent resource naming using Helm template helpers
* **Label management** - Standardized Kubernetes labels across all resources
* **Documentation structure** - Improved README with troubleshooting and best practices

### Fixed
* **Template consistency** - Resolved naming conflicts and selector mismatches
* **Resource dependencies** - Fixed startup order and dependency management
* **Configuration validation** - Proper validation of required and optional values

---

## Release Notes

### Upgrading from 0.1.x to 0.2.x

**Breaking Changes:**
- Chart structure completely redesigned
- New values.yaml format with nested configuration
- Resource naming convention changed to use template helpers
- Ingress configuration restructured

**Migration Steps:**
1. Export existing configuration: `helm get values <release-name> > old-values.yaml`
2. Update values to new format (see README.md for examples)
3. Test upgrade in non-production environment
4. Perform rolling upgrade: `helm upgrade <release-name> mcp-stack -f new-values.yaml`

### Compatibility Matrix

| Chart Version | App Version | Kubernetes | Helm |
|---------------|-------------|------------|------|
| 0.3.x         | 0.3.x       | 1.23+      | 3.8+ |
| 0.2.x         | 0.2.x       | 1.21+      | 3.7+ |
| 0.1.x         | 0.1.x       | 1.19+      | 3.5+ |

### Support Policy

- **Current version (0.3.x)**: Full support with new features and bug fixes
- **Previous version (0.2.x)**: Security updates and critical bug fixes only
- **Older versions (0.1.x)**: Best effort support, upgrade recommended

---

### Release Links

* **Chart Repository**: [OCI Registry](https://github.com/IBM/mcp-context-forge/pkgs/container/mcp-context-forge%2Fmcp-stack)
* **Documentation**: [Helm Deployment Guide](https://ibm.github.io/mcp-context-forge/deployment/helm/)
* **Source Code**: [GitHub Repository](https://github.com/IBM/mcp-context-forge/tree/main/charts/mcp-stack)
* **Issue Tracker**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
