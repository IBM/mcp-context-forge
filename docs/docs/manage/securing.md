# Securing MCP Gateway

This guide provides essential security configurations and best practices for deploying MCP Gateway in production environments.

## ⚠️ Critical Security Notice

**MCP Gateway is currently in early beta (v0.5.0)** and requires careful security configuration for production use:

- The **Admin UI is development-only** and must be disabled in production
- MCP Gateway is **not a standalone product** - it's an open source component to integrate into your solution
- **No official support** is provided - security is your responsibility
- Expect **breaking changes** between versions until 1.0 release
- Do not use it with insecure MCP servers.

## 🚨 Production Security Checklist

### 1. Disable Development Features

```bash
# Required for production - disable all admin interfaces
MCPGATEWAY_UI_ENABLED=false
MCPGATEWAY_ADMIN_API_ENABLED=false

# Disable unused features
MCPGATEWAY_ENABLE_ROOTS=false    # If not using roots
MCPGATEWAY_ENABLE_PROMPTS=false  # If not using prompts
MCPGATEWAY_ENABLE_RESOURCES=false # If not using resources
```

### 2. Enable Authentication & Security

```bash
# Configure strong authentication
MCPGATEWAY_AUTH_ENABLED=true
MCPGATEWAY_AUTH_USERNAME=custom-username  # Change from default
MCPGATEWAY_AUTH_PASSWORD=strong-password-here  # Use secrets manager

# Set environment for security defaults
ENVIRONMENT=production

# Configure domain for CORS
APP_DOMAIN=yourdomain.com

# Ensure secure cookies (automatic in production)
SECURE_COOKIES=true
COOKIE_SAMESITE=strict

# Configure CORS (auto-configured based on APP_DOMAIN in production)
CORS_ALLOW_CREDENTIALS=true
```

### 3. Network Security

- [ ] Configure TLS/HTTPS with valid certificates
- [ ] Implement firewall rules and network policies
- [ ] Use internal-only endpoints where possible
- [ ] Configure appropriate CORS policies (auto-configured by ENVIRONMENT setting)
- [ ] Set up rate limiting per endpoint/client
- [ ] Verify security headers are present (automatically added by SecurityHeadersMiddleware)
- [ ] Configure iframe embedding policy (X_FRAME_OPTIONS=DENY by default, change to SAMEORIGIN if needed)

### 4. Container Security

```bash
# Run containers with security constraints
docker run \
  --read-only \
  --user 1001:1001 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  mcpgateway:latest
```

- [ ] Use minimal base images (UBI Micro)
- [ ] Run as non-root user
- [ ] Enable read-only filesystem
- [ ] Set resource limits (CPU, memory)
- [ ] Scan images for vulnerabilities

### 5. Secrets Management

- [ ] **Never store secrets in environment variables directly**
- [ ] Use a secrets management system (Vault, AWS Secrets Manager, etc.)
- [ ] Rotate credentials regularly
- [ ] Restrict container access to secrets
- [ ] Never commit `.env` files to version control

### 6. MCP Server Validation

Before connecting any MCP server:

- [ ] Verify server authenticity and source code
- [ ] Review server permissions and data access
- [ ] Test in isolated environment first
- [ ] Monitor server behavior for anomalies
- [ ] Implement rate limiting for untrusted servers

### 7. Database Security

- [ ] Use TLS for database connections
- [ ] Configure strong passwords
- [ ] Restrict database access by IP/network
- [ ] Enable audit logging
- [ ] Regular backups with encryption

### 8. Monitoring & Logging

- [ ] Set up structured logging without sensitive data
- [ ] Configure log rotation and secure storage
- [ ] Implement monitoring and alerting
- [ ] Set up anomaly detection
- [ ] Create incident response procedures

### 9. Integration Security

MCP Gateway should be integrated with:

- [ ] API Gateway for auth and rate limiting
- [ ] Web Application Firewall (WAF)
- [ ] Identity and Access Management (IAM)
- [ ] SIEM for security monitoring
- [ ] Load balancer with TLS termination

### 10. Well-Known URI Security

Configure well-known URIs appropriately for your deployment:

