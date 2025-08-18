# Well-Known URI Configuration

Well-known URIs are standardized endpoints that web services expose for automated discovery and security contact purposes, as defined by RFC 8615. MCP Gateway provides configurable support for standard well-known URIs with security-first defaults.

## Overview

The well-known URI handler provides:

- **robots.txt** - Search engine crawler management
- **security.txt** - Security contact information (RFC 9116)
- **Custom files** - Organization-specific policies (ai.txt, dnt-policy.txt, etc.)
- **Security-first defaults** - Appropriate for private API gateway deployment
- **Admin monitoring** - Configuration status via `/admin/well-known`

## Quick Start

### Default Configuration (Private API)

```bash
# Enable well-known URIs (enabled by default)
WELL_KNOWN_ENABLED=true

# Default robots.txt blocks all crawlers (appropriate for private APIs)
# No additional configuration needed - uses built-in secure defaults
```

Access your well-known files:
- `GET /.well-known/robots.txt` - Always available
- `GET /.well-known/security.txt` - Available when configured
- `GET /admin/well-known` - Configuration status (requires auth)

## Configuration

### Basic Settings

```bash
# Enable/disable well-known URI endpoints
WELL_KNOWN_ENABLED=true

# Cache control for well-known files (seconds)
WELL_KNOWN_CACHE_MAX_AGE=3600  # 1 hour default
```

### robots.txt Configuration

```bash
# Default: blocks all crawlers (security-first for private APIs)
WELL_KNOWN_ROBOTS_TXT="User-agent: *\nDisallow: /\n\n# MCP Gateway is a private API gateway\n# Public crawling is disabled by default"

# Public API example: allow health checks, block admin
WELL_KNOWN_ROBOTS_TXT="User-agent: *\nAllow: /health\nAllow: /docs\nDisallow: /admin\nDisallow: /tools\nDisallow: /"

# Allow specific bots only
WELL_KNOWN_ROBOTS_TXT="User-agent: monitoring-bot\nAllow: /health\nAllow: /metrics\n\nUser-agent: *\nDisallow: /"
```

### security.txt Configuration

Configure security contact information per RFC 9116:

```bash
# Basic security contact
WELL_KNOWN_SECURITY_TXT="Contact: mailto:security@example.com\nExpires: 2025-12-31T23:59:59Z\nPreferred-Languages: en"

# Comprehensive security.txt
WELL_KNOWN_SECURITY_TXT="Contact: mailto:security@example.com\nContact: https://example.com/security\nEncryption: https://example.com/pgp-key.txt\nAcknowledgments: https://example.com/security/thanks\nPreferred-Languages: en, es\nCanonical: https://api.example.com/.well-known/security.txt\nHiring: https://example.com/careers"
```

**Note**: The system automatically:
- Adds `Expires` field if missing (6 months from generation)
- Adds header comments with generation timestamp
- Validates RFC 9116 format requirements

### Custom Well-Known Files

Add organization-specific well-known files via JSON configuration:

```bash
# AI usage policy
WELL_KNOWN_CUSTOM_FILES='{"ai.txt": "# AI Usage Policy\n\nThis MCP Gateway uses AI for:\n- Tool orchestration\n- Response generation\n- Error handling\n\nWe do not use AI for:\n- User data analysis\n- Behavioral tracking\n- Decision making without human oversight"}'

# Multiple custom files
WELL_KNOWN_CUSTOM_FILES='{"ai.txt": "AI Policy: Responsible use only", "dnt-policy.txt": "# Do Not Track Policy\n\nWe respect the DNT header.\nNo tracking cookies are used.\nOnly essential session data is stored.", "change-password": "https://mycompany.com/account/password"}'
```

## API Access

### Public Endpoints (No Authentication)

Well-known URIs are public by design (RFC 8615):

```bash
# Always available (when enabled)
curl https://api.example.com/.well-known/robots.txt

# Available when configured
curl https://api.example.com/.well-known/security.txt

# Custom files (when configured)
curl https://api.example.com/.well-known/ai.txt
```

### Admin Monitoring (Authentication Required)

```bash
# Check configuration status
curl -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/admin/well-known

# Response example:
{
  "enabled": true,
  "configured_files": [
    {
      "path": "/.well-known/robots.txt",
      "enabled": true,
      "description": "Robot exclusion standard",
      "cache_max_age": 3600
    },
    {
      "path": "/.well-known/security.txt",
      "enabled": true,
      "description": "Security contact information",
      "cache_max_age": 3600
    }
  ],
  "supported_files": ["robots.txt", "security.txt", "ai.txt", "dnt-policy.txt", "change-password"],
  "cache_max_age": 3600
}
```

## Security Considerations

### Private API Deployment (Default)

For private API gateways, the default configuration:
- **Blocks all crawlers** via robots.txt
- **Minimizes information disclosure**
- **No security.txt** (unless explicitly configured)
- **Cache headers** for performance but not long-term public caching

