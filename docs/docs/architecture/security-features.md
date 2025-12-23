# MCP Gateway Security Features

**Current Version: 0.9.0 (Beta)** — The gateway ships with the controls described below. Everything listed here is present in the codebase today; future roadmap items live in `docs/docs/architecture/roadmap.md`.

## Security Posture Overview

- **Authentication on by default.** `AUTH_REQUIRED=true` ensures every API, SSE, and Admin UI route requires an authenticated session unless you explicitly opt out for local testing.
- **Secure defaults for operators.** The service binds to `127.0.0.1` unless overridden, `MCPGATEWAY_UI_ENABLED=false` and `MCPGATEWAY_ADMIN_API_ENABLED=false` keep the Admin UI/API offline in production, and cookies are hardened with `SECURE_COOKIES=true`, HttpOnly, and `SameSite=lax`.
- **Environment-aware CORS & cookies.** `ENVIRONMENT` and `APP_DOMAIN` drive cors/origin policy, switching between a localhost allowlist in development and strict origin checks in production (`mcpgateway/middleware/security_headers.py`).
- **Security posture reporting.** Startup invokes `validate_security_configuration()` (`mcpgateway/main.py`) which consumes `settings.get_security_status()` to log weak secrets, missing auth, or insecure federation setups. Setting `REQUIRE_STRONG_SECRETS=true` upgrades warnings to hard failures.

## Authentication & Identity

### Core Gateway Authentication

- **HTTP Basic Auth** protects the Admin UI and optionally the OpenAPI docs (`DOCS_ALLOW_BASIC_AUTH=true`). Credentials are defined by `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`, and the config endpoint masks secrets (`mcpgateway/admin.py`).
- **JWT bearer tokens** are required for API access and MCP transports when `MCP_CLIENT_AUTH_ENABLED=true` (default). For reverse proxies you can opt into `TRUST_PROXY_AUTH=true` and provide the authenticated identity through `PROXY_USER_HEADER`.
- **Token issuance tooling.** `python -m mcpgateway.utils.create_jwt_token` produces gateway-signed tokens for automation. The helper respects configured expiry, issuer, and audience claims.

### JWT Token Management

- **Algorithm agility.** `mcpgateway/utils/jwt_config_helper.py` supports HS256/384/512, RS256/384/512, and ES256/384/512. For asymmetric algorithms the helper validates key paths on startup and reads the PEM material securely.
- **Secret validation.** The Pydantic field validator (`Settings.validate_secrets`) logs warnings for default or low-entropy secrets, and when `REQUIRE_STRONG_SECRETS=true` startup fails if critical values remain weak.
- **Revocation and audit.** API tokens are modelled as JWTs with per-token `jti` identifiers. Revocations (`TokenRevocation`) and usage logs (`TokenUsageLog`) persist to the database, enabling immediate invalidation and monitoring.

### Email-Based Authentication

- **Argon2id password hashing.** `EmailAuthService` hashes credentials with configurable `ARGON2ID_TIME_COST`, `ARGON2ID_MEMORY_COST`, and `ARGON2ID_PARALLELISM`.
- **Password policy controls.** Minimum length and complexity are driven by `PASSWORD_MIN_LENGTH` and related flags. Attempts that fail policy raise `PasswordValidationError`.
- **Account lockout & auditing.** `MAX_FAILED_LOGIN_ATTEMPTS` and `ACCOUNT_LOCKOUT_DURATION_MINUTES` enforce lockouts at the ORM layer (`EmailUser.increment_failed_attempts`). Every login, registration, or password change emits an `EmailAuthEvent` with IP and user-agent metadata for investigation.
- **Admin bootstrap.** The first superuser is provisioned from `PLATFORM_ADMIN_EMAIL`/`PLATFORM_ADMIN_PASSWORD`, enabling secure initial access even when SSO is not configured.

### Token Catalog & API Keys

- **Hashed personal and team tokens.** `TokenCatalogService` stores only SHA-256 hashes (`token_hash`) of issued tokens (`EmailApiToken`) and keeps the raw secret in memory just long enough to present it once.
- **Fine-grained scopes.** Tokens can be confined to a server, a permission list, IP CIDRs, and time-of-day or usage quotas via `TokenScope`.
- **Usage analytics.** Every request records method, endpoint, IP, user-agent, latency, and block reason in `TokenUsageLog`, supporting anomaly detection.
- **Immediate revocation.** `TokenRevocation` entries are enforced before gateway execution, guaranteeing revoked tokens cannot be replayed.

### OAuth & SSO Federation

