# Doctest Coverage

This page documents the comprehensive doctest coverage implementation in MCP Context Forge, which ensures that all code examples in documentation are tested and verified automatically.

---

## Overview

MCP Context Forge implements comprehensive doctest coverage across all modules to ensure:

- **Code Quality**: All documented examples are tested and verified
- **Documentation Accuracy**: Examples in docstrings are always up-to-date with actual code behavior
- **Developer Experience**: Developers can run examples directly from documentation
- **Regression Prevention**: Changes that break documented behavior are caught early

## What is Doctest?

Doctest is a Python testing framework that extracts interactive examples from docstrings and runs them as tests. It's built into Python's standard library and provides:

- **Inline Testing**: Examples in docstrings are automatically tested
- **Documentation Verification**: Ensures examples match actual code behavior
- **Google Style Support**: Works seamlessly with Google-style docstrings
- **CI/CD Integration**: Can be integrated into automated testing pipelines

## Coverage Status

### Current Focus

| Area | Status | Notes |
| ---- | ------ | ----- |
| Core transports & utilities | ✅ Doctest examples live directly in the modules (e.g. `mcpgateway/transports/*`, `mcpgateway/config.py`, `mcpgateway/wrapper.py`) |
| Service layer | 🔄 Many high-traffic services include doctests, but coverage is being expanded as modules are touched |
| Validators & schemas | ✅ JSON-RPC validation, slug helpers, and schema models ship with doctest-backed examples |
| Remaining modules | 🚧 Add doctests opportunistically when new behaviour is introduced |

### Key modules with doctests today

The following modules already contain runnable doctest examples you can reference when adding new ones:

- `mcpgateway/transports/base.py`, `stdio_transport.py`, `sse_transport.py`, `streamablehttp_transport.py`
- `mcpgateway/cache/session_registry.py` (initialisation handshake and SSE helpers)
- `mcpgateway/config.py` and supporting validators
- `mcpgateway/utils/create_jwt_token.py`
- `mcpgateway/wrapper.py` (URL conversion, logging toggles)
- `mcpgateway/validation/jsonrpc.py`

## Running Doctests

### Local Development

```bash
# Run all doctests
make doctest

# Run with verbose output
make doctest-verbose

# Generate coverage report
make doctest-coverage

# Check coverage percentage (fails if < 100%)
make doctest-check
```

### Individual Modules

```bash
# Test a specific module
python -m doctest mcpgateway/transports/base.py -v

# Test with programmatic approach
python -c "import doctest; doctest.testmod(mcpgateway.transports.base)"
```

### CI/CD Integration

Doctests are automatically run in the GitHub Actions pipeline:

```yaml
# .github/workflows/pytest.yml
- name: "📊  Doctest coverage with threshold"
  run: |
    pytest --doctest-modules mcpgateway/ \
      --cov=mcpgateway \
      --cov-report=term \
      --cov-report=json:doctest-coverage.json \
      --cov-fail-under=40 \
      --tb=short

- name: "📊  Doctest coverage validation"
  run: |
    python -m pytest --doctest-modules mcpgateway/ --tb=no -q
```

## Doctest Standards

### Google Docstring Format

All doctests follow the Google docstring format with an "Examples:" section:

```python
def create_slug(text: str) -> str:
    """Convert text to URL-friendly slug.

    Args:
        text: Input text to convert

    Returns:
        URL-friendly slug string

    Examples:
        >>> create_slug("Hello World!")
        'hello-world'

        >>> create_slug("Special@#$Characters")
        'special-characters'

        >>> create_slug("  Multiple   Spaces  ")
        'multiple-spaces'
    """
    # Implementation here
```

### Best Practices

1. **Comprehensive Examples**: Cover normal cases, edge cases, and error conditions
2. **Async Support**: Use `asyncio.run()` for async function examples
3. **Mock Objects**: Use `unittest.mock` for external dependencies
4. **Clear Expectations**: Make expected output obvious and unambiguous
5. **Error Testing**: Include examples that demonstrate error handling

### Async Function Examples

```python
async def connect(self) -> None:
    """Set up transport connection.

    Examples:
        >>> transport = MyTransport()
        >>> import asyncio
        >>> asyncio.run(transport.connect())
        >>> transport.is_connected()
        True
    """
```

### Mock Usage Examples

```python
def send_message(self, message: Dict[str, Any]) -> None:
    """Send message over transport.

    Examples:
        >>> from unittest.mock import Mock, AsyncMock
        >>> mock_transport = Mock()
        >>> mock_transport.send = AsyncMock()
        >>> import asyncio
        >>> asyncio.run(mock_transport.send({"test": "data"}))
        >>> mock_transport.send.called
        True
    """
```