```bash
# For private APIs (default) - blocks all crawlers
WELL_KNOWN_ENABLED=true
WELL_KNOWN_ROBOTS_TXT="User-agent: *\nDisallow: /"

# For public APIs - allow health checks, block sensitive endpoints
# WELL_KNOWN_ROBOTS_TXT="User-agent: *\nAllow: /health\nAllow: /docs\nDisallow: /admin\nDisallow: /tools"

# Security contact information (RFC 9116)
WELL_KNOWN_SECURITY_TXT="Contact: mailto:security@example.com\nExpires: 2025-12-31T23:59:59Z\nPreferred-Languages: en"
```

Security considerations:
- [ ] Configure security.txt with current contact information
- [ ] Review robots.txt to prevent unauthorized crawler access
- [ ] Monitor well-known endpoint access in logs
- [ ] Update security.txt Expires field before expiration
- [ ] Consider custom well-known files only if necessary

### 11. Downstream Application Security

Applications consuming MCP Gateway data must:

- [ ] Validate all inputs from the gateway
- [ ] Implement context-appropriate sanitization
- [ ] Use Content Security Policy (CSP) headers
- [ ] Escape data for output context (HTML, JS, SQL)
- [ ] Implement their own authentication/authorization

## 🔐 Environment Variables Reference

### Security-Critical Settings

```bash
# Core Security
MCPGATEWAY_UI_ENABLED=false              # Must be false in production
MCPGATEWAY_ADMIN_API_ENABLED=false       # Must be false in production
MCPGATEWAY_AUTH_ENABLED=true             # Enable authentication
MCPGATEWAY_AUTH_USERNAME=custom-user     # Change from default
MCPGATEWAY_AUTH_PASSWORD=<from-secrets>  # Use secrets manager

# Feature Flags (disable unused features)
MCPGATEWAY_ENABLE_ROOTS=false
MCPGATEWAY_ENABLE_PROMPTS=false
MCPGATEWAY_ENABLE_RESOURCES=false

# Network Security
MCPGATEWAY_CORS_ALLOWED_ORIGINS=https://your-domain.com
MCPGATEWAY_RATE_LIMIT_ENABLED=true
MCPGATEWAY_RATE_LIMIT_PER_MINUTE=100

# Logging (no sensitive data)
MCPGATEWAY_LOG_LEVEL=INFO               # Not DEBUG in production
MCPGATEWAY_LOG_SENSITIVE_DATA=false     # Never log sensitive data
```

## 🚀 Deployment Architecture

### Recommended Production Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│   WAF/CDN       │────▶│  Load Balancer │────▶│   API Gateway   │
│                 │     │   (TLS Term)    │     │  (Auth/Rate)    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │                 │
                                                 │  MCP Gateway    │
                                                 │  (Internal)     │
                                                 └────────┬────────┘
                                                          │
                              ┌───────────────────────────┼───────────────────────────┐
                              │                           │                           │
                              ▼                           ▼                           ▼
                     ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
                     │                 │        │                 │        │                 │
                     │  Trusted MCP    │        │    Database     │        │     Redis       │
                     │    Servers      │        │   (TLS/Auth)    │        │   (TLS/Auth)    │
                     └─────────────────┘        └─────────────────┘        └─────────────────┘
```

## 🔍 Security Validation

### Pre-Production Checklist

1. **Run Security Scans**
   ```bash
   make security-all        # Run all security tools
   make security-report     # Generate security report
   make trivy              # Scan container vulnerabilities
   ```

2. **Validate Configuration**
   - Review all environment variables
   - Confirm admin features disabled
   - Verify authentication enabled
   - Check TLS configuration

3. **Test Security Controls**
   - Attempt unauthorized access
   - Verify rate limiting works
   - Test input validation
   - Check error handling

4. **Review Dependencies**
   ```bash
   make pip-audit          # Check Python dependencies
   make sbom              # Generate software bill of materials
   ```

## 📚 Additional Resources

- [Security Policy](https://github.com/IBM/mcp-context-forge/blob/main/SECURITY.md) - Full security documentation
- [Deployment Options](index.md) - Various deployment methods
- [Environment Variables](../configuration/environment-variables.md) - Complete configuration reference

## ⚡ Quick Start Security Commands

```bash
# Development (with security checks)
make security-all && make test && make run

# Production build
make docker-prod

# Security audit
make security-report
```

Remember: **Security is a shared responsibility**. MCP Gateway provides *some* security controls, but you must properly configure and integrate it within a comprehensive security architecture.
