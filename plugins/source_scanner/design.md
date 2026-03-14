# SourceScannerPlugin_Design.md

## Flow

Gateway

- **Hook Trigger**  
  The gateway invokes the Source Scanner Plugin during the `server_pre_register` and/or `catalog_pre_deploy` stage.

---

SourceScanner Plugin -> GIT (Clone & Checkout)

- **Source Retrieval**  
  The plugin clones the target Git repository and checks out the specified branch, tag, or commit.

---

SourceScanner Plugin

- **Language Detection**  
  The repository is inspected to identify the project’s primary language(s) and ecosystem.

---

Scanners

- **Scanner Execution**
  - If Python is detected, Bandit is executed to scan the source code.
  - For all supported languages, Semgrep is executed with security-focused rulesets.

---

Scanners -> SourceScanner Plugin

- **Result Collection**  
  Raw scan results are collected from each scanner in their native output formats (e.g. JSON, SARIF).

---

SourceScanner Plugin

- **Merge and Deduplication**  
  Findings from multiple scanners are merged and deduplicated.
- **Policy Evaluation**  
  The aggregated findings are evaluated against configured severity thresholds.

---

SourceScanner Plugin (Resource Cleanup)

- **Resource Cleanup**  
  Temporary directories and other transient resources are cleaned up.

---

SourceScanner Plugin -> Gateway

- **Result Propagation**  
  The final findings or blocking decision are returned to the gateway.

---

### Call Flow

```bash
Gateway
  → SourceScannerPlugin
      → RepoFetcher.fetch(repo_url, ref, auth, limits) → (repo_path, commit_sha, cleanup)
      → LanguageDetector.detect(repo_path) → languages
      → SemgrepRunner.run(repo_path, config, timeout) → findings[]
      → [if python] BanditRunner.run(repo_path, config, timeout) → findings[]
      → ParserNormalizer.merge_dedup(findings_by_scanner) → merged_findings[]
      → PolicyChecker.evaluate(merged_findings, threshold, fail_on_critical) → decision
      → cleanup()
      → return ScanResult(findings, decision, metadata)
```

## Component Responsibilities

- **SourceScannerPlugin -- Xinyi**  
  Acts as the orchestrator. It coordinates the scan workflow, reads configuration, and aggregates results.

  **Talks to**
  - Calls `RepoFetcher.fetch(...)`
  - Calls `LanguageDetector.detect(repo_path)`
  - Calls selected `ScannerRunner.run(...)`
  - Calls `ParserNormalizer.merge_dedup(...)`
  - Calls `PolicyChecker.evaluate(...)`
  - Returns `ScanResult` to Gateway

---

- **RepoFetcher -- Yasser/#2**  
  Handles Git operations, including repository cloning, reference checkout, and temporary directory management.

  - Receives `(repo_url, ref, auth, limits)`
  - Returns `workspace { path, commit_sha }` + `cleanup()`

---

- **LanguageDetector -- Yasser/#2**  
  Determines the programming language(s) and ecosystem of the repository to guide scanner selection.

  - Receives `repo_path`
  - Returns `languages: string[]`

---

- **ScannerRunners (interface)**  
  Defines the common contract for all source code scanners.

  - Receives `(repo_path, scanner_config, timeout_s)`
  - Returns `findings: Finding[]` (optional `raw_output_ref`)

- **SemgrepRunner -- Ayo / #1**   
  Runs Semgrep and parses its output (SARIF/JSON) into `Finding[]`.

- **BanditRunner -- Yasser / #2**   
  Runs Bandit and parses its output (JSON) into `Finding[]`.

---

- **Parser / Normalizer -- Arnav/#3**  
  Parses scanner outputs and converts them into a unified findings schema.

  - Receives `findings_by_scanner: Finding[][]`
  - Returns `merged_findings: Finding[]`

---

- **Policy / Threshold Checker -- Xinyi**  
  Applies severity thresholds and enforcement rules to decide whether to allow or block registration or deployment.

  - Receives `(findings, severity_threshold, fail_on_critical)`
  - Returns `decision { blocked, reason? }`

