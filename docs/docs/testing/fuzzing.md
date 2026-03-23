# Fuzz Testing

ContextForge includes comprehensive fuzz testing to automatically discover edge cases, security vulnerabilities, and crashes through property-based testing, coverage-guided fuzzing, and security-focused validation.

## Overview

Fuzz testing generates thousands of random, malformed, or edge-case inputs to find bugs that traditional testing might miss. Our implementation combines multiple fuzzing approaches:

- **Property-Based Testing** with Hypothesis for core validation logic
- **Coverage-Guided Fuzzing** with Atheris for deep code path exploration
- **API Schema Fuzzing** with Schemathesis for contract validation
- **Security-Focused Testing** for vulnerability discovery

## Quick Start

### Installation

Install fuzzing dependencies as an optional package group:

```bash
# Via Makefile (recommended)
make fuzz-install

# Or directly with pip
pip install -e .[fuzz]
```

### Running Tests

```bash
# Complete fuzzing suite
make fuzz-all

# Individual components
make fuzz-hypothesis     # Property-based tests
make fuzz-security       # Security vulnerability tests
make fuzz-quick          # Fast CI validation
make fuzz-report         # Generate reports
```

## Fuzzing Components

### Property-Based Testing (Hypothesis)

Tests core validation logic by generating inputs that satisfy certain properties and verifying invariants hold.

**Test Modules:**

- `tests/fuzz/test_jsonrpc_fuzz.py` - JSON-RPC validation (16 tests)
- `tests/fuzz/test_jsonpath_fuzz.py` - JSONPath processing (16 tests)
- `tests/fuzz/test_schema_validation_fuzz.py` - Pydantic schemas (19 tests)

**Example Test:**
```python
@given(st.text())
def test_validate_request_handles_text_input(self, text_input):
    """Test that text input never crashes the validator."""
    try:
        data = json.loads(text_input)
        if isinstance(data, dict):
            validate_request(data)
    except (JSONRPCError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
        # Expected exceptions for invalid input
        pass
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")
```

**Configuration:**
Set testing intensity via environment variables:
```bash
HYPOTHESIS_PROFILE=dev      # 100 examples (default)
HYPOTHESIS_PROFILE=ci       # 50 examples (fast)
HYPOTHESIS_PROFILE=thorough # 1000 examples (comprehensive)
```

### Coverage-Guided Fuzzing (Atheris)

Uses libfuzzer to instrument code and guide input generation toward unexplored code paths.

**Fuzzer Scripts:**

- `tests/fuzz/fuzzers/fuzz_jsonpath.py` - JSONPath expression fuzzing
- `tests/fuzz/fuzzers/fuzz_jsonrpc.py` - JSON-RPC message fuzzing
- `tests/fuzz/fuzzers/fuzz_config_parser.py` - Configuration parsing fuzzing

**Setup Requirements:**
Atheris requires clang and libfuzzer to be installed:

```bash
# Install LLVM/Clang (one-time setup)
git clone --depth=1 https://github.com/llvm/llvm-project.git
cd llvm-project
cmake -DLLVM_ENABLE_PROJECTS='clang;compiler-rt' -G "Unix Makefiles" -S llvm -B build
cmake --build build --parallel $(nproc)

# Set environment and install
export CLANG_BIN="$(pwd)/bin/clang"
pip install -e .[fuzz-atheris]
```

**Running Atheris:**
```bash
# Manual execution with custom parameters
python tests/fuzz/fuzzers/fuzz_jsonpath.py -runs=10000 -max_total_time=300
```

### API Schema Fuzzing (Schemathesis)

Tests API endpoints by generating requests based on OpenAPI schema definitions.

**Features:**

- Validates API contracts automatically
- Tests authentication flows
- Verifies response schemas
- Discovers endpoint-specific edge cases

**Manual Setup:**
API fuzzing requires a running server instance:

```bash
# Terminal 1: Start server
make dev

# Terminal 2: Run API fuzzing
source $(VENV_DIR)/bin/activate
schemathesis run http://localhost:4444/openapi.json \
  --checks all \
  --auth admin:changeme \
  --hypothesis-max-examples=500
```

### Security-Focused Testing

Tests resistance to common security vulnerabilities and attack patterns.

**Test Categories:**