- **Multi-provider SSO.** `mcpgateway/services/sso_service.py` supports GitHub, Google, IBM Security Verify, Microsoft Entra ID, Okta, Keycloak, and generic OIDC providers. Secrets are encrypted with a Fernet key derived from `AUTH_ENCRYPTION_SECRET`.
- **Security-state tracking.** `SSOAuthSession` persists OAuth state tokens, PKCE `code_verifier`, and nonces to prevent CSRF and replay attacks.
- **Per-user OAuth vault.** `TokenStorageService` encrypts access/refresh tokens using AES-GCM (`oauth_encryption.py`) and keys them by both gateway and gateway user to prevent cross-tenant leakage.
- **Dynamic Client Registration (DCR).** `DcrService` discovers OAuth metadata (RFC 8414), honours issuer allowlists (`DCR_ALLOWED_ISSUERS`), registers clients, and encrypts the resulting client secrets and registration access tokens before storing them (`RegisteredOAuthClient`).
- **Tool credential encryption.** The same `AUTH_ENCRYPTION_SECRET` powers `services_auth.encode_auth()` to store upstream tool auth blobs as AES-GCM tokens inside the database.

## Authorization & Access Control

- **Role-Based Access Control (RBAC).** `PermissionService` and `RoleService` implement global/team/personal scopes with caching, inheritance, and audit logging (`PermissionAuditLog`). Admin bypass is explicit, and permission checks default to deny on error.
- **Multi-tenancy primitives.** Teams, invites, and memberships (`EmailTeam`, `EmailTeamMember`, `TeamInvitationService`) enforce owner-only invitations, configurable expiry, and per-team quotas (`MAX_TEAMS_PER_USER`, `MAX_MEMBERS_PER_TEAM`). Personal teams can be auto-created with `AUTO_CREATE_PERSONAL_TEAMS=true`.
- **Resource visibility.** Tools, prompts, resources, and gateways include a `visibility` flag (private/team/public) that PermissionService respects when resolving access.
- **Feature gating.** Administrative capabilities stay off unless you opt in: `MCPGATEWAY_UI_ENABLED`, `MCPGATEWAY_ADMIN_API_ENABLED`, `MCPGATEWAY_BULK_IMPORT_ENABLED`, `MCPGATEWAY_CATALOG_ENABLED`, and `MCPGATEWAY_A2A_ENABLED` all default to safe values.
- **Scoped API credentials.** Tokens can be restricted to individual virtual servers, explicit permission strings, and IP ranges; blocked requests are captured via `TokenUsageLog.blocked`.
- **Header passthrough controls.** `utils/passthrough_headers.py` keeps passthrough disabled unless `ENABLE_HEADER_PASSTHROUGH=true`, sanitises header names/values, rejects conflicting `Authorization` headers, and lets clients safely supply `X-Upstream-Authorization` for upstream delegation.
- **Policy-as-code plugins.** The plugin framework powers deny/allow decisions before and after prompt/tool/resource execution. Security-focused plugins include `deny_filter`, `pii_filter`, `content_moderation`, `output_length_guard`, `schema_guard`, `sql_sanitizer`, `secrets_detection`, `rate_limiter`, `url_reputation`, `vault`, `watchdog`, and the optional external OPA integration for Rego policies (`plugins/external/opa`).
- **Federation safeguards.** Startup validation warns when `federation_enabled` is combined with unauthenticated deployments, and federation forwarding honours global rate limits to protect upstream peers.

## Data Protection & Secret Handling

- **AES-GCM secret vault.** `mcpgateway/utils/services_auth.py` derives a 32-byte key from `AUTH_ENCRYPTION_SECRET` and encrypts tool/resource credentials, ensuring secrets stored in the database or logs are opaque without the passphrase.
- **Encrypted OAuth/SSO secrets.** The SSO service and DCR service wrap client secrets and registration tokens with Fernet and only decrypt them on demand.
- **Cookie security helpers.** `utils/security_cookies.py` sets auth/session cookies with HttpOnly, `SameSite`, and `secure` flags (enforced for production or when `SECURE_COOKIES=true`) and provides symmetric deletion helpers to avoid stale cookies.
- **Security headers middleware.** `SecurityHeadersMiddleware` adds CSP, X-Frame-Options (default `DENY`), X-Content-Type-Options (`nosniff`), X-Download-Options (`noopen`), Referrer-Policy, HSTS (when HTTPS is detected), and strips `Server`/`X-Powered-By` headers.
- **TLS ready.** `make certs` creates local certificates, `make serve-ssl` runs Gunicorn with TLS, and the client defaults keep `SKIP_SSL_VERIFY=false`. The container images trust RHEL certificate bundles for outbound TLS.
- **Support bundle sanitisation.** `SupportBundleService` redacts passwords, tokens, secrets, and bearer values before writing diagnostic ZIPs. Patterns cover API keys, JWTs, Authorization headers, and database URLs.
- **Configuration masking.** `/admin/config/settings` hides sensitive keys using the `mask_sensitive` helper to prevent secret exfiltration through the Admin UI/API.
- **Hardened containers.** `Containerfile.lite` builds on patched RHEL UBI 10 ↦ scratch, installs dependencies in a venv, strips debugging symbols, removes package managers, deletes setuid/setgid binaries, creates a non-root `UID 1001`, preserves the RPM DB for scanning, and sets security-oriented runtime env vars.
- **Logging controls.** `LoggingService` centralises formatting with JSON or text output, supports log rotation, and the support bundle honours size/line caps to avoid log leakage.