---

- **Storage / ScanRepository -- Arnav**  
  Persists scan results and findings, supports deduplication and caching by commit SHA.

  - Receives `ScanResult` / `Finding[]` + metadata
  - Stores and retrieves scan records (TTL-based cache if enabled)

---

- **Utils / Exec**  
  Shared subprocess wrapper used by RepoFetcher and ScannerRunners.
  All CLI invocations (git/semgrep/bandit) should use `utils.exec.run_command(...)`.

  - Runs CLI commands with timeout
  - Returns stdout/stderr/return code for parsing and error handling

---

- **Tests (Unit + Integration) -- Yasser**  
  Defines and implements unit/integration tests for the plugin workflow.

  - Unit tests: policy, normalizer, runners, language detection
  - Integration tests: clone → scan → policy decision on known vulnerable repos


## Data Contracts (Unified Schemas)

### Finding (Unified Finding Schema)

for each problem from **Scanners**

```bash
- scanner: string                             # from which tool"semgrep" | "bandit" | ...
- severity: "ERROR"|"WARNING"|"INFO"          # used to make policy judgments
- rule_id: string                             # which rule matched (for dedup & explain)
- message: string                             # message for read
- file_path: string                           # which file is the problem in 
- line?: number
- column?: number
- code_snippet?: string
- help_url?: string

# ? -> optional 
```

**Severity mapping (normalization):**
- Bandit: LOW → INFO, MEDIUM → WARNING, HIGH → ERROR
- Semgrep: map tool-specific severities into ERROR/WARNING/INFO

**Nots:**
- All scanners must normalize their outputs into this `(Finding schema)`.
- Deduplication key suggestion: `(scanner, rule_id, file_path, line, message)`

---

### ScanResult (Plugin Output Contract)

whole problem report generate by **Plugin**

```bash
- repo_url: string
- ref?: string                   # branch/tag/commit (user input)
- commit_sha?: string            # resolved SHA after checkout (if available)
- languages: string[]            # e.g. ["python", "javascript"]
- findings: Finding[]
- summary:
    - error_count: number
    - warning_count: number
    - info_count: number
- blocked: boolean               # true if policy blocks the workflow
- block_reason?: string          # present when blocked=true
```

## Configuration Contract

### Scanner Configuration

The plugin supports configuring scanners via the scanners field, matching the issue specification.

**Preferred (recommended) configuration style:**

```
config:
  scanners:
    semgrep:
      enabled: true
      rulesets:
        - p/security-audit
        - p/owasp-top-ten
    bandit:
      enabled: true
      severity: medium
      confidence: medium
```

**Backward-compatible configuration (also supported):**

```
config:
  semgrep:
    enabled: true
  bandit:
    enabled: true
```

**Notes:**

- The `scanners.*` form is preferred and aligns with the project issue and documentation.

- Top-level `semgrep / bandit` configuration is supported for backward compatibility.

- `severity_threshold` defaults to `"WARNING"` if not specified.


## Error Handling Contract

**Purpose:** provide consistent error handling across all components.

### Error Types

All components must raise errors from the shared exception hierarchy:

- `RepoFetchError` (clone / checkout / size / timeout)

- `ScannerError` (scanner execution failures)

- `ParseError` (scanner output parsing failures)

- `PolicyError` (policy evaluation failures)

#### Responsibilities

- **Component owners** (RepoFetcher, ScannerRunner, Parser, etc.)

    - Raise the appropriate error type

    - Provide a short, descriptive error message

- **SourceScannerPlugin** (orchestrator)

    - Catches these errors

    - Decides whether to block or allow based on plugin mode and configuration

**Blocking behavior:**

- **Audit mode:** errors are reported but do not block

- **Enforce mode:** blocking is decided by the orchestrator, not by individual components

## Interface Contracts

### RepoFetcher

**Purpose:** clone + checkout + manage temp workspace

- **Input**
  - `repo_url: string`
  - `ref?: string` (branch/tag/commit)
  - `auth: { token_env?: string }`
  - `limits: { clone_timeout_s: number, max_repo_size_mb?: number }`
