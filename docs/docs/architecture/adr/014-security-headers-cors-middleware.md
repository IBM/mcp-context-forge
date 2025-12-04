# ADR-0014: Security Headers and Environment-Aware CORS Middleware

- *Status:* Accepted
- *Date:* 2025-08-17
- *Deciders:* Core Engineering Team
- *Issues:* [#344](https://github.com/IBM/mcp-context-forge/issues/344), [#533](https://github.com/IBM/mcp-context-forge/issues/533)
- *Related:* Addresses all 9 security headers identified by nodejsscan

## Context

The MCP Gateway needed comprehensive security headers and proper CORS configuration to prevent common web attacks including XSS, clickjacking, MIME sniffing, and cross-origin attacks. Additionally, the nodejsscan static analysis tool identified 9 missing security headers specifically for the Admin UI and static assets.

The previous implementation had:

- Basic CORS middleware with wildcard origins in some configurations
- Limited security headers only in the DocsAuthMiddleware
- No comprehensive security header implementation
- Manual CORS origin configuration without environment awareness
- Admin UI cookie settings without proper security attributes
- No static analysis tool compatibility

Security requirements included:

- **Essential security headers** for all responses (issue #344)
- **Configurable security headers** for Admin UI and static assets (issue #533)
- **Environment-aware CORS** configuration for development vs production
- **Secure cookie handling** for authentication
- **Admin UI compatibility** with Content Security Policy
- **Static analysis compatibility** for nodejsscan and similar tools
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
response.headers["X-Download-Options"] = "noopen"  # Prevent IE downloads
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

### 4. Configurable Security Headers

Added comprehensive configuration options to `mcpgateway/config.py` for all security headers:

```python
# Environment awareness
environment: str = Field(default="development", env="ENVIRONMENT")
app_domain: str = Field(default="localhost", env="APP_DOMAIN")

# Cookie Security
secure_cookies: bool = Field(default=True, env="SECURE_COOKIES")
cookie_samesite: str = Field(default="lax", env="COOKIE_SAMESITE")

# CORS Configuration
cors_allow_credentials: bool = Field(default=True, env="CORS_ALLOW_CREDENTIALS")

# Security Headers Configuration (issue #533)
security_headers_enabled: bool = Field(default=True, env="SECURITY_HEADERS_ENABLED")
x_frame_options: str = Field(default="DENY", env="X_FRAME_OPTIONS")
x_content_type_options_enabled: bool = Field(default=True, env="X_CONTENT_TYPE_OPTIONS_ENABLED")
x_xss_protection_enabled: bool = Field(default=True, env="X_XSS_PROTECTION_ENABLED")
x_download_options_enabled: bool = Field(default=True, env="X_DOWNLOAD_OPTIONS_ENABLED")
hsts_enabled: bool = Field(default=True, env="HSTS_ENABLED")
hsts_max_age: int = Field(default=31536000, env="HSTS_MAX_AGE")
hsts_include_subdomains: bool = Field(default=True, env="HSTS_INCLUDE_SUBDOMAINS")
remove_server_headers: bool = Field(default=True, env="REMOVE_SERVER_HEADERS")
```

### 5. Static Analysis Tool Compatibility

Added security meta tags to `mcpgateway/templates/admin.html` for static analysis tool compatibility:

```html
<!-- Security meta tags for static analysis tools (complement HTTP headers) -->
<meta http-equiv="Content-Security-Policy" content="..." />
<meta http-equiv="X-Frame-Options" content="DENY" />
<meta http-equiv="X-Content-Type-Options" content="nosniff" />
<meta http-equiv="X-XSS-Protection" content="1; mode=block" />
<meta http-equiv="X-Download-Options" content="noopen" />
```

### 6. Enhanced Static Analysis

Updated Makefile to scan both static files and templates:
```makefile
nodejsscan:
    @$(VENV_DIR)/bin/nodejsscan --directory ./mcpgateway/static --directory ./mcpgateway/templates || true
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

### iframe Embedding Configuration
By default, iframe embedding is **disabled** for security via `X-Frame-Options: DENY` and `frame-ancestors 'none'`. To enable iframe embedding:

1. **Same-domain embedding**: Set `X_FRAME_OPTIONS=SAMEORIGIN`
2. **Specific domain embedding**: Set `X_FRAME_OPTIONS=ALLOW-FROM https://trusted-domain.com`
3. **Disable frame protection**: Set `X_FRAME_OPTIONS="ALLOW-ALL"` (not recommended)

**Note**: When changing X-Frame-Options, also consider updating the CSP `frame-ancestors` directive for comprehensive browser support.

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