## Input Validation & Guardrails

- **SecurityValidator centralises sanitisation.** `mcpgateway/validators.py` enforces length limits, safe character sets, scheme allowlists, JSON depth (`MAX_JSON_DEPTH`), and detects dangerous HTML/JS patterns across every Pydantic schema.
- **Schema-driven enforcement.** `mcpgateway/schemas.py` applies the validator to tool names, URLs, resource URIs, descriptions, prompts, and JSON payloads, trimming or rejecting unsafe values before they hit business logic.
- **Guardrail plugins.** Content filters (PII, harmful content, markdown cleanup), output length guards, regex filters, and SQL sanitizers run as pre/post hooks to block malicious prompt/tool/resource usage.
- **Rate limiting & quotas.** Admin routes use the `rate_limit` decorator to enforce per-IP quotas (`admin.py`), bulk import has configurable ceilings (`MCPGATEWAY_BULK_IMPORT_RATE_LIMIT`, `MCPGATEWAY_BULK_IMPORT_MAX_TOOLS`), and runtime limits (`tool_rate_limit`, `tool_timeout`, `tool_concurrent_limit`) prevent resource exhaustion.
- **Header and payload hygiene.** Passthrough headers strip control characters, clamp values to 4 KB, and refuse malformed names; request/response retries honour jitter and backoff to mitigate abuse.
- **Secure invitation flows.** Team invitations use cryptographically random, URL-safe tokens, enforce owner-only issuance, respect expiry, and prevent over-subscribing teams (`TeamInvitationService`).

## Operational Security & Monitoring

- **Startup enforcement.** `validate_security_configuration()` blocks boot when critical issues remain and `REQUIRE_STRONG_SECRETS=true`, and otherwise prints actionable warnings (default secrets, disabled auth, SSL verification overrides).
- **Security event logging.** `SECURITY_LOGGING_ENABLED` persists authentication attempts, authorization failures, and security-relevant events to the `security_events` table for audit and investigation. `SECURITY_LOGGING_LEVEL` controls verbosity: `all` (every event, high DB load), `failures_only` (default, authentication/authorization failures), or `high_severity` (critical events only). Disabled by default for performance.
- **Continuous telemetry.** Permission checks, OAuth flows, and token usage log structured events with timestamps, IP addresses, user-agent strings, span attributes, and success/failure flags for downstream monitoring.
- **Security tooling baked into the build.** The `Makefile` exposes `make security-all`, `make security-scan`, `make security-report`, `make bandit`, `make semgrep`, `make dodgy`, `make gitleaks`, `make trivy`, `make grype-scan`, `make snyk-all`, and `make fuzz-security`, providing repeatable security automation for CI/CD.
- **Observability hooks.** OpenTelemetry exports (when configured) tag spans with error flags, latency, and success status, supporting tracing-based detection of anomalies.
- **Support bundle hygiene.** Operators can gather diagnostics without leaking credentials thanks to sanitisation routines and configurable size/time limits.

## Production Hardening Checklist