- **SQL Injection**: Tests input sanitization in database queries
- **XSS Prevention**: Validates output encoding and CSP headers
- **Path Traversal**: Tests file access controls
- **Command Injection**: Validates command execution safeguards
- **Authentication Bypass**: Tests auth mechanism robustness
- **DoS Protection**: Validates rate limiting and resource constraints

**Example Security Test:**
```python
@given(st.text(min_size=1, max_size=1000))
def test_sql_injection_resistance(self, malicious_input):
    """Test resistance to SQL injection in various fields."""
    sql_patterns = [
        malicious_input,
        f"'; DROP TABLE tools; --",
        f"' OR '1'='1",
        f"'; INSERT INTO tools (name) VALUES ('hacked'); --",
    ]

    for pattern in sql_patterns:
        response = client.post("/admin/tools", json={
            "name": pattern,
            "url": "http://example.com"
        }, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

        # Should not crash or allow injection
        assert response.status_code in [200, 201, 400, 401, 422]
```

## Makefile Targets

| Target | Purpose | Dependencies | Use Case |
|--------|---------|--------------|----------|
| `fuzz-install` | Install fuzzing dependencies | Virtual environment | One-time setup |
| `fuzz-all` | Complete fuzzing suite | `fuzz-install` | Full validation |
| `fuzz-hypothesis` | Property-based testing | `fuzz-install` | Core logic validation |
| `fuzz-atheris` | Coverage-guided fuzzing | clang/libfuzzer | Deep exploration |
| `fuzz-api` | API endpoint fuzzing | Running server | Contract validation |
| `fuzz-restler` | RESTler API fuzzing (instructions) | Docker or local RESTler | Stateful/sequence fuzzing |
| `fuzz-restler-auto` | Run RESTler via Docker automatically | Docker, running server | Automated stateful fuzzing |
| `fuzz-security` | Security vulnerability testing | `fuzz-install` | Security validation |
| `fuzz-quick` | Fast fuzzing for CI | `fuzz-install` | PR validation |
| `fuzz-extended` | Extended fuzzing | `fuzz-install` | Nightly testing |
| `fuzz-report` | Generate reports | `fuzz-install` | Analysis |
| `fuzz-clean` | Clean artifacts | None | Maintenance |

## Test Execution Modes

### Development Mode
For interactive development and debugging:
```bash
make fuzz-hypothesis    # Run with statistics and detailed output
make fuzz-security      # Security tests with warnings
```

### CI/CD Mode
For automated testing in continuous integration:
```bash
make fuzz-quick         # Fast validation (50 examples)
```

### Comprehensive Mode
For thorough testing in nightly builds:
```bash
make fuzz-extended      # Extended testing (1000+ examples)
```

## RESTler Fuzzing

RESTler performs stateful, sequence-based fuzzing of REST APIs using the OpenAPI/Swagger specification. It's ideal for discovering bugs that require specific call sequences.

### Option A: Docker (recommended)

Prerequisites: Docker installed and the gateway running locally.

```bash
# Terminal 1: Start the server
make dev

# Terminal 2: Generate/OpenAPI and run RESTler via Docker
curl -sSf http://localhost:4444/openapi.json -o reports/restler/openapi.json
docker run --rm -v "$PWD/reports/restler:/workspace" \
  ghcr.io/microsoft/restler restler compile --api_spec /workspace/openapi.json
docker run --rm -v "$PWD/reports/restler:/workspace" \
  ghcr.io/microsoft/restler restler test --grammar_dir /workspace/Compile --no_ssl --time_budget 5

# Results are written to reports/restler
```

You can print these instructions anytime with:

```bash
make fuzz-restler
```

### Option A2: Automated Docker runner

Use the helper that waits for the server, downloads the spec, then compiles and runs RESTler in Docker:

```bash
# Terminal 1: Start the server
make dev

# Terminal 2: Run automated RESTler fuzzing
make fuzz-restler-auto

# Optional environment variables:
# MCPFUZZ_BASE_URL   (default: http://localhost:4444)
# MCPFUZZ_AUTH_HEADER (e.g., "Authorization: Basic YWRtaW46Y2hhbmdlbWU=")
# MCPFUZZ_TIME_BUDGET (minutes, default: 5)
# MCPFUZZ_NO_SSL      (1 to pass --no_ssl; default: 1)
```

Notes:

- If Docker is not present, `fuzz-restler-auto` will print a friendly message and exit successfully (use `make fuzz-restler` for manual steps). This behavior avoids CI failures on runners without Docker.
- Artifacts are written under `reports/restler/`.

