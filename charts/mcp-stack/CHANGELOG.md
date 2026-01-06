# Changelog

All notable changes to the MCP Stack Helm Chart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [0.9.1] - 2025-12-03

### Added
* **Helm Hook Support for Migration Job** - enable recreation of the migration Job on every deployment
  - helm.sh/hook: pre-install,pre-upgrade — ensures the migration Job runs automatically during installs and upgrades
  - helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded — removes old migration Jobs to prevent immutable field errors
  - Eliminates upgrade failures caused by changes to spec.template in Kubernetes Jobs

### Changed
* **Chart version** - Bumped to 0.9.1 for migration job fix

## [0.9.0] - 2025-11-05

### Added
* **Ed25519 Certificate Signing** - Digital certificate signing and verification using Ed25519 cryptographic signatures:
  - `ENABLE_ED25519_SIGNING` - Enable/disable Ed25519 certificate signing (default: "false")
  - `ED25519_PRIVATE_KEY` - Current Ed25519 private key for signing (base64-encoded)
  - `PREV_ED25519_PRIVATE_KEY` - Previous Ed25519 private key for graceful key rotation (base64-encoded)
  - Built-in key generation utility at `mcpgateway/utils/generate_keys.py`
  - Zero-downtime key rotation support with automatic fallback verification
  - Complete documentation with Kubernetes examples and External Secrets integration
  - Ensures certificate authenticity and prevents tampering using RFC 8032 algorithm

### Changed
* **Chart version** - Bumped to 0.9.0 for Ed25519 certificate signing support

## [0.6.1] - 2025-09-01

### Added
* **Enhanced Authentication Configuration** - Comprehensive email-based authentication support with new environment variables:
  - Email authentication: `EMAIL_AUTH_ENABLED`, `PLATFORM_ADMIN_EMAIL/PASSWORD/FULL_NAME`
  - Password policies: `PASSWORD_MIN_LENGTH`, `PASSWORD_REQUIRE_*` settings
  - Account lockout: `MAX_FAILED_LOGIN_ATTEMPTS`, `ACCOUNT_LOCKOUT_DURATION_MINUTES`
  - Argon2id hashing: `ARGON2ID_TIME_COST/MEMORY_COST/PARALLELISM`
* **SSO Integration** - Single Sign-On support for multiple providers:
  - GitHub OAuth: `SSO_GITHUB_*` configuration options
  - Google OAuth: `SSO_GOOGLE_*` configuration options
  - IBM Security Verify: `SSO_IBM_VERIFY_*` configuration options
  - Okta OIDC: `SSO_OKTA_*` configuration options
  - SSO policies: `SSO_AUTO_CREATE_USERS`, `SSO_TRUSTED_DOMAINS`, `SSO_REQUIRE_ADMIN_APPROVAL`
* **A2A (Agent-to-Agent) Features** - Complete A2A agent configuration:
  - `MCPGATEWAY_A2A_ENABLED/MAX_AGENTS/DEFAULT_TIMEOUT/MAX_RETRIES/METRICS_ENABLED`
* **Personal Teams Management** - Team collaboration features:
  - `AUTO_CREATE_PERSONAL_TEAMS`, `PERSONAL_TEAM_PREFIX`
  - `MAX_TEAMS_PER_USER/MEMBERS_PER_TEAM`, `INVITATION_EXPIRY_DAYS`
* **Enhanced Logging Configuration** - Extended logging capabilities:
  - File logging: `LOG_TO_FILE/FILEMODE/FILE/FOLDER`
  - Rotation: `LOG_ROTATION_ENABLED/MAX_SIZE_MB/BACKUP_COUNT`
  - Buffer management: `LOG_BUFFER_SIZE_MB`
* **OpenTelemetry Observability** - Comprehensive tracing and metrics:
  - OTLP configuration: `OTEL_EXPORTER_OTLP_ENDPOINT/PROTOCOL/HEADERS`
  - Alternative backends: `OTEL_EXPORTER_JAEGER/ZIPKIN_ENDPOINT`
  - Performance tuning: `OTEL_BSP_*` batch span processor settings
* **Well-Known URI Support** - RFC compliance for discovery:
  - `WELL_KNOWN_ENABLED/ROBOTS_TXT/SECURITY_TXT/CUSTOM_FILES/CACHE_MAX_AGE`
* **Plugin Framework Configuration** - Plugin system support:
  - `PLUGINS_ENABLED/CONFIG_FILE/CLI_COMPLETION/CLI_MARKUP_MODE`
* **Enhanced Security Features** - Additional security configurations:
  - MCP client auth: `MCP_CLIENT_AUTH_ENABLED/TRUST_PROXY_AUTH/PROXY_USER_HEADER`
  - OAuth settings: `OAUTH_REQUEST_TIMEOUT/MAX_RETRIES`
  - Header passthrough: `ENABLE_HEADER_PASSTHROUGH/DEFAULT_PASSTHROUGH_HEADERS`
  - JWT enhancements: `JWT_AUDIENCE/ISSUER`, `REQUIRE_TOKEN_EXPIRATION`
* **Additional Configuration** - Miscellaneous enhancements:
  - SSE keepalive: `SSE_KEEPALIVE_ENABLED/INTERVAL`
  - Tool routing: `GATEWAY_TOOL_NAME_SEPARATOR`
  - Health checks: `GATEWAY_VALIDATION_TIMEOUT`
  - HTTP retry: `RETRY_MAX_ATTEMPTS/BASE_DELAY/MAX_DELAY/JITTER_MAX`
  - Bulk import: `MCPGATEWAY_BULK_IMPORT_ENABLED/MAX_TOOLS/RATE_LIMIT`

### Changed
* **Chart version** - Bumped to 0.6.1 to reflect extensive configuration additions
* **Configuration organization** - Improved categorization and documentation of environment variables

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
