# Integration Tests - Repository Security Scanner

Tests for scanning any repository using **Semgrep** and **Bandit** security scanners with automated policy evaluation.

**Default Repository:** https://github.com/harishsg993010/damn-vulnerable-MCP-server.git  
**Tests:** 18 total (6 workflow + 5 Bandit + 7 Semgrep)  
**Duration:** 5 minutes (full suite)  

## Summary Report

Tests automatically generate a **Security Scan Summary Report** at the end with:
- Total findings by scanner (Semgrep vs Bandit)
- Severity breakdown (ERROR, WARNING, INFO)
- **Policy decision** (BLOCKED if errors > 0, else ALLOWED)
- Repository and branch information
- Execution metrics

```
===========================================================================
  SECURITY SCAN SUMMARY REPORT
===========================================================================
Repository: https://github.com/harishsg993010/damn-vulnerable-MCP-server.git
Branch/Ref: main
Execution Time: 5m 0s

FINDINGS SUMMARY:
  Total Findings: 179
  Semgrep Findings: 16
  Bandit Findings: 163

SEVERITY BREAKDOWN:
  ERROR: 18
  WARNING: 90
  INFO: 71

POLICY DECISION:
  [BLOCKED] Found 18 critical error(s)

TEST RESULTS: 18 tests passed
===========================================================================
```

## How to Run

```bash
# Install
make install-dev

# Verify setup
python3 tests/integration/test_source_scanners/verify_setup.py

# Run all tests (with default repository)
pytest tests/integration/test_source_scanners/ -v -m integration

# Run with different repository
TEST_REPO_URL=https://github.com/WebGoat/WebGoat.git pytest tests/integration/test_source_scanners/ -v -m integration

# Run specific scanner
pytest tests/integration/test_source_scanners/test_bandit_integration.py -v -m integration
pytest tests/integration/test_source_scanners/test_semgrep_integration.py -v -m integration
```

## Switch Repository

Change which repository to scan by setting `TEST_REPO_URL` and optionally `TEST_REPO_REF`:

```bash
# Damn Vulnerable MCP Server (Python, JavaScript)
TEST_REPO_URL=https://github.com/harishsg993010/damn-vulnerable-MCP-server.git pytest ...

# WebGoat (Java, JavaScript)
TEST_REPO_URL=https://github.com/WebGoat/WebGoat.git pytest ...

# Your own repository
TEST_REPO_URL=https://github.com/your-org/your-repo.git TEST_REPO_REF=develop pytest ...
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `TEST_REPO_URL` | damn-vulnerable-MCP-server | Repository to scan |
| `TEST_REPO_REF` | main | Branch/tag to checkout |
| `SCANNER_TIMEOUT` | 300 | Scan timeout (seconds) |
| `SCANNER_CLONE_TIMEOUT` | 60 | Clone timeout (seconds) |
| `SCANNER_MAX_SIZE_MB` | 1000 | Max repo size (MB) |
| `SCANNER_SEMGREP_ENABLED` | true | Enable Semgrep |
| `SCANNER_BANDIT_ENABLED` | true | Enable Bandit |

## Expected Results

Expected findings vary by repository and languages detected:

| Repository | Languages | Expected Findings | Time |
|------------|-----------|-------------------|------|
| damn-vulnerable-MCP-server | Python, JavaScript | 10-50 | 3-8 min |
| WebGoat | Java, JavaScript | 40-100 | 8-12 min |
| Your repo | Varies | Varies | Varies |

## Test Classes

- `TestRepoScan` - Workflow tests (6):
  - Full repository scan workflow
  - Language detection validation
  - Finding structure validation
  - Scan performance metrics
  - **Policy decision evaluation** (ERROR-based)
  
- `TestBanditIntegration` - Bandit tests (5):
  - Python-specific vulnerability detection
  - Severity distribution analysis
  - Rule detection validation
  - File coverage metrics
  
- `TestSemgrepIntegration` - Semgrep tests (7):
  - Multi-language vulnerability scanning
  - Severity classification
  - OWASP Top 10 detection
  - Message content validation

## Policy Decision Logic

Tests evaluate security policy automatically:

| Condition | Decision | Blocked |
|-----------|----------|---------|
| ERROR count > 0 | **BLOCKED** | ✅ Yes |
| Only WARNING/INFO | **ALLOWED** | ❌ No |

Policy decision is captured in the summary report for audit trails and compliance tracking.

## Fixtures

```python
# Available from conftest.py
plugin_config            # Scanner configuration (customizable via env vars)
source_scanner_plugin    # Plugin instance
repo_url                # Repository URL (TEST_REPO_URL env var)
repo_ref                # Branch/tag (TEST_REPO_REF env var, default: main)
```

### Using Fixtures

```python
@pytest.mark.asyncio
async def test_example(source_scanner_plugin, repo_url, repo_ref):
    result = await source_scanner_plugin.scan(
        repo_url=repo_url,
        ref=repo_ref,
    )
```

## Issues

| Issue | Solution |
|-------|----------|
| Semgrep not found | `pip install semgrep` |
| Bandit not found | `pip install bandit` |
| Tests skipped | Add `-m integration` flag |
| Clone timeout | Need ~500MB free disk space |

## What's Tested

✅ Repository cloning & checkout  
✅ Language detection (Python, Java, JavaScript, etc.)  
✅ Semgrep multi-language vulnerability scanning  
✅ Bandit Python security scanning  
✅ Finding deduplication across scanners  
✅ Severity classification (ERROR, WARNING, INFO)  
✅ **Policy decision evaluation (ERROR-based blocking)**  
✅ Scan performance metrics  
✅ OWASP Top 10 vulnerability detection  
✅ Finding structure validation  
✅ **Automated summary report generation**