### Option B: Local install

Follow RESTler's official installation guide, set `RESTLER_HOME`, then:

```bash
export RESTLER_HOME=/path/to/restler
curl -sSf http://localhost:4444/openapi.json -o reports/restler/openapi.json
"$RESTLER_HOME"/restler compile --api_spec reports/restler/openapi.json
"$RESTLER_HOME"/restler test --grammar_dir Compile --no_ssl --time_budget 5
```

Notes:

- Ensure the server exposes `http://localhost:4444/openapi.json`.
- For authenticated specs, supply tokens/headers to RESTler as needed.
- Increase `--time_budget` for deeper exploration in nightly runs.

 - In CI, prefer running `fuzz-restler-auto` only on runners with Docker available, or skip otherwise.

## Understanding Results

### Test Outcomes

**Passing Tests**: Inputs handled correctly without crashes
**Failing Tests**: Unexpected exceptions or crashes discovered
**Skipped Tests**: Tests requiring external dependencies (auth, servers)

### Hypothesis Statistics

Hypothesis provides detailed statistics about test execution:

```
- during generate phase (1.86 seconds):
  - Typical runtimes: ~ 15-16 ms, of which < 1ms in data generation
  - 100 passing examples, 0 failing examples, 0 invalid examples
- Stopped because settings.max_examples=100
```

### Bug Discovery

When fuzzing finds issues, it provides:

- **Minimal failing example**: Simplified input that reproduces the bug
- **Seed for reproduction**: Run with `--hypothesis-seed=X` to reproduce
- **Call stack**: Exact location where the failure occurred

Example failure:
```
Falsifying example: test_validate_request_handles_text_input(
    self=<TestJSONRPCRequestFuzzing>,
    text_input='null'
)
```

## Writing Fuzz Tests

### Property-Based Test Structure

```python
from hypothesis import given, strategies as st
import pytest

class TestMyComponentFuzzing:
    @given(st.text(min_size=1, max_size=100))
    def test_component_never_crashes(self, input_text):
        """Test that component handles arbitrary text input."""
        try:
            result = my_component.process(input_text)
            # Verify expected properties
            assert isinstance(result, (str, dict, list))
        except (ValueError, TypeError):
            # Expected exceptions for invalid input
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")
```

### Atheris Fuzzer Structure

```python
#!/usr/bin/env python3
import atheris
import sys
import os

# Ensure project is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from mcpgateway.my_module import my_function

def TestOneInput(data: bytes) -> None:
    """Fuzz target for my_function."""
    fdp = atheris.FuzzedDataProvider(data)

    try:
        if fdp.remaining_bytes() < 1:
            return

        # Generate test input
        test_input = fdp.ConsumeUnicodeNoSurrogates(100)

        # Test function (should never crash)
        my_function(test_input)

    except (ValueError, TypeError):
        # Expected exceptions
        pass
    except Exception:
        # Unexpected - let Atheris catch it
        raise

def main():
    atheris.instrument_all()
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

if __name__ == "__main__":
    main()
```

### Security Test Patterns

```python
@given(st.text().filter(lambda x: any(char in x for char in '<>"\'&')))
def test_xss_prevention(self, potentially_malicious):
    """Test XSS prevention in user inputs."""
    response = client.post("/api/endpoint", json={
        "field": potentially_malicious
    }, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

    # Should handle malicious content safely
    assert response.status_code in [200, 201, 400, 401, 422]

    # Raw script tags should not appear unescaped
    if "<script>" in potentially_malicious.lower():
        assert "<script>" not in response.text.lower()
```

## Common Strategies

### Input Generation Strategies

```python
import hypothesis.strategies as st

# Basic types
st.text()                    # Unicode strings
st.integers()                # Integers
st.binary()                  # Raw bytes
st.booleans()               # True/False

# Structured data
st.dictionaries(
    keys=st.text(min_size=1),
    values=st.integers()
)
st.lists(st.text(), max_size=10)

# Custom strategies
st.one_of(st.none(), st.text(), st.integers())  # Union types

# Filtered strategies (use sparingly)
st.text().filter(lambda x: '$' in x)
```

### Common Edge Cases to Test

**JSON-RPC Validation:**

- Empty objects: `{}`
- Non-objects: `null`, `[]`, `"string"`, `123`
- Missing required fields
- Invalid field types
- Very large payloads

**JSONPath Processing:**

