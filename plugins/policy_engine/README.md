# Policy Engine Plugin for MCP Gateway

Integrates with Source Scanner to provide **automated security compliance checking** with policy evaluation, waiver management, and flexible exception handling.

## Overview

The Policy Engine plugin:
1. **Scans** repositories using [Source Scanner](../source_scanner) to find vulnerabilities
2. **Evaluates** findings against configurable security policies  
3. **Scores** compliance on a 0-100 scale
4. **Manages** exceptions through a waiver approval workflow
5. **Audits** all decisions for compliance reporting

---

## Quick Start

### Installation

```bash
# Navigate to project root
cd sweng26_group12_ibm_contextforge_security

# Install dependencies (if not already done)
pip install fastapi pydantic pytest
```

### Basic Workflow

```bash
# 1. Scan & apply policy 
python -m plugins.policy_engine.cli apply-policy --server <server_name> --repo <repo_url> --policy <policy_name>

# 2. If violations found, request a waiver
python -m plugins.policy_engine.cli ask-waiver --server <server_name> --rule <rule_name> --reason "<reason>" --days <duration>

# 3. Security team approves (if needed)
python -m plugins.policy_engine.cli approve-waiver --id <waiver_id> --by <approver_name>
```

---

## Commands

### `apply-policy` - Evaluate Against Policy

Checks scan results against a security policy and returns compliance decision. Can scan a repo directly with `--repo` or use previous scan results.

```bash
python -m plugins.policy_engine.cli apply-policy \
  --server <server_name> \
  --policy <policy_name> \
  --repo <repo_url> \
  --scan-file <optional_scan_file>
```

**Arguments:**
- `--server` (required): Server identifier
- `--policy` (required): Policy name (see `list-policies`)
- `--repo` (optional): Repository URL to scan (auto-scans if provided)
- `--scan-file` (optional): Scan results JSON (auto-finds latest if not provided)

**Output:**
```
============================================================
APPLYING POLICY: Production
Server: my-api
============================================================

Policy Evaluation Results:
  Decision:         BLOCK
  Compliance Score: 60.0%
  Status:           BLOCKED

Rule Results:
  ✗ FAIL: max_critical_vulnerabilities
         Found 2 critical vulnerabilities, exceeding limit of 0.
  ✓ PASS: sbom_required
         SBOM provided as required.

⚠️  Policy Violations Found!
   1 rule(s) need waivers to proceed
```

### `ask-waiver` - Request Exception

Creates a waiver request for a failed policy rule. Waivers require approval.

```bash
python -m plugins.policy_engine.cli ask-waiver \
  --server <server_name> \
  --rule <rule_name> \
  --reason "<reason>" \
  --days <duration>
```

**Arguments:**
- `--server` (required): Server identifier
- `--rule` (required): Rule being waived (e.g., `max_critical_vulnerabilities`)
- `--reason` (required): Business justification
- `--days` (optional): Duration in days (default: 7, max: 90)

**Output:**
```
============================================================
REQUESTING WAIVER
============================================================
Server:   my-api
Rule:     max_critical_vulnerabilities
Reason:   Critical CVE hotfix in progress
Duration: 7 days

✓ Waiver Request Created!
  Waiver ID:  550e8400-e29b-41d4-a716-446655440000
  Status:     pending
  Expires:    2026-03-17 10:30:45

⏳ Awaiting approval from security team...
```

### `approve-waiver` - Approve Exception (Admin)

Approves a pending waiver request. Once approved, the waiver takes effect immediately.

```bash
python -m plugins.policy_engine.cli approve-waiver \
  --id <waiver_id> \
  --by <approver_name>
```

**Arguments:**
- `--id` (required): Waiver ID (from `ask-waiver` output)
- `--by` (optional): Approver identifier (default: security-team)

### `list-policies` - Show Available Policies

Lists all configured security policies.

```bash
python -m plugins.policy_engine.cli list-policies
```

### `list-waivers` - Show Exceptions

Lists all active waivers, optionally filtered by server.

```bash
python -m plugins.policy_engine.cli list-waivers --server <server_name>
```

---

## Running the System