- **Output**
  - `workspace: { path: string, commit_sha?: string }`
  - `cleanup(): void`
- **Failure modes**
  - clone/checkout fails → return error to plugin (plugin decides allow/block)

---

### LanguageDetector

**Purpose:** detect language(s) to select scanners

- **Input**
  - `repo_path: string`
- **Output**
  - `languages: string[]` (e.g. `["python"]`, `["javascript","typescript"]`)
- **Notes**
  - MVP heuristic: `pyproject.toml/requirements.txt/setup.py` → python; `package.json` → js/ts

---

### ScannerRunner (Generic Interface)

**Purpose:** run one scanner and return normalized findings (preferred)

- **Input**
  - `repo_path: string`
  - `scanner_config: object`
  - `timeout_s: number`
- **Output**
  - `findings: Finding[]`
  - (optional) `raw_output_ref?: string` (for debugging)
- **Implementations**
  - `SemgrepRunner`
  - `BanditRunner`

---

### Parser / Normalizer

**Purpose:** unify fields + merge + deduplicate

- **Input**
  - `findings_by_scanner: Finding[][]`
    - Raw: each scanner
    - Column: findings from each scanner
- **Output**
  - `merged_findings: Finding[]`
- **Dedup key (suggested MVP)**
  - `(scanner, rule_id, file_path, line, message)`

---

### Policy / Threshold Checker

**Purpose:** decide allow vs block

- **Input**
  - `findings: Finding[]`
  - `severity_threshold: "ERROR"|"WARNING"|"INFO"`
  - `fail_on_critical: boolean`
    - audit mode: only report no block -> false
    - enforce mode: block when reach threshold -> true
- **Output**
  - `decision: { blocked: boolean, reason?: string }`
- **Suggested rule (MVP)**
  - If `fail_on_critical=true` and any finding severity ≥ threshold → blocked=true

## Hook Trigger Points (Gateway Integration)  

- Gateway currently documents server_pre_register and catalog_pre_deploy but does not invoke them in code.
- To enable SourceScannerPlugin, we need to add hook trigger points in:  
  - `mcpgateway/services/server_service.py::register_server` → invoke `"server_pre_register"`
  - `mcpgateway/services/catalog_service.py::deploy_catalog` → invoke `"catalog_pre_deploy"`
- Current behavior is fail-open until enforce-mode scan-failure policy is finalized.

## Directory Structure

```bash
plugins/source_scanner/
  __init__.py                 # package init
  source_scanner.py           # Plugin + hooks + orchestration 
  config.py                   # Pydantic config models
  types.py                    # Finding / ScanResult unified schemas
  policy.py                   # threshold + block/allow decision
  errors.py                   # shared exception types (clone/scan/parse/timeout)
  repo_fetcher.py             # git clone/checkout + limits + cleanup (DevOps: Yasser)
  language_detector.py        # detect repo languages/ecosystem (2nd year #2)

  scanners/
    __init__.py
    semgrep_runner.py         # run semgrep + parse SARIF/JSON -> Finding[] (Ayo + 2nd #1)
    bandit_runner.py          # run bandit + parse JSON -> Finding[] (2nd #2)

  parsing/
    __init__.py
    normalizer.py             # merge + dedup + summary counts + severity normalize (2nd #3)

  storage/
    __init__.py
    models.py                 # DB models / tables for findings & scans (Arnav)
    repository.py             # save/load, cache by commit_sha, TTL (Arnav)

  utils/
    __init__.py
    exec.py                   # subprocess wrapper: timeout, stdout/stderr, rc

  tests/source_scanner/
    integration/
      test_scan_vulnerable_repo.py   # end-to-end: clone -> scan -> block/allow (Yasser)
    test_semgrep_runner.py           # runner-level tests (Ayo/Yasser)
    test_bandit_runner.py
    test_repo_fetcher.py
    test_language_detector.py
    test_normalizer.py
    test_policy.py

  plugin-manifest.yaml        # plugin registration metadata
  README.md                   # usage + config + dev notes (2nd #4 final)
```