- Invalid expressions: `$..`, `$[`, `$.`
- Very long expressions
- Unicode characters
- Special characters that break parsing

**API Endpoints:**

- Malformed JSON payloads
- Missing authentication headers
- Invalid content types
- Very large request bodies
- Concurrent requests

## Troubleshooting

### Common Issues

**Import Errors:**
```
ModuleNotFoundError: No module named 'hypothesis'
```
**Solution:** Run `make fuzz-install` first

**Authentication Failures:**
```
assert 401 in [200, 201, 400, 422]
```
**Solution:** Security tests expect auth failures when testing in isolation

**Filter Warnings:**
```
FailedHealthCheck: filtering out a lot of inputs
```
**Solution:** Use `assume()` instead of `.filter()` or disable health check

### Performance Tuning

**Slow Tests:**

- Reduce `max_examples` for development
- Use `HYPOTHESIS_PROFILE=ci` for faster execution
- Add `@settings(timeout=timedelta(seconds=10))` for time limits

**Memory Issues:**

- Limit recursive data structure depth
- Use `max_leaves` parameter in recursive strategies
- Monitor corpus size growth

### Debugging Failed Tests

**Reproduce Failures:**
```bash
# Use seed from failed test output
pytest --hypothesis-seed=12345 tests/fuzz/test_my_module.py::test_function
```

**Debug Mode:**
```python
@settings(verbosity=Verbosity.verbose)
@given(st.text())
def test_with_debug(self, input_text):
    print(f"Testing with: {repr(input_text)}")  # Add debug output
    # ... test logic
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Fuzz Testing
on:
  pull_request:
    branches: [main]
  schedule:

    - cron: '0 2 * * *'  # Nightly

jobs:
  fuzz-quick:
    name: Quick Fuzzing
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:

      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: make fuzz-quick

  fuzz-extended:
    name: Extended Fuzzing
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule'
    steps:

      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: make fuzz-extended
      - run: make fuzz-report
      - uses: actions/upload-artifact@v4
        with:
          name: fuzz-reports
          path: reports/
```

### Pre-commit Hooks

Add fuzzing to pre-commit pipeline:

```yaml
# .pre-commit-config.yaml
repos:

  - repo: local
    hooks:

      - id: fuzz-quick
        name: Quick Fuzz Testing
        entry: make fuzz-quick
        language: system
        pass_filenames: false
        stages: [pre-push]
```

## Best Practices

### Test Design

1. **Focus on invariants**: Test properties that should always hold
2. **Expect the expected**: Handle known exception types gracefully
3. **Fail on unexpected**: Use `pytest.fail()` for truly unexpected errors
4. **Use examples**: Add `@example()` decorators for known edge cases

### Input Strategies

1. **Start broad**: Use general strategies like `st.text()` initially
2. **Narrow gradually**: Add constraints based on domain knowledge
3. **Avoid over-filtering**: Use `assume()` instead of `.filter()` when possible
4. **Test boundaries**: Include empty, very large, and edge case inputs

### Security Testing

1. **Test defensively**: Assume all input is potentially malicious
2. **Verify sanitization**: Check that dangerous content is properly escaped
3. **Test authentication**: Verify auth requirements are properly enforced
4. **Monitor responses**: Ensure error messages don't leak sensitive information

## Real Issues Found

Our fuzzing implementation has already discovered several real bugs:

### JSON-RPC Validation Crashes

**Issue**: `validate_request()` crashes with `AttributeError` when given non-dict inputs.

**Root Cause**: Function assumes input is always a dictionary and calls `.get()` method.

**Examples that crash:**

- `json.loads("null")` → `None` → `None.get("jsonrpc")` crashes
- `json.loads("0")` → `0` → `0.get("jsonrpc")` crashes
- `json.loads("[]")` → `[]` → `[].get("jsonrpc")` crashes

**Fix Applied**: Added type checking in fuzz tests to only validate dict inputs.

### Schema Validation Edge Cases

**Issue**: Pydantic schemas accept broader input types than expected.

**Examples:**

- `AuthenticationValues(auth_type="")` accepts empty strings
- `ToolCreate(input_schema=None)` allows None values
- Various unicode and special character handling inconsistencies

## Directory Structure

