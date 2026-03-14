# Source Scanner Plugin

> Author: SwEng Group 12

Performs static security analysis on MCP server source code repositories using Semgrep and Bandit to detect vulnerabilities before deployment.

## Features

- **Multi-Scanner Support**: Integrates Semgrep and Bandit scanners for comprehensive code analysis
- **Language Detection**: Automatically detects repository language(s) and applies appropriate scanning rules
- **Dynamic Ruleset Loading**: Supports configurable Semgrep rulesets (security-audit, owasp-top-ten, language-specific)
- **Repository Caching**: Optional caching by commit SHA to avoid re-scanning identical code
- **Policy Evaluation**: Validates findings against configured severity thresholds and fail conditions
- **Comprehensive Reporting**: Aggregates, deduplicates, and normalizes findings from multiple scanners
- **Resource Management**: Automatic cleanup of temporary files and directories
- **Storage Integration**: Optional persistence of scan results to database

## Supported Scanners

### Semgrep
- **Purpose**: Fast, pattern-based static analysis across multiple languages
- **Languages**: Python, JavaScript, Java, Go, Rust, C, C++, and more
- **Default Rulesets**: security-audit, owasp-top-ten, language-specific rules
- **Configuration**: Customizable rule paths and extra arguments

### Bandit
- **Purpose**: Python-specific security vulnerability scanner
- **Languages**: Python only
- **Checks**: Detects unsafe functions, hardcoded secrets, SQL injection risks, etc.
- **Configuration**: Severity and confidence level filters

## Hooks

- `server_pre_register` - Scans MCP server source before registration
- `catalog_pre_deploy` - Scans before catalog deployment

## Configuration

### Basic Configuration
```yaml
- name: "SourceScanner"
  kind: "plugins.source_scanner.source_scanner.SourceScannerPlugin"
  hooks: ["server_pre_register", "catalog_pre_deploy"]
  mode: "enforce"
  priority: 50
  config:
    scanners:
      semgrep:
        enabled: true
        rulesets:
          - "p/security-audit"
          - "p/owasp-top-ten"
          - "p/python"
          - "p/javascript"
        extra_args: []
      bandit:
        enabled: true
        severity: "medium"
        confidence: "medium"
    
    severity_threshold: "WARNING"
    fail_on_critical: true
    
    clone_timeout_seconds: 120
    scan_timeout_seconds: 600
    max_repo_size_mb: 500
    
    cache_by_commit: true
    cache_ttl_hours: 168
```

### Configuration Options

**Scanner Settings**
- `scanners.semgrep.enabled` - Enable/disable Semgrep scanner (default: true)
- `scanners.semgrep.rulesets` - List of Semgrep rulesets to apply (default: security-audit, owasp-top-ten, p/python, p/javascript)
- `scanners.semgrep.extra_args` - Additional command-line arguments for Semgrep
- `scanners.bandit.enabled` - Enable/disable Bandit scanner (default: true)
- `scanners.bandit.severity` - Minimum severity level to report: LOW, MEDIUM, HIGH (default: MEDIUM)
- `scanners.bandit.confidence` - Minimum confidence level: LOW, MEDIUM, HIGH (default: MEDIUM)

**Policy Settings**
- `severity_threshold` - Minimum severity to trigger action: INFO, WARNING, ERROR, CRITICAL (default: WARNING)
- `fail_on_critical` - Block deployment on critical findings (default: true)

**Resource Limits**
- `clone_timeout_seconds` - Timeout for Git repository cloning (default: 120)
- `scan_timeout_seconds` - Timeout for scanner execution (default: 600)
- `max_repo_size_mb` - Maximum repository size to scan (default: 500)

**Caching**
- `cache_by_commit` - Cache results by commit SHA (default: true)
- `cache_ttl_hours` - Cache retention period in hours (default: 168 = 7 days)

**Authentication**
- `github_token_env` - Environment variable containing GitHub token for private repositories (default: GITHUB_TOKEN)

### Advanced Configuration

#### Permissive Mode (Log Only)
```yaml
config:
  mode: "permissive"
  severity_threshold: "INFO"
  fail_on_critical: false
  scanners:
    semgrep:
      enabled: true
      rulesets: ["p/security-audit"]
    bandit:
      enabled: true
      severity: "low"
```

#### Strict Mode (Block on Findings)
```yaml
config:
  mode: "enforce"
  severity_threshold: "WARNING"
  fail_on_critical: true
  scanners:
    semgrep:
      enabled: true
      rulesets:
        - "p/security-audit"
        - "p/owasp-top-ten"
        - "p/cwe-top-25"
    bandit:
      enabled: true
      severity: "medium"
      confidence: "high"
```

#### JavaScript-Only Scanning
```yaml
config:
  scanners:
    semgrep:
      enabled: true
      rulesets:
        - "p/javascript"
        - "p/owasp-top-ten"
    bandit:
      enabled: false
```

## Workflow

1. **Extract Repository Information**: Extracts `repo_url` and `ref` (branch/tag/commit) from the MCP server registration payload
2. **Check Cache**: Validates if scan results exist for the commit SHA (if caching enabled)
3. **Clone Repository**: Fetches the repository using Git and checks out the specified reference
4. **Detect Languages**: Analyzes repository structure to identify primary programming language(s)
5. **Run Scanners**:
   - Executes Semgrep with configured rulesets for all languages
   - Executes Bandit if Python is detected
6. **Normalize Findings**: Merges, deduplicates, and normalizes findings from all scanners into unified format
7. **Calculate Summary**: Aggregates findings by severity level
8. **Evaluate Policy**: Checks if findings meet deployment blocks based on severity threshold and critical condition
9. **Store Results**: Optionally persists scan results to database for auditing and reporting
10. **Cleanup**: Removes temporary directories and files
11. **Return Decision**: Returns block/allow decision and detailed findings to gateway

## Design

### Core Components

- **SourceScannerPlugin**: Main orchestrator that coordinates the scan workflow
- **RepoFetcher**: Handles Git operations (clone, checkout, cleanup)
- **LanguageDetector**: Identifies repository language and ecosystem
- **SemgrepRunner**: Executes Semgrep scanner with configured rulesets
- **BanditRunner**: Executes Bandit scanner for Python code
- **FindingNormalizer**: Merges, deduplicates, and normalizes scanner outputs
- **PolicyChecker**: Evaluates findings against severity and failure policies
- **ScanRepository**: Stores scan results in database

### Finding Format

All findings are normalized to a unified format:
```python
Finding {
    scanner: str              # "semgrep" or "bandit"
    rule_id: str              # Rule/check ID
    rule_name: str            # Human-readable rule name
    severity: str             # CRITICAL, ERROR, WARNING, INFO
    confidence: str           # HIGH, MEDIUM, LOW
    file: str                 # File path relative to repo
    line_start: int           # Starting line number
    line_end: int             # Ending line number
    message: str              # Finding description
    remediation: str          # Suggested fix (if available)
    cwe: list[str]            # Related CWE IDs
    tags: list[str]           # Classification tags
}
```


  