# URL Reputation (Rust)
> Author: Matheus Cafalchio
> Version: 0.1.0

Blocks URLs based on configured blocked domains, patterns and heuristics before resource fetch. Designed for fast and efficient resource checks.


## Hooks
- resource_pre_fetch – triggered before any resource is fetched.

## Config
```yaml
config:
    whitelist_domains: {"ibm.com", "yourdomain.com"},
    blocked_domains: {"malicious.example.com"},
    blocked_patterns: {cassino, crypto},
    use_heuristic_check: true,
    entropy_threshold: 3.65,
    block_non_secure_http: true,
```
* whitelist_domains: 
    - A set of domains that are allowed to be fetched without any checks.
* blocked_domains:
    - A set of domains that will be blocked by the plugin
* blocked_patterns:
    - A set of string patterns that will be checked against the URL's path and query parameters. If a match is found, the resource will be blocked.
* use_heuristic_check: 
    - A sequence of checks that will be performed to determine if the URL should be blocked or not. The default value is false:
* entropy_threshold:
    - A positive number that represents the maximum Shannon entropy allowed in the domain. If the entropy exceeds this threshold, the resource will be blocked.
* block_non_secure_http: 
    - A boolean flag that determines whether non-secure HTTP requests should be blocked or not. The default value is true

## Logic workflow

`validate_url`

1. Parse & Normalize URL – Parse the string into a Url. Fail → Violation: "Could not parse url".

2. Extract Domain – Parse domain from URL. Fail → Violation: "Could not parse domain".

3. Whitelist Check – If domain in config whitelisted_domains → continue_processing = true.

4. Block Non‑Secure HTTP – If scheme ≠ https and config block_non_secure_http → Violation: "Blocked non secure http url".

5. Blocked Domains – If domain in config blocked_domains → Violation: "Blocked domain".

6. Blocked Patterns – If domain matches config blocked_patterns → Violation: "Blocked pattern".

7. Heuristic Checks – Only for non-IP hosts and config use_heuristic_check is. Skip for IPv4/IPv6 addresses.

    * 7.1 Check for Shannon entropy, if entropy > config entropy_threshold → Violation: "High entropy domain".

    * 7.2 TLD Validity Check – Validate top-level domain against IANA list. Fail → Violation: "Illegal TLD".

    * 7.3 Unicode Security Check – Run heuristic::is_domain_unicode_secure. Fail → Violation: "Domain unicode is not secure".

Final Outcome – All checks pass → continue_processing = true. Any fail → return PluginViolation and continue_processing = false.


## Limitations

    - Static lists only; no external reputation providers.
    - Ianna valid TLDs are static and will be out of date
    - Ignores other schemes that are not http and https
    - Substring patterns only; no regex or anchors
    - Whitelist and Blocklist are not flexible
    - No external domain reputation checks

## TODOs
    - Allowlist support – More flexible whitelisting beyond exact domains.
    - Bloom filter integration – Efficient lookup for large domain blocklists.
    - External threat-intel integration – Query external feeds for known malicious domains.
    - Caching threat-intel results – Reduce repeated network calls and improve agent performance.
    - IP address handling policy – Decide rules for IPv4/IPv6 URLs.
    - Dynamic TLD updates – Fetch latest IANA TLD list automatically.