### Public API Deployment

For public-facing APIs, consider:
- **Selective crawler access** - allow health checks, block admin endpoints
- **Security contact information** - enable security.txt for responsible disclosure
- **Custom policies** - AI usage policy, privacy policy links
- **Monitoring** - track well-known endpoint access in logs

### Information Disclosure

Well-known URIs intentionally disclose information:
- **Service type/purpose** through robots.txt comments
- **Security contact** through security.txt
- **Organizational policies** through custom files

Review all content before deployment.

## Deployment Examples

### Docker Compose

```yaml
services:
  gateway:
    environment:
      WELL_KNOWN_ENABLED: "true"
      WELL_KNOWN_ROBOTS_TXT: |
        User-agent: monitoring-bot
        Allow: /health

        User-agent: *
        Disallow: /
      WELL_KNOWN_SECURITY_TXT: |
        Contact: security@example.com
        Encryption: https://example.com/pgp
        Expires: 2025-12-31T23:59:59Z
      WELL_KNOWN_CUSTOM_FILES: '{"ai.txt": "AI is used for tool orchestration"}'
      WELL_KNOWN_CACHE_MAX_AGE: "7200"
```

### Kubernetes ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-gateway-wellknown
data:
  WELL_KNOWN_ENABLED: "true"
  WELL_KNOWN_ROBOTS_TXT: |
    User-agent: *
    Disallow: /

    # Private API - No public crawling
  WELL_KNOWN_SECURITY_TXT: |
    Contact: mailto:security@example.com
    Contact: https://example.com/security
    Expires: 2025-12-31T23:59:59Z
    Preferred-Languages: en
  WELL_KNOWN_CUSTOM_FILES: |
    {
      "ai.txt": "This service uses AI for tool orchestration only.",
      "dnt-policy.txt": "We honor Do Not Track headers."
    }
```

### Helm Chart Values

```yaml
config:
  wellKnown:
    enabled: true
    cacheMaxAge: 3600
    robotsTxt: |
      User-agent: internal-monitor
      Allow: /health
      Allow: /metrics

      User-agent: *
      Disallow: /
    securityTxt: |
      Contact: security@example.com
      Encryption: https://example.com/pgp-key.txt
      Acknowledgments: https://example.com/security/hall-of-fame
    customFiles:
      ai.txt: "AI Usage: Tool orchestration and response generation only"
      dnt-policy.txt: "We respect Do Not Track headers and implement minimal tracking"
```

## Troubleshooting

### Common Issues

**Problem**: Well-known endpoints return 404
```bash
# Check if feature is enabled
curl -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/admin/well-known
```

**Problem**: security.txt not available
```bash
# security.txt is only enabled when content is provided
WELL_KNOWN_SECURITY_TXT="Contact: security@example.com"
```

**Problem**: Custom files not working
```bash
# Ensure valid JSON format
WELL_KNOWN_CUSTOM_FILES='{"ai.txt": "AI Policy content here"}'

# Check JSON validity
echo '{"ai.txt": "content"}' | python3 -m json.tool
```

**Problem**: Cache headers not updating
```bash
# Clear browser cache or check cache-control header
curl -I https://api.example.com/.well-known/robots.txt
```

### Validation

Check well-known URI configuration:

```bash
# Test robots.txt
curl -I https://api.example.com/.well-known/robots.txt

# Test security.txt (if configured)
curl https://api.example.com/.well-known/security.txt

# Check admin status
curl -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/admin/well-known | jq .
```

### Monitoring

Monitor well-known URI access in logs:

```bash
# Search for well-known requests in logs
grep "/.well-known/" /var/log/mcpgateway.log

# Monitor for unexpected access patterns
grep -E "(/.well-known/|robots|security\.txt)" /var/log/access.log | \
  awk '{print $1, $7}' | sort | uniq -c
```

## Standards Compliance

### RFC 8615 - Well-Known URIs
- ✅ Serves content at `/.well-known/` path
- ✅ Uses appropriate content types
- ✅ Implements proper caching headers
- ✅ Provides helpful error messages

### RFC 9116 - security.txt
- ✅ Validates required fields
- ✅ Auto-generates Expires field if missing
- ✅ Serves with correct content-type
- ✅ Supports all standard fields (Contact, Expires, Encryption, etc.)

### RFC 9309 - Robots Exclusion Protocol
- ✅ Standard robots.txt format
- ✅ User-agent directive support
- ✅ Allow/Disallow directive support
- ✅ Comment support for documentation

## Related Documentation

- [Security Guide](securing.md) - General security configuration
- [ADR-015](../architecture/adr/015-well-known-uri-handler.md) - Architecture decision record
- [Export/Import](export-import.md) - Configuration management
- [Environment Variables](../overview/index.md) - Complete configuration reference
