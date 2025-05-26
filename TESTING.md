# Testing Guide for MCP Context Forge

This guide explains how to set up and run tests for the MCP Context Forge project.

## Prerequisites

- Python 3.10 or higher
- virtualenv or venv (for virtual environment management)
- Make (for running Makefile commands)

## Setting Up the Test Environment

First, create a virtual environment and install the project's development dependencies:

```bash
make venv       # Create a virtual environment
make install    # Install the project with development dependencies
```

## Running Tests

### Running All Tests

To run all tests, simply use:

```bash
make test
```

This will:
1. Create a virtual environment if it doesn't exist
2. Install required testing dependencies (pytest, pytest-asyncio, pytest-cov)
3. Run the pytest suite with verbose output

### Running Specific Tests

You can run specific tests by specifying the file or directory:

```bash
# Activate the virtual environment
source ~/.venv/mcpgateway/bin/activate

# Run a specific test file
python -m pytest tests/unit/mcpgateway/test_config.py -v

# Run a specific test class
python -m pytest tests/unit/mcpgateway/validation/test_jsonrpc.py::TestJSONRPCValidation -v

# Run a specific test method
python -m pytest tests/unit/mcpgateway/validation/test_jsonrpc.py::TestJSONRPCValidation::test_validate_valid_request -v
```

### Testing README Examples

To test code examples from the README:

```bash
make pytest-examples
```

## Test Coverage

To run tests with coverage reporting:

```bash
# Activate the virtual environment
source ~/.venv/mcpgateway/bin/activate

# Run tests with coverage
python -m pytest --cov=mcpgateway tests/

# Generate a coverage report
python -m pytest --cov=mcpgateway --cov-report=html tests/
```

The HTML coverage report will be available in the `htmlcov` directory.

## Creating New Tests

When creating new tests, follow these guidelines:

1. Place test files in the appropriate directory under `tests/unit/`
2. Use the naming convention `test_*.py` for test files
3. Use pytest fixtures from `conftest.py` where applicable
4. Use `@pytest.mark.asyncio` decorator for asynchronous tests

## Continuous Integration

The project is configured to run tests automatically in CI/CD pipelines.
When committing changes, ensure all tests pass locally first:

```bash
make test
```

## Troubleshooting

If you encounter issues with running tests:

1. Check that you're using the virtual environment with the correct dependencies
2. Verify that your Python version is compatible (Python 3.10+)
3. Try recreating the virtual environment: `make clean && make venv && make install`
4. Check for any error messages during dependency installation