- [ ] **Set production posture.** Run with `ENVIRONMENT=production`, configure `APP_DOMAIN` and explicit `ALLOWED_ORIGINS`, and leave `SKIP_SSL_VERIFY=false`.
- [ ] **Harden secrets.** Rotate `BASIC_AUTH_PASSWORD`, `JWT_SECRET_KEY`, `AUTH_ENCRYPTION_SECRET`, `PLATFORM_ADMIN_PASSWORD`, and database credentials; enable `REQUIRE_STRONG_SECRETS=true` so weak values stop startup.
- [ ] **Keep auth mandatory.** Maintain `AUTH_REQUIRED=true`, `MCP_CLIENT_AUTH_ENABLED=true`, and only enable `TRUST_PROXY_AUTH` behind a trusted authentication proxy.
- [ ] **Disable unused surfaces.** Leave `MCPGATEWAY_UI_ENABLED=false`, `MCPGATEWAY_ADMIN_API_ENABLED=false`, `MCPGATEWAY_BULK_IMPORT_ENABLED=false`, `MCPGATEWAY_A2A_ENABLED=false`, and `MCPGATEWAY_CATALOG_ENABLED=false` unless you actively use them.
- [ ] **Leave header passthrough off.** `ENABLE_HEADER_PASSTHROUGH=false` (default) should only change after reviewing downstream requirements and allowlists.
- [ ] **Secure the data plane.** Terminate TLS with real certificates (`make certs`/`make serve-ssl` or a fronting proxy), and prefer PostgreSQL/MySQL with TLS over SQLite in production.
- [ ] **Monitor activity.** Ship `token_usage_logs`, `email_auth_events`, audit trails, and structured logs to your SIEM/observability stack; alert on repeated failures or blocked requests.
- [ ] **Lock down federation.** If `federation_enabled` remains on, restrict `FEDERATION_PEERS`, ensure every peer enforces auth, and monitor health-check traffic.
- [ ] **Automate security checks.** Integrate the security Make targets into CI/CD so images, dependencies, and IaC are scanned before deployment.

## Planned & In-Progress Enhancements (🚧 Planned)

The items below are active roadmap work or design explorations. Track status in `docs/docs/architecture/roadmap.md` and the linked GitHub issues.

### Authentication & Authorization

- 🚧 **Attribute-Based Access Control (ABAC)** — Use user attributes and resource metadata to supplement RBAC for multi-tenant servers ([#706](https://github.com/IBM/mcp-context-forge/issues/706)).
- 🚧 **Policy-as-Code enforcement** — Integrate Rego/OPA policies directly into gateway decisions beyond the current optional plugin ([#271](https://github.com/IBM/mcp-context-forge/issues/271)).
- 🚧 **Per-virtual-server API keys & conditional capabilities** — Expand token scopes to cover tool-level capability grants and auto-expiry policies.

### Data Protection & Secrets

- 🚧 **HashiCorp Vault & external KMS** — Native secret backends for tool credentials, JWT keys, and OAuth secrets ([#542](https://github.com/IBM/mcp-context-forge/issues/542)).
- 🚧 **mTLS and certificate pinning** — Stronger upstream trust requirements for MCP servers with automatic pin management ([#568](https://github.com/IBM/mcp-context-forge/issues/568)).
- 🚧 **Data Loss Prevention (DLP)** — Inline scanning for sensitive payloads with redact-or-drop policies.
- 🚧 **Advanced cryptography** — Evaluating TEEs, HSM-backed signing, and post-quantum algorithms for long-lived deployments.

### Runtime & Infrastructure Security

- 🚧 **Container runtime enforcement** — Integrations for Falco, AppArmor/SELinux profiles, seccomp, and CapDrop during container deployment.
- 🚧 **Service mesh alignment** — Dedicated Istio/Linkerd blueprints for mTLS, traffic policies, and zero-trust networking.
- 🚧 **Federated attestation** — Signing/verification workflow for MCP gateways and servers to establish trust before federation link-up.
- 🚧 **Sandboxed execution** — gVisor, Firecracker, or WebAssembly sandboxes for untrusted MCP servers and plugins.

### Monitoring & Governance

- 🚧 **Dynamic security posture scoring** — Automated risk evaluations enriched with runtime metrics and audit history.
- 🚧 **Behavioral analytics** — ML-assisted anomaly detection for unusual tool usage, prompt patterns, or federation activity.
- 🚧 **Immutable audit trails** — Evaluating tamper-resistant storage (e.g., append-only or ledger-backed logs) for high-assurance environments.

These features remain aspirational until the associated PRs merge. Expect the documentation to move them into the "Current" sections when code lands.

## Additional References

- **Configuration reference:** `.env.example` and `README.md` cover every toggle in more depth.
- **Security policy:** `SECURITY.md` documents vulnerability disclosure expectations.
- **Multi-tenancy details:** `docs/docs/architecture/multitenancy.md` digs deeper into RBAC and team scoping.
- **Deployment guidance:** `docs/docs/deployment/helm.md` and `Containerfile.lite` showcase hardened deployment patterns.
