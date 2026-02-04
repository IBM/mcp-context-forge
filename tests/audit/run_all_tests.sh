#!/bin/bash
# Test runner script for MCP Audit System
# Usage:
#   ./run_all_tests.sh          # Run all tests
#   ./run_all_tests.sh --quick  # Run basic tests only
#   ./run_all_tests.sh --cov    # Run with coverage

set -e

echo "======================================================================"
echo "MCP Audit System - Test Runner"
echo "======================================================================"
echo ""

# Check for pytest
if python3 -c "import pytest" 2>/dev/null; then
    HAS_PYTEST=1
else
    HAS_PYTEST=0
fi

# Parse arguments
QUICK_MODE=0
COVERAGE_MODE=0

for arg in "$@"; do
    case $arg in
        --quick)
            QUICK_MODE=1
            ;;
        --cov|--coverage)
            COVERAGE_MODE=1
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick      Run basic tests only (no pytest required)"
            echo "  --cov        Run with coverage report (requires pytest-cov)"
            echo "  --help       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                  # Run all tests"
            echo "  $0 --quick          # Quick test without dependencies"
            echo "  $0 --cov            # Full tests with coverage"
            exit 0
            ;;
    esac
done

# Run tests based on mode
if [ $QUICK_MODE -eq 1 ] || [ $HAS_PYTEST -eq 0 ]; then
    if [ $HAS_PYTEST -eq 0 ] && [ $QUICK_MODE -eq 0 ]; then
        echo "⚠️  pytest not found. Running basic tests only."
        echo "   Install with: pip install pytest pytest-asyncio --break-system-packages"
        echo ""
    fi
    
    echo "Running Basic Tests..."
    echo "----------------------------------------------------------------------"
    python3 test_mcp_audit.py
    EXIT_CODE=$?
else
    echo "Running Comprehensive Test Suite..."
    echo "----------------------------------------------------------------------"
    
    if [ $COVERAGE_MODE -eq 1 ]; then
        python3 -m pytest test_mcp_audit_comprehensive.py -v --cov=. --cov-report=term-missing --cov-report=html
    else
        python3 -m pytest test_mcp_audit_comprehensive.py -v
    fi
    EXIT_CODE=$?
    
    if [ $COVERAGE_MODE -eq 1 ] && [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "Coverage report generated: htmlcov/index.html"
    fi
fi

echo ""
echo "======================================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ All tests passed!"
else
    echo "❌ Some tests failed. Exit code: $EXIT_CODE"
fi
echo "======================================================================"

exit $EXIT_CODE
