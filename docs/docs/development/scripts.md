# Development Scripts

This page documents utility scripts in the `scripts/` directory that assist with development, testing, and operations.

---

## 📊 GitHub History Chart Generator

**Location:** `scripts/github_history_chart.py`

Generates a line chart showing the number of open issues and PRs at the end of each Tuesday throughout a specified time period.

### Features

- Fetches all issues and PRs from GitHub repository
- Reconstructs historical state at each Tuesday
- Dual y-axes for independent scaling (issues on left, PRs on right)
- Excludes draft PRs from counts
- Stops at next Tuesday after today (includes current week)
- High-resolution PNG output (300 DPI)

### Requirements

```bash
pip install matplotlib requests
```

### Usage

```bash
# Current year (default)
python scripts/github_history_chart.py

# Specific year
python scripts/github_history_chart.py --year 2025

# Since a specific date
python scripts/github_history_chart.py --since 2025-06-01
python scripts/github_history_chart.py --since "June 1, 2025"

# Custom output file
python scripts/github_history_chart.py --output my_chart.png

# Different repository
python scripts/github_history_chart.py --repo owner/repo

# With GitHub token (recommended)
GITHUB_TOKEN=$(gh auth token) python scripts/github_history_chart.py --year 2026
```

### GitHub Token Setup

For higher rate limits (5,000 requests/hour vs 60 without token):

1. Visit [GitHub Settings → Tokens](https://github.com/settings/tokens)
2. Generate new token (classic)
3. Select `public_repo` scope
4. Copy the token

Set as environment variable:

```bash
export GITHUB_TOKEN="your_token_here"
```

Or use GitHub CLI:

```bash
export GITHUB_TOKEN=$(gh auth token)
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--year` | Year to analyze | Current year |
| `--since` | Start date (YYYY-MM-DD, etc.) | None |
| `--repo` | Repository (owner/repo) | IBM/mcp-context-forge |
| `--token` | GitHub token | $GITHUB_TOKEN |
| `--output` | Output PNG file | github_history.png |
| `--help` | Show help message | - |

### Output

The script generates:

1. **PNG Chart** with dual y-axes:
   - Blue line (left axis): Open Issues
   - Purple line (right axis): Open PRs (non-draft)

2. **Console Output**:
   - Progress updates during data fetching
   - Summary statistics (averages, peaks)
   - Date range information

### Example Output

```
======================================================================
GitHub History Chart Generator
======================================================================

Analyzing repository: IBM/mcp-context-forge
Year: 2026 (through next Tuesday after today)
Output file: github_history_2026.png

Fetching all all issues...
  Fetched page 1: 44 issues (total: 44)
  ...
Total issues fetched: 2507

Fetching all all pull requests...
  Fetched page 1: 100 PRs (total: 100)
  ...
Total PRs fetched: 2623

Found 24 Tuesdays in the specified range
Date range: 2026-01-06 to 2026-06-16

Calculating open counts for each Tuesday...
  Tuesday 1/24 (2026-01-06): Issues: 332, PRs: 13
  ...
  Tuesday 24/24 (2026-06-16): Issues: 929, PRs: 208

Creating chart...
Chart saved to: github_history_2026.png

======================================================================
Summary Statistics
======================================================================
  Average open issues: 714.3
  Average open PRs:    110.6
  Max open issues:     929 (on 2026-06-16)
  Max open PRs:        208 (on 2026-06-16)
======================================================================
```

---

## 🔐 Authentication & Testing Scripts

### JWT Token Generator

**Location:** `scripts/test_email_auth_api.py`

Tests email-based authentication API endpoints.

### MCP Client Test

**Location:** `scripts/test_mcp_client.py`

Tests MCP protocol client connections.

### Token Scoping Test

**Location:** `scripts/test_mcp_token_scoping.py`

Tests token-based access control and scoping.

### REST API Endpoints Test

**Location:** `scripts/test_rest_api_endpoints.py`

Tests REST API endpoint functionality.

---

## 🧪 Benchmarking Scripts

### JSON Serialization Benchmark

**Location:** `scripts/benchmark_json_serialization.py`

Benchmarks JSON serialization performance across different libraries.

### Middleware Benchmark

**Location:** `scripts/benchmark_middleware.py`

Benchmarks middleware performance and overhead.

---

## 🔧 Maintenance Scripts

### Cleanup Orphaned Resources

**Location:** `scripts/cleanup_orphaned_resources.py`

Cleans up orphaned database resources.

### CDN Resources

**Location:** `scripts/cdn_resources.py`

Manages CDN resource downloads and updates.

### SRI Hash Generation

**Location:** `scripts/generate-sri-hashes.py`

Generates Subresource Integrity (SRI) hashes for static assets.

### SRI Hash Verification

**Location:** `scripts/verify-sri-hashes.py`

Verifies SRI hashes for static assets.

### License Checker

**Location:** `scripts/license_checker.py`

Checks dependency licenses for compliance.

---

## 🚀 Deployment Scripts

### ContextForge Setup

**Location:** `scripts/contextforge-setup.sh`

Automated setup script for ContextForge deployment.

### FedRAMP Validation

**Location:** `scripts/fedramp-validate.sh`

Validates FedRAMP compliance requirements.

---

## 🔍 Testing & Validation Scripts

### Compliance Matrix

**Location:** `scripts/compliance_matrix.py`

Generates compliance matrix for security standards.

### Native Extensions Verification

**Location:** `scripts/verify-native-extensions.py`

Verifies native extension builds and functionality.

### SQLite Test

**Location:** `scripts/test_sqlite.py`

Tests SQLite database functionality.

### SSO Flow Test

**Location:** `scripts/test-sso-flow.sh`

Tests Single Sign-On (SSO) authentication flow.

---

## 📦 CI/CD Scripts

Scripts in `scripts/ci/` support continuous integration and deployment:

- Build automation
- Test execution
- Deployment validation
- Release management

See individual scripts for detailed usage.

---

## 🛠 Pre-commit Scripts

Scripts in `scripts/pre-commit/` are used by pre-commit hooks:

- Code formatting checks
- Linting validation
- Security scanning
- Documentation generation

These are automatically run via `pre-commit` framework.

---

## 📚 Additional Resources

- [Building Locally](building.md) - Development environment setup
- [Testing](../testing/index.md) - Testing guidelines
- [Release Management](release-management.md) - Release process
- [GitHub Workflows](github.md) - CI/CD workflows