## Pre-commit Integration

The default `.pre-commit-config.yaml` ships with a doctest hook commented out. Enable it locally by uncommenting the block (or copying the snippet below) if you want doctests to run on every commit:

```yaml
- repo: local
  hooks:

    - id: doctest
      name: Doctest
      entry: pytest --doctest-modules mcpgateway/ --tb=short
      language: system
      types: [python]
```

When enabled, the hook blocks commits until doctests pass—handy if you're touching modules with extensive inline examples.

## Coverage Metrics

- `make doctest-coverage` writes an HTML report to `htmlcov-doctest/` and an XML summary to `coverage-doctest.xml`.
- GitHub Actions currently enforces a doctest coverage floor of **40%** via `--cov-fail-under=40`.
- Use `coverage json -o doctest-coverage.json` (already produced in CI) or `coverage report` locally to inspect specific modules.

### Coverage Goals

1. Keep transports, config validators, and request/response helpers covered with runnable examples.
2. Add doctests alongside new service-layer logic instead of backfilling everything at once.
3. Promote tricky bug fixes into doctest examples so regressions surface quickly.

## Contributing Guidelines

### Adding Doctests

When adding new functions or methods:

1. **Include Examples**: Always add an "Examples:" section to docstrings
2. **Test Edge Cases**: Cover normal usage, edge cases, and error conditions
3. **Use Google Format**: Follow the established Google docstring format
4. **Async Support**: Use `asyncio.run()` for async functions
5. **Mock Dependencies**: Use mocks for external dependencies

### Example Template

```python
def new_function(param1: str, param2: int) -> bool:
    """Brief description of what the function does.

    Longer description explaining the function's purpose, behavior,
    and any important implementation details.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter

    Returns:
        Description of return value

    Raises:
        ValueError: When parameters are invalid

    Examples:
        >>> # Normal usage
        >>> new_function("test", 42)
        True

        >>> # Edge case
        >>> new_function("", 0)
        False

        >>> # Error condition
        >>> try:
        ...     new_function("test", -1)
        ... except ValueError as e:
        ...     print("Expected error:", str(e))
        Expected error: Invalid parameter
    """
```

### Running Tests

Before submitting a PR:

```bash
# Run all tests including doctests
make test

# Run only doctests
make doctest

# Check linting
make flake8

# Run pre-commit hooks
make pre-commit
```

## Troubleshooting

### Common Issues

1. **Async Functions**: Remember to use `asyncio.run()` in examples
2. **Mock Objects**: Use appropriate mocks for external dependencies
3. **Import Issues**: Ensure all imports are available in doctest context
4. **Whitespace**: Be careful with trailing whitespace in expected output

### Debugging Doctests

```bash
# Run with maximum verbosity
python -m doctest module.py -v

# Run specific function
python -c "import doctest; doctest.run_docstring_examples(function, globals())"

# Check for syntax errors
python -m py_compile module.py
```

## Benefits

### For Developers

- **Self-Documenting Code**: Examples show exactly how to use functions
- **Regression Testing**: Changes that break documented behavior are caught
- **Learning Tool**: New developers can run examples to understand code
- **Quality Assurance**: Ensures documentation stays accurate

### For Users

- **Reliable Examples**: All examples in documentation are tested
- **Up-to-Date Documentation**: Examples reflect actual code behavior
- **Interactive Learning**: Can copy-paste examples and run them
- **Confidence**: Know that documented behavior is verified

### For Maintainers

- **Automated Testing**: Doctests run automatically in CI/CD
- **Quality Gates**: Pre-commit hooks prevent broken examples
- **Coverage Tracking**: Clear metrics on documentation quality
- **Maintenance**: Easier to keep documentation in sync with code

## Future Enhancements

### Planned Improvements

1. **Coverage Reporting**: Generate detailed coverage reports
2. **Performance Testing**: Add performance benchmarks to examples
3. **Integration Testing**: More complex multi-module examples
4. **Visual Documentation**: Generate visual documentation from doctests

### Tools and Integration

- **Coverage.py**: Track doctest coverage metrics
- **pytest-doctestplus**: Enhanced doctest features
- **sphinx-doctest**: Integration with Sphinx documentation
- **doctest-ellipsis**: Support for ellipsis in expected output

---

## Related Documentation

- [Development Guide](index.md) - General development information
- [Testing Guide](../testing/index.md) - Testing strategies and tools
- [Contributing Guidelines](https://github.com/IBM/mcp-context-forge/blob/main/CONTRIBUTING.md) - How to contribute to the project
- [Make Targets](../index.md#development) - Available make targets including doctest commands
