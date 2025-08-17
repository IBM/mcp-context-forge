# ADR-0014: Security Headers and Environment-Aware CORS Middleware

- *Status:* Accepted
- *Date:* 2025-08-17
- *Deciders:* Core Engineering Team
- *Issues:* [#344](https://github.com/IBM/mcp-context-forge/issues/344), [#533](https://github.com/IBM/mcp-context-forge/issues/533)

## Context

The MCP Gateway needed comprehensive security headers and proper CORS configuration to prevent common web attacks including XSS, clickjacking, MIME sniffing, and cross-origin attacks. The previous implementation had:

- Basic CORS middleware with wildcard origins in some configurations
- Limited security headers only in the DocsAuthMiddleware
- No comprehensive security header implementation
- Manual CORS origin configuration without environment awareness

Security requirements included:
- **Essential security headers** for all responses
- **Environment-aware CORS** configuration for development vs production
- **Secure cookie handling** for authentication
- **Admin UI compatibility** with Content Security Policy
- **Backward compatibility** with existing configurations

## Decision

We implemented a comprehensive security middleware solution with the following components:

### 1. SecurityHeadersMiddleware

Created `mcpgateway/middleware/security_headers.py` that automatically adds essential security headers to all responses:

```python
# Essential security headers
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY" 
response.headers["X-XSS-Protection"] = "0"  # Modern browsers use CSP
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

# Content Security Policy (Admin UI compatible)
csp_directives = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss: https:",
    "frame-ancestors 'none'"
]

# HSTS for HTTPS connections
if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

# Remove sensitive headers
del response.headers["X-Powered-By"]  # if present
del response.headers["Server"]        # if present
```

### 2. Environment-Aware CORS Configuration

Enhanced CORS setup in `mcpgateway/main.py` with automatic origin configuration:

**Development Environment:**
- Automatically configures origins for common development ports: localhost:3000, localhost:8080, gateway port
- Includes both `localhost` and `127.0.0.1` variants
- Allows HTTP origins for development convenience

**Production Environment:**
- Constructs HTTPS origins from `APP_DOMAIN` setting
- Creates origins: `https://{domain}`, `https://app.{domain}`, `https://admin.{domain}`
- Enforces HTTPS-only origins
- Never uses wildcard origins

### 3. Secure Cookie Utilities

Added `mcpgateway/utils/security_cookies.py` with functions for secure authentication:

```python
def set_auth_cookie(response: Response, token: str, remember_me: bool = False):
    use_secure = (settings.environment == "production") or settings.secure_cookies
    response.set_cookie(
        key="jwt_token",
        value=token,
        max_age=30 * 24 * 3600 if remember_me else 3600,
        httponly=True,      # Prevents JavaScript access
        secure=use_secure,  # HTTPS only in production
        samesite=settings.cookie_samesite,  # CSRF protection
        path="/"
    )
```

### 4. Configuration Integration

Added new settings to `mcpgateway/config.py`:

```python
# Environment awareness
environment: str = Field(default="development", env="ENVIRONMENT")
app_domain: str = Field(default="localhost", env="APP_DOMAIN")

# Security settings
secure_cookies: bool = Field(default=True, env="SECURE_COOKIES")
cookie_samesite: str = Field(default="lax", env="COOKIE_SAMESITE")
cors_allow_credentials: bool = Field(default=True, env="CORS_ALLOW_CREDENTIALS")
```

## Consequences

### ✅ Benefits

- **Comprehensive Protection**: All responses include essential security headers
- **Automatic Configuration**: CORS origins are automatically configured based on environment
- **Admin UI Compatible**: CSP allows required CDN resources while maintaining security
- **Production Ready**: Secure defaults for production deployments
- **Development Friendly**: Permissive localhost origins for development
- **Backward Compatible**: Existing configurations continue to work
- **Cookie Security**: Authentication cookies automatically configured with security flags
- **HTTPS Detection**: HSTS header added automatically when HTTPS is detected

### ❌ Trade-offs

- **CSP Flexibility**: Using 'unsafe-inline' and 'unsafe-eval' for Admin UI compatibility
- **CDN Dependencies**: CSP allows specific external CDN domains
- **Configuration Complexity**: More environment variables to configure
- **Development Overhead**: Additional middleware processing on every request

### 🔄 Maintenance

- **CSP Updates**: May need updates if Admin UI adds new external dependencies
- **CDN Changes**: CSP must be updated if CDN URLs change
- **Security Reviews**: Periodic review of CSP directives for security improvements
- **Browser Updates**: Monitor browser CSP implementation changes

## Alternatives Considered

| Alternative | Why Not Chosen |
|------------|----------------|
| **Manual CORS configuration only** | Error-prone and inconsistent across environments |
| **Strict CSP without Admin UI support** | Would break existing Admin UI functionality |
| **Separate middleware for each header** | More complex and harder to maintain |
| **Runtime-configurable CSP** | Added complexity with minimal benefit |
| **No security headers** | Unacceptable security posture for production |
| **Environment-specific builds** | More complex deployment and maintenance |

## Implementation Details

### Middleware Order
```python
# Order matters - security headers should be added after CORS
app.add_middleware(CORSMiddleware, ...)      # 1. CORS first
app.add_middleware(SecurityHeadersMiddleware) # 2. Security headers
app.add_middleware(DocsAuthMiddleware)       # 3. Auth protection
```

### Environment Detection
- Uses `ENVIRONMENT` setting to determine development vs production mode
- Falls back to safe defaults if environment not specified
- Only applies automatic origins when using default configuration

### CSP Design Decisions
- **'unsafe-inline'**: Required for Tailwind CSS inline styles and Alpine.js
- **'unsafe-eval'**: Required for some JavaScript frameworks used in Admin UI
- **Specific CDN domains**: Whitelisted known-good CDN sources instead of wildcard
- **'frame-ancestors none'**: Prevents all framing to prevent clickjacking

## Testing Strategy

Implemented comprehensive test coverage (42 new tests):
- **Security headers validation** across all endpoints
- **CORS behavior testing** for allowed and blocked origins  
- **Environment-aware configuration** testing
- **Cookie security attributes** validation
- **Production security posture** verification
- **CSP directive structure** validation
- **HSTS behavior** testing

## Future Enhancements

Potential improvements for future iterations:
- **CSP Nonces**: Replace 'unsafe-inline' with nonces for dynamic content
- **Subresource Integrity**: Add SRI for external CDN resources
- **CSP Violation Reporting**: Implement CSP violation reporting endpoint
- **Per-Route CSP**: Different CSP policies for different endpoints
- **Security Header Compliance**: Monitoring dashboard for header compliance

## Status

This security headers and CORS middleware implementation is **accepted and implemented** as of version 0.5.0, providing comprehensive security coverage while maintaining compatibility with existing functionality.