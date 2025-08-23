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

### Current Coverage

| Module Category | Status | Coverage |
|----------------|--------|----------|
| **Transport Modules** | ✅ Complete | 100% |
| **Utility Functions** | ✅ Complete | 100% |
| **Validation Modules** | ✅ Complete | 100% |
| **Configuration** | ✅ Complete | 100% |
| **Service Classes** | 🔄 In Progress | ~60% |
| **Complex Classes** | 🔄 In Progress | ~40% |

### Modules with Full Coverage

- `mcpgateway/transports/base.py` - Base transport interface
- `mcpgateway/transports/stdio_transport.py` - Standard I/O transport
- `mcpgateway/transports/sse_transport.py` - Server-Sent Events transport
- `mcpgateway/transports/websocket_transport.py` - WebSocket transport
- `mcpgateway/transports/streamablehttp_transport.py` - Streamable HTTP transport
- `mcpgateway/transports/__init__.py` - Transport module exports
- `mcpgateway/utils/create_slug.py` - Slug generation utilities
- `mcpgateway/validation/jsonrpc.py` - JSON-RPC validation
- `mcpgateway/config.py` - Configuration management

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
- name: Run doctests
  run: |
    pytest --doctest-modules mcpgateway/ -v
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

Doctests are integrated into the pre-commit workflow:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: doctest
      name: Doctest
      entry: pytest --doctest-modules mcpgateway/
      language: system
      types: [python]
```

This ensures that:
- All doctests pass before commits are allowed
- Documentation examples are always verified
- Code quality is maintained automatically

## Coverage Metrics

### Current Statistics

- **Total Functions/Methods**: ~200
- **Functions with Doctests**: ~150
- **Coverage Percentage**: ~75%
- **Test Examples**: ~500+

### Coverage Goals

- **Phase 1**: ✅ Infrastructure setup (100%)
- **Phase 2**: ✅ Utility modules (100%)
- **Phase 3**: ✅ Configuration and schemas (100%)
- **Phase 4**: ✅ Service classes (100%)
- **Phase 5**: ✅ Transport modules (100%)
- **Phase 6**: 🔄 Documentation integration (100%)

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
- [Makefile Targets](../index.md#makefile-targets) - Available make targets including doctest commands
