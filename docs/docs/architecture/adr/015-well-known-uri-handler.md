# ADR-0015: Configurable Well-Known URI Handler

- *Status:* Accepted
- *Date:* 2025-08-17
- *Deciders:* Core Engineering Team
- *Issues:* [#540](https://github.com/IBM/mcp-context-forge/issues/540)
- *Related:* Security infrastructure for standardized web discovery

## Context

ContextForge needed to support standardized well-known URIs as defined by RFC 8615 to enable proper web service discovery, security contact information, and crawler management. Well-known URIs are standardized endpoints that web services expose for automated discovery and security contact purposes.

The implementation needed to address:

- **robots.txt** for search engine crawler management (typically private API = disable crawling)
- **security.txt** for security contact information per RFC 9116
- **Custom well-known files** for additional service policies (AI usage, DNT policy, etc.)
- **Security-first defaults** appropriate for private API gateway deployment
- **Configuration flexibility** for different deployment scenarios
- **Admin monitoring** of well-known configuration status

### Requirements

- Support standard well-known URIs (robots.txt, security.txt)
- Allow custom well-known files via configuration
- Default to private API security posture (no crawling)
- RFC 9116 compliant security.txt with automatic validation
- Configurable cache headers for performance
- Admin endpoint for configuration monitoring
- Environment-based configuration via standard patterns

## Decision

We implemented a flexible `/.well-known/*` endpoint handler with the following design:

### 1. Router-Based Implementation

Created `mcpgateway/routers/well_known.py` with a dedicated FastAPI router:

```python
@router.get("/.well-known/{filename:path}", include_in_schema=False)
async def get_well_known_file(filename: str, response: Response, request: Request):
    """Serve well-known URI files with configurable content and security defaults."""
```

**Design decisions:**

- **Router isolation**: Separate router for clean organization and testing
- **Dynamic routing**: Single endpoint handles all well-known URIs
- **Security-first**: Disabled by default, explicit enable required
- **Schema exclusion**: Not included in OpenAPI docs (reduces attack surface)

### 2. Configuration-Driven Content

Extended `mcpgateway/config.py` with well-known URI settings:

```python
# Well-Known URI Configuration
well_known_enabled: bool = True
well_known_robots_txt: str = """User-agent: *
Disallow: /

# ContextForge is a private API gateway
# Public crawling is disabled by default"""

well_known_security_txt: str = ""
well_known_security_txt_enabled: bool = False
well_known_custom_files: str = "{}"  # JSON format
well_known_cache_max_age: int = 3600  # 1 hour
```

**Design decisions:**

- **Private API defaults**: robots.txt blocks all crawlers by default
- **Explicit security.txt**: Only enabled when content is provided
- **JSON custom files**: Flexible format for additional well-known files
- **Configurable caching**: Performance optimization with sensible defaults

### 3. RFC 9116 Security.txt Compliance

Implemented automatic security.txt validation and enhancement:

```python
def validate_security_txt(content: str) -> Optional[str]:
    """Validate security.txt format and add required headers."""
    # Add Expires field if missing (6 months from now)
    # Add header comments for clarity
    # Preserve existing valid content
```

**Design decisions:**

- **Auto-expires**: Adds Expires header if missing (RFC requirement)
- **Header comments**: Adds generation timestamp and description
- **Validation**: Ensures RFC 9116 compliance
- **Preservation**: Maintains existing valid fields

### 4. Well-Known Registry

Implemented a registry for known well-known URIs with metadata:

```python
WELL_KNOWN_REGISTRY = {
    "robots.txt": {
        "content_type": "text/plain",
        "description": "Robot exclusion standard",
        "rfc": "RFC 9309"
    },
    "security.txt": {
        "content_type": "text/plain",
        "description": "Security contact information",
        "rfc": "RFC 9116"
    },
    # ... additional standard URIs
}
```

**Design decisions:**

- **Helpful errors**: Provides descriptive 404 messages for known but unconfigured files
- **Content-Type mapping**: Ensures correct MIME types
- **Documentation**: Links to relevant RFCs and standards
- **Extensibility**: Easy to add new standard well-known URIs

### 5. Admin Monitoring

Added `/admin/well-known` endpoint for configuration visibility:

```python
@router.get("/admin/well-known", response_model=dict)
async def get_well_known_status(user: str = Depends(require_auth)):
    """Returns configuration status and available well-known files."""
```

**Design decisions:**

- **Authentication required**: Admin endpoint requires JWT authentication
- **Configuration visibility**: Shows enabled files and cache settings
- **Supported files list**: Displays all known well-known URI types
- **Status monitoring**: Helps administrators verify configuration

## Implementation Architecture

### File Structure
```
mcpgateway/
├── config.py                 # Well-known configuration settings
├── routers/
│   └── well_known.py         # /.well-known/* endpoint handler
└── main.py                   # Router integration

tests/unit/mcpgateway/
└── test_well_known.py        # Comprehensive test coverage

.env.example                  # Configuration documentation
```

### Request Flow
1. **Request**: `GET /.well-known/robots.txt`
2. **Authentication**: No auth required for well-known URIs (public by design)
3. **Validation**: Check if well-known endpoints are enabled
4. **Routing**: Match filename to configured content or registry
5. **Headers**: Add cache control and specific headers (X-Robots-Tag for robots.txt)
6. **Response**: Return PlainTextResponse with appropriate headers

### Security Considerations
- **No authentication**: Well-known URIs are public by design per RFC 8615
- **Content validation**: security.txt content validated against RFC 9116
- **Path traversal protection**: Filename normalization prevents directory traversal
- **Cache headers**: Appropriate cache settings reduce server load
- **Information disclosure**: Default robots.txt reveals minimal information

## Consequences

### ✅ Benefits

- **Standards Compliance**: Implements RFC 8615 (well-known URIs) and RFC 9116 (security.txt)
- **Security Contact**: Enables security researchers to find contact information
- **Crawler Management**: Proper robots.txt prevents unwanted search engine indexing
- **Flexibility**: Custom well-known files support organization-specific policies
- **Performance**: Configurable caching reduces server load for frequently accessed files
- **Monitoring**: Admin endpoint provides configuration visibility
- **Private API Focused**: Defaults appropriate for API gateway deployment

### ❌ Trade-offs

- **Information Disclosure**: Well-known URIs are public and may reveal service information
- **Cache Headers**: Public cache headers may not be appropriate for all deployments
- **Configuration Complexity**: Additional environment variables to manage
- **Static Content**: Well-known files are static and can't include dynamic information

### 🔄 Maintenance

- **security.txt Updates**: Requires periodic updates to contact information and expiration
- **RFC Compliance**: Monitor RFC updates for security.txt format changes
- **Custom File Management**: Organizations need to maintain custom well-known content
- **Cache Tuning**: May need cache duration adjustments based on usage patterns

## Configuration Examples

### Basic Private API (Default)
```bash
WELL_KNOWN_ENABLED=true
# robots.txt blocks all crawlers (default)
# security.txt disabled (default)
```

### Public API with Security Contact
```bash
WELL_KNOWN_ENABLED=true
WELL_KNOWN_SECURITY_TXT="Contact: mailto:security@example.com\nContact: https://example.com/security\nPreferred-Languages: en"
WELL_KNOWN_ROBOTS_TXT="User-agent: *\nAllow: /health\nAllow: /docs\nDisallow: /"
```

### Custom Policies
```bash
WELL_KNOWN_CUSTOM_FILES={"ai.txt": "AI Usage: Tool orchestration only", "dnt-policy.txt": "We honor Do Not Track headers"}
```

## Alternatives Considered

| Alternative | Why Not Chosen |
|------------|----------------|
| **Static file serving** | No environment-based configuration, harder to manage |
| **Database-stored content** | Overly complex for static content, harder to configure |
| **Middleware-based handler** | Less organized than router-based approach |
| **Always-enabled endpoints** | Security risk, should be explicitly enabled |
| **No security.txt validation** | Would allow non-compliant security.txt files |
| **Wildcard well-known handler** | Security risk, explicit file support is safer |

## Testing Strategy

Implemented comprehensive test coverage:

- **Default robots.txt**: Validates security-first defaults
- **security.txt validation**: Tests RFC 9116 compliance and auto-enhancement
- **Custom files**: Verifies JSON configuration parsing and serving
- **404 handling**: Tests unknown files and helpful error messages
- **Path normalization**: Ensures path traversal protection
- **Registry functionality**: Validates well-known URI metadata

## Future Enhancements

Potential improvements for future iterations:

- **Dynamic content**: Template variables (e.g., `{{DOMAIN}}`, `{{CONTACT_EMAIL}}`)
- **File upload API**: Admin interface for uploading well-known files
- **GPG signing**: Digital signature support for security.txt
- **Rate limiting**: Specific limits for well-known endpoints
- **Internationalization**: Multi-language support for policy files
- **A/B testing**: Different content based on user agent or other criteria

## Security Impact

### Positive Security Impact
- **Security contact**: Enables responsible disclosure by security researchers
- **Crawler control**: Prevents unwanted indexing of private API endpoints
- **Standards compliance**: Follows established web security practices
- **Information control**: Explicit control over what information is disclosed

### Security Considerations
- **Information disclosure**: Well-known URIs are intentionally public
- **Content validation**: Prevents serving malicious content through validation
- **Cache control**: Public caching may not be appropriate for all environments
- **Admin endpoint**: Configuration status requires authentication

## Status

This well-known URI handler implementation is **accepted and implemented** as of version 0.7.0, providing standards-compliant web service discovery while maintaining security-first defaults appropriate for private API gateway deployments.