### Start Backend Server & UI

```bash
python -m uvicorn plugins.policy_engine.server:app --host 0.0.0.0 --port 8001 --reload
```

Access on `http://localhost:8001`

### API Endpoints

```bash
# Policies
curl http://localhost:8001/api/policy-engine/policies
curl http://localhost:8001/api/policy-engine/policies/<policy_id>
curl -X POST http://localhost:8001/api/policy-engine/policies -H "Content-Type: application/json" -d '{"name":"<name>","environment":"<env>","rules":{...}}'

# Waivers
curl http://localhost:8001/api/policy-engine/waivers
curl http://localhost:8001/api/policy-engine/waivers/pending
curl http://localhost:8001/api/policy-engine/waivers/active

# Dashboard
curl http://localhost:8001/api/dashboard/summary
```

### Tests

```bash
pytest plugins/policy_engine/tests/ -v --cov=plugins/policy_engine
```

---

## Policy Rules

### Available Rules

Each policy is configured with rules and thresholds:

| Rule | Type | Description | Values |
|------|------|-------------|--------|
| `max_critical_vulnerabilities` | number | Maximum critical issues (ERROR) | 0-N |
| `max_high_vulnerabilities` | number | Maximum high severity (WARNING) | 0-N |
| `sbom_required` | boolean | Require Software Bill of Materials | true/false |
| `min_trust_score` | number | Minimum trust score | 0-100 |
| `no_root_execution` | boolean | Prohibit root execution | true/false |

### Finding Levels

Scanner findings map to severity levels:

| Severity | Finding Type | Description |
|----------|--------------|-------------|
| **ERROR** | Critical Vulnerabilities | High-risk security issues (map to `error_count`) |
| **WARNING** | High Severity Issues | Important issues that should be resolved (map to `warning_count`) |
| **INFO** | Informational | Advisory findings and best practices |

---

## Complete Workflow Example

```bash
# 1. Scan a vulnerable repository
$ python -m plugins.policy_engine.cli scan --server api-service-v2.1 --repo https://github.com/company/api-service

============================================================
SCANNING: api-service-v2.1
Repository: https://github.com/company/api-service
============================================================

✓ Scan Complete!

Findings Summary:
  🔴 Critical (ERROR):  2
  🟠 High (WARNING):    5
  🟡 Info:              3
  Total Issues:         10

---

# 2. Apply production policy (very strict - 0 criticals allowed)
$ python -m plugins.policy_engine.cli apply-policy --server api-service-v2.1 --policy Production

============================================================
APPLYING POLICY: Production
Server: api-service-v2.1
============================================================

Policy Evaluation Results:
  Decision:         BLOCK
  Compliance Score: 60.0%
  Status:           BLOCKED

Rule Results:
  ✗ FAIL: max_critical_vulnerabilities
         Found 2 critical vulnerabilities, exceeding limit of 0.
  ✓ PASS: max_high_vulnerabilities
         Found 5 high vulnerabilities, within the limit of 3.
  ✓ PASS: sbom_required
         SBOM is required and provided.
  ✓ PASS: min_trust_score
         Trust score 85 meets the minimum required of 85.
  ✓ PASS: no_root_execution
         Container runs as non-root (OK).

⚠️  Policy Violations Found!
   1 rule(s) need waivers to proceed

---

# 3. Development team requests waiver for known CVE being fixed
$ python -m plugins.policy_engine.cli ask-waiver \
  --server api-service-v2.1 \
  --rule max_critical_vulnerabilities \
  --reason "CVE-2026-1234 hotfix scheduled for next sprint" \
  --days 14

============================================================
REQUESTING WAIVER
============================================================
Server:   api-service-v2.1
Rule:     max_critical_vulnerabilities
Reason:   CVE-2026-1234 hotfix scheduled for next sprint
Duration: 14 days

✓ Waiver Request Created!
  Waiver ID:  a1b2c3d4-e5f6-7890-abcd-ef1234567890
  Status:     pending
  Expires:    2026-03-24 15:45:30

⏳ Awaiting approval from security team...

---

# 4. Security team approves the waiver
$ python -m plugins.policy_engine.cli approve-waiver \
  --id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --by security-lead

Approving waiver a1b2c3d4-e5f6-7890-abcd-ef1234567890...

✓ Waiver Approved!
  Status: approved

---

# 5. Re-evaluate with approved waiver - now passes!
$ python -m plugins.policy_engine.cli apply-policy --server api-service-v2.1 --policy Production

Policy Evaluation Results:
  Decision:         ALLOW  
  Compliance Score: 100.0%
  Status:           PASSED

Rule Results:
  ✓ PASS (WAIVED): max_critical_vulnerabilities
                   Exception approved until 2026-03-24
  ✓ PASS: max_high_vulnerabilities
         Found 5 high vulnerabilities, within the limit of 3.
  ✓ PASS: sbom_required
         SBOM is required and provided.
  ✓ PASS: min_trust_score
         Trust score 85 meets the minimum required of 85.
  ✓ PASS: no_root_execution
         Container runs as non-root (OK).

✓ Service approved for deployment!
```

---

## Core Components

| File | Purpose |
|------|---------|
| `cli.py` | Command-line interface for all operations |
| `plugin.py` | Plugin entry point and main logic |
| `evaluator.py` | Policy evaluation engine |
| `rules.py` | Individual rule evaluators (5 types) |
| `waivers.py` | Waiver lifecycle and expiration |
| `models.py` | Pydantic data schemas |
| `api.py` | REST API endpoints |
| `admin.py` | Admin dashboard routes |

---

## Testing

```bash
# Run all tests
pytest plugins/policy_engine/tests/ -v

# Run specific test file  
pytest plugins/policy_engine/tests/test_rules.py -v
pytest plugins/policy_engine/tests/test_evaluator.py -v
pytest plugins/policy_engine/tests/test_waivers.py -v
```

**Test Coverage:** 50+ tests covering all components

---

## Architecture

```
CLI (cli.py)
    ↓
Plugin (plugin.py)
    ├─→ Scanner (from source_scanner plugin)
    └─→ Engine:
         ├─→ Evaluator (evaluator.py)
         ├─→ Rules (rules.py)
         └─→ Waivers (waivers.py)
```

---

## Compliance Scoring

- **Rule Passed:** 100% of score weight
- **Rule Waived:** 100% of score weight
- **Rule Failed:** 0% of score weight

Example: 3 pass + 1 waived + 1 failed out of 5 = (3 + 1) / 5 × 100 = **80%**

---

## Waiver Lifecycle

1. **Request:** Developer creates waiver with reason and duration
2. **Pending:** Waiver awaits security team approval  
3. **Approved:** Waiver takes effect immediately
4. **Active:** Waiver covers failed rule until expiration
5. **Expired:** Auto-removed after duration ends

---

## Status Meanings

| Status | Condition |
|--------|-----------|
| **PASSED** | All rules passed |
| **WARNED** | All passed but warnings exist |
| **BLOCKED** | Unwaived failures exist |

---

## Adding a New Rule

> **Note:** Since there is no database connection, available rules are stored as a static list in `models.py` (`AVAILABLE_RULES`). This list drives what appears in the Policy Management UI dropdown. To add a new rule to the system, the following 3 files must be updated:

1. **`models.py`** — Add the new rule to the `AVAILABLE_RULES` list with a name, description, and type (`number` or `boolean`). This makes it appear in the UI edit/create modal.

2. **`rules.py`** — Add a new evaluator class with the logic that checks the rule against scan findings, then register it in `RuleEvaluatorFactory.EVALUATORS` so the engine can invoke it during policy evaluation.

3. **`templates/polices.yaml`** *(optional)* — Add the rule with a default value to any of the three default policies (Dev, Standard, Production). If skipped, the rule still appears in the UI but won't be active in any policy until an admin explicitly adds it via the Policy Management page.

---

## Support

For issues or questions, see related plugins and documentation:
- **Source Scanner Plugin:** `../source_scanner/README.md`
- **Related Issue:** GitHub #2219 - Policy Engine Implementation

---

**Status:** ✅ Complete and Ready  
**Last Updated:** March 10, 2026
