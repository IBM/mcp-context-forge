# Quick Start: Running Tests

This guide gets you up and running with tests in under 5 minutes.

## Step 1: Navigate to Test Directory

```bash
cd /path/to/outputs
ls -l mcp_audit_*.py test_mcp_audit*.py
```

You should see:
- `mcp_audit_models.py`
- `mcp_audit_database.py`
- `mcp_audit_service.py`
- `mcp_audit_siem.py`
- `mcp_audit_api.py`
- `test_mcp_audit.py`
- `test_mcp_audit_comprehensive.py`

## Step 2: Choose Your Testing Method

### Option A: Quick Test (No Dependencies) ⚡

**Fastest way to verify everything works:**

```bash
python3 test_mcp_audit.py
```

**Expected output:**
```
======================================================================
MCP Audit System Tests (GitHub Issue #2225)
======================================================================

▶ Create audit decision record... ✓ PASSED
▶ Convert record to dict (GitHub schema)... ✓ PASSED
...
======================================================================
Results: 16 passed, 0 failed
======================================================================
```

✅ **Done!** If all 16 tests pass, your system is working correctly.

---

### Option B: Full Test Suite (Recommended) 🔬

**For comprehensive testing with detailed reports:**

#### 1. Install pytest:

```bash
pip install pytest pytest-asyncio --break-system-packages
```

Or with virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install pytest pytest-asyncio
```

#### 2. Run tests:

```bash
pytest test_mcp_audit_comprehensive.py -v
```

**Expected output:**
```
test_mcp_audit_comprehensive.py::TestAuditModels::test_subject_details_creation PASSED
test_mcp_audit_comprehensive.py::TestAuditModels::test_subject_to_dict PASSED
...
============================== 45 passed in 2.54s ===============================
```

✅ **Done!** All 45+ comprehensive tests passed.

---

### Option C: Automated Test Script 🤖

**Use the provided shell script:**

```bash
# Make it executable (first time only)
chmod +x run_all_tests.sh

# Run all tests
./run_all_tests.sh

# Or run quick tests
./run_all_tests.sh --quick

# Or run with coverage
./run_all_tests.sh --cov
```

---

## Step 3: Understanding Results

### Success ✅

```
======================================================================
Results: 16 passed, 0 failed
======================================================================
```

All tests passed! Your implementation is working correctly.

### Failure ❌

```
▶ Some test name... ✗ FAILED: assertion error message
```

If you see failures:
1. Read the error message
2. Check that all `mcp_audit_*.py` files are present
3. Verify Python version (requires 3.8+)
4. Check for import errors

---

## Common Commands

```bash
# Basic quick test
python3 test_mcp_audit.py

# Full test suite
pytest test_mcp_audit_comprehensive.py -v

# With coverage report
pytest test_mcp_audit_comprehensive.py --cov=. --cov-report=html
open htmlcov/index.html

# Run specific test class
pytest test_mcp_audit_comprehensive.py::TestAuditModels -v

# Run only database tests
pytest test_mcp_audit_comprehensive.py::TestAuditDatabase -v

# Stop on first failure
pytest test_mcp_audit_comprehensive.py -x

# Show what each test does
pytest test_mcp_audit_comprehensive.py -v -s
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'pytest'"

```bash
pip install pytest pytest-asyncio --break-system-packages
```

### "ModuleNotFoundError: No module named 'mcp_audit_models'"

Make sure you're in the directory with all the files:
```bash
ls -l mcp_audit_*.py
```

### "Permission denied: ./run_all_tests.sh"

```bash
chmod +x run_all_tests.sh
```

### Tests are slow

Run in parallel:
```bash
pip install pytest-xdist --break-system-packages
pytest test_mcp_audit_comprehensive.py -n auto
```

---

## What Tests Cover

### ✅ Model Tests (15 tests)
- Data model creation and validation
- JSON/dict serialization
- SIEM format conversion (Splunk, Elasticsearch, Webhook)
- Configuration models

### ✅ Database Tests (15 tests)
- Schema creation
- CRUD operations
- Query filtering (subject, resource, decision, time)
- Pagination
- Statistics calculation
- Retention management

### ✅ Service Tests (6 tests)
- Service initialization
- Decision logging
- Configuration controls
- Query API

### ✅ Integration Tests (2+ tests)
- MAC policy workflow
- RBAC policy workflow
- End-to-end scenarios

**Total: 45+ comprehensive tests**

---

## Next Steps

1. ✅ Run `python3 test_mcp_audit.py` to verify basic functionality
2. ✅ Install pytest and run full suite
3. ✅ Review test coverage with `--cov`
4. ✅ Add your own tests for custom features

---

## Full Documentation

- **Comprehensive Testing Guide**: See `TESTING_GUIDE.md`
- **Implementation Details**: See `MCP_AUDIT_IMPLEMENTATION.md`
- **API Usage**: See `mcp_audit_example.py`

---

## Questions?

If you encounter issues:
1. Check Python version: `python3 --version` (need 3.8+)
2. Verify all files are present: `ls -l mcp_audit_*.py`
3. Check test output for specific error messages
4. See TESTING_GUIDE.md for advanced troubleshooting