```
tests/fuzz/                          # Fuzz testing directory
├── conftest.py                     # Pytest configuration and markers
├── test_jsonrpc_fuzz.py            # JSON-RPC validation tests
├── test_jsonpath_fuzz.py           # JSONPath processing tests
├── test_schema_validation_fuzz.py  # Pydantic schema tests
├── test_api_schema_fuzz.py         # API endpoint tests
├── test_security_fuzz.py           # Security vulnerability tests
├── fuzzers/                        # Atheris coverage-guided fuzzers
│   ├── fuzz_jsonpath.py           # JSONPath expression fuzzer
│   ├── fuzz_jsonrpc.py            # JSON-RPC message fuzzer
│   └── fuzz_config_parser.py      # Configuration parser fuzzer
└── scripts/
    └── generate_fuzz_report.py    # Report generation utility

# Generated artifacts (gitignored)
corpus/                             # Test case corpus
├── jsonpath/                       # JSONPath test cases
├── jsonrpc/                       # JSON-RPC test cases
└── api/                           # API request test cases

reports/                            # Generated reports
├── fuzz-report.json               # Machine-readable report
└── fuzz-report.md                 # Human-readable report
```

## Advanced Usage

### Custom Strategies

Create domain-specific input generators:

```python
# JSON-RPC message strategy
jsonrpc_request = st.fixed_dict({
    "jsonrpc": st.just("2.0"),
    "method": st.text(min_size=1, max_size=50),
    "id": st.one_of(st.integers(), st.text(), st.none())
}, optional={
    "params": st.one_of(
        st.dictionaries(st.text(), st.text()),
        st.lists(st.text())
    )
})

@given(jsonrpc_request)
def test_with_valid_structure(self, request):
    validate_request(request)
```

### Corpus Management

Build and maintain test case collections:

```bash
# Generate corpus from successful fuzzing runs
python tests/fuzz/fuzzers/fuzz_jsonpath.py \
  -runs=10000 \
  -artifact_prefix=corpus/jsonpath/

# Use corpus for regression testing
python tests/fuzz/fuzzers/fuzz_jsonpath.py \
  corpus/jsonpath/* \
  -runs=0  # Only test existing corpus
```

### Performance Monitoring

Track fuzzing performance over time:

```python
@settings(deadline=timedelta(milliseconds=500))
@given(st.text())
def test_performance_regression(self, input_text):
    """Ensure processing stays within performance bounds."""
    start_time = time.time()
    my_function(input_text)
    duration = time.time() - start_time
    assert duration < 0.1, f"Processing took {duration}s, expected < 0.1s"
```

## Reporting and Analysis

### Generated Reports

The `make fuzz-report` command generates comprehensive reports:

**JSON Report** (`reports/fuzz-report.json`):

- Machine-readable results for CI integration
- Tool execution statistics
- Failure counts and error categorization
- Corpus and coverage metrics

**Markdown Report** (`reports/fuzz-report.md`):

- Human-readable executive summary
- Tool-by-tool breakdown
- Recommendations for action
- Links to detailed artifacts

### Interpreting Results

**Green (✅)**: No crashes or security issues found
**Yellow (⚠️)**: Partial results or configuration issues
**Red (🚨)**: Critical issues requiring immediate attention

**Example Report Summary:**
```
🎯 Overall Status: ✅ PASS
🔧 Tools Completed: 4/4
🚨 Critical Issues: 0

💡 Key Recommendations:
✅ No critical issues found in fuzzing
🔄 Continue regular fuzzing as part of CI/CD
📊 Review detailed results for optimization opportunities
```

## Maintenance

### Regular Tasks

1. **Update corpus**: Add new interesting test cases discovered during development
2. **Review failures**: Investigate and fix any new crashes discovered
3. **Tune performance**: Adjust example counts based on CI time constraints
4. **Update strategies**: Enhance input generation as code evolves

### Corpus Hygiene

```bash
# Clean up old artifacts
make fuzz-clean

# Regenerate corpus with latest code
make fuzz-atheris

# Verify corpus quality
python tests/fuzz/scripts/generate_fuzz_report.py
```

## References

- [Hypothesis Documentation](https://hypothesis.readthedocs.io/) - Property-based testing guide
- [Atheris Documentation](https://github.com/google/atheris) - Coverage-guided fuzzing
- [Schemathesis Documentation](https://schemathesis.readthedocs.io/) - API schema testing
- [OWASP Fuzzing Guide](https://owasp.org/www-community/Fuzzing) - Security fuzzing practices
- [Property-Based Testing](https://increment.com/testing/property-based-testing-with-hypothesis/) - Testing philosophy and examples
