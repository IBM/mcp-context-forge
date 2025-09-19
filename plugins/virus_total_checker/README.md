# VirusTotal URL Checker Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Integrates with VirusTotal v3 to evaluate URLs, domains, and IP addresses before fetching resources. Optionally submits unknown URLs for analysis and can wait briefly for results. Includes a small in-memory cache to reduce API calls.

## Hooks
- resource_pre_fetch

## Config
```yaml
config:
  enabled: true
  api_key_env: "VT_API_KEY"               # env var containing your VT API key
  base_url: "https://www.virustotal.com/api/v3"
  timeout_seconds: 8.0

  # What to check
  check_url: true
  check_domain: true
  check_ip: true

  # Unknown handling
  scan_if_unknown: false                  # submit URL for scanning if unknown
  wait_for_analysis: false                # poll briefly for completed analysis
  max_wait_seconds: 8
  poll_interval_seconds: 1.0

  # Block policy
  block_on_verdicts: ["malicious"]       # also consider suspicious/timeout as needed
  min_malicious: 1                        # engines reporting malicious to block

  # Cache
  cache_ttl_seconds: 300

  # Retry (ResilientHttpClient)
  max_retries: 3
  base_backoff: 0.5
  max_delay: 8.0
  jitter_max: 0.2

  # Local overrides
  allow_url_patterns: []        # regexes that skip VT (always allow)
  deny_url_patterns: []         # regexes that block immediately
  allow_domains: []             # exact or suffix (example.com allows foo.example.com)
  deny_domains: []              # exact or suffix
  allow_ip_cidrs: []            # e.g., 10.0.0.0/8
  deny_ip_cidrs: []
  # Local overrides
  allow_url_patterns:
    - "trusted\\.example"
  deny_url_patterns:
    - "malware\\.download"
  allow_domains:
    - "partner.example.com"
  deny_domains:
    - "evil.example"
  allow_ip_cidrs:
    - "10.0.0.0/8"
  deny_ip_cidrs:
    - "203.0.113.0/24"
```

### Examples
- Allowlist a trusted CDN URL pattern while denying a known bad domain substring:
```yaml
config:
  allow_url_patterns: ["cdn\\.trusted\\.example"]
  deny_url_patterns: ["\\.badcdn\\."]
```

- Deny a domain and a public IP range regardless of VT verdicts:
```yaml
config:
  deny_domains: ["malicious.example"]
  deny_ip_cidrs: ["198.51.100.0/24"]
```

- Override precedence (allow wins over deny):
```yaml
config:
  allow_url_patterns: ["trusted\\.example"]
  deny_url_patterns: ["/malware/"]
  override_precedence: "allow_over_deny"
```

## Hook Usage
- resource_pre_fetch: Applies local overrides and cache-first checks; performs URL/domain/IP/file reputation lookups; can submit unknown URLs/files (if enabled); blocks or annotates metadata.
- resource_post_fetch: Scans ResourceContent.text for URLs; applies local overrides; queries VT; blocks on policy.
- prompt_post_fetch: Scans rendered prompt text (Message.content.text); applies local overrides; queries VT; blocks on policy.
- tool_post_invoke: Scans tool outputs for URLs; applies local overrides; queries VT; blocks on policy.

## Override Precedence
- Config: `override_precedence: "deny_over_allow" | "allow_over_deny"`
- Behavior summary:
  - Neither allow nor deny match → proceed with VT checks
  - Allow-only match → allow immediately (skip VT)
  - Deny-only match → block immediately (VT_LOCAL_DENY)
- Both allow and deny match:
    - deny_over_allow → block
    - allow_over_deny → allow (skip VT)

## Quick Start Setups

- URL-only checks with upload and short polling (fast feedback):
```yaml
config:
  enabled: true
  # Only check URLs
  check_url: true
  check_domain: false
  check_ip: false
  # Submit unknown URLs and wait briefly for an answer
  scan_if_unknown: true
  wait_for_analysis: true
  max_wait_seconds: 8
  poll_interval_seconds: 1.0
  # Strict blocking
  block_on_verdicts: ["malicious", "suspicious"]
  min_malicious: 1
  # Retry tuning
  max_retries: 3
  base_backoff: 0.5
  max_delay: 8.0
  jitter_max: 0.2
```

- File-only reputation mode (hash-first, upload small unknowns):
```yaml
config:
  enabled: true
  # Disable network URL/domain/IP checks
  check_url: false
  check_domain: false
  check_ip: false
  # Enable local file checks for file:// URIs
  enable_file_checks: true
  file_hash_alg: "sha256"
  upload_if_unknown: true
  upload_max_bytes: 10485760   # 10MB cap
  wait_for_analysis: true
  max_wait_seconds: 12
  # Policy
  block_on_verdicts: ["malicious"]
  min_malicious: 1
```

- Strict overrides (VT as audit-only fallback):
  In `plugins/config.yaml`, set the plugin `mode: permissive` so VT verdicts annotate metadata without blocking, and rely on local overrides for enforcement.
```yaml
config:
  enabled: true
  # Local overrides enforce policy
  deny_url_patterns: ["(?:/download/|/payload/)"]
  deny_domains: ["malicious.example", "evil.org"]
  deny_ip_cidrs: ["203.0.113.0/24"]
  allow_url_patterns: ["trusted\\.example", "cdn\\.partner\\.com"]
  override_precedence: "allow_over_deny"   # allow exceptions to denylists

  # VT still runs but does not block (plugin mode is permissive)
  check_url: true
  check_domain: true
  check_ip: true
  block_on_verdicts: []   # rely on local overrides only
  min_malicious: 0
  min_harmless_ratio: 0.0
```

## Design
- Uses gateway's ResilientHttpClient (mcpgateway.utils.retry_manager) configured via plugin config and passing httpx client args (headers, timeout).
- URL checks: GET /urls/{id}, where id is base64url(url) without padding. If unknown and scan_if_unknown=true, POST /urls to submit; if wait_for_analysis, polls /analyses/{id} until completed or timeout, then re-fetches URL info.
- Domain checks: GET /domains/{domain}; IP checks: GET /ip_addresses/{ip}.
- Blocking policy evaluates last_analysis_stats and applies block_on_verdicts and min_malicious thresholds.
- Results and errors are returned via plugin metadata.virustotal to aid auditability.
- Local overrides: deny_* patterns/domains/cidrs block immediately; allow_* entries bypass VT entirely.
- Cache-first: for resource_pre_fetch, consults in-memory cache and can block/allow without network calls.

## Limitations
- Requires a valid VirusTotal API key with sufficient quota; otherwise the plugin skips checks.
- Only simple per-process in-memory caching; no distributed cache.
- File scanning and hash lookups are not invoked in this hook (URL-focused); can be extended in the future.

## TODOs
- Add file hash lookups (/files/{hash}) and optional file submissions when appropriate.
- Provide a tool_post_invoke hook to scan URLs found in tool outputs.
- Add distributed caching and rate limiting controls.
 - Add domain/IP allow/deny precedence configuration (e.g., choose allow-over-deny semantics).

## Design
- Static domain blocklist evaluated at `resource_pre_fetch`.
- Subdomain-aware exact match check.

## Limitations
- No external API calls or advanced reputation signals.
- No pattern list; domains only.

## TODOs
- Add optional external provider mode with caching.
- Support pattern lists and allowlists.
