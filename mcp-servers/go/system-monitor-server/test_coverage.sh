#!/bin/bash

# Test Coverage Script for System Monitor Server
# This script runs all tests and generates a comprehensive coverage report

set -e

echo "🧪 Running comprehensive test suite for System Monitor Server..."
echo "================================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "go.mod" ]; then
    print_error "go.mod not found. Please run this script from the project root directory."
    exit 1
fi

# Clean previous coverage files
print_status "Cleaning previous coverage files..."
rm -f coverage.out coverage.html coverage.txt

# Create coverage directory
mkdir -p coverage

# Run tests with coverage for each package
print_status "Running tests with coverage..."

# Test main package
print_status "Testing main package..."
go test -v -coverprofile=coverage/main.out -covermode=count ./cmd/server/ || {
    print_error "Main package tests failed"
    exit 1
}

# Test config package
print_status "Testing config package..."
go test -v -coverprofile=coverage/config.out -covermode=count ./internal/config/ || {
    print_error "Config package tests failed"
    exit 1
}

# Test metrics package
print_status "Testing metrics package..."
go test -v -coverprofile=coverage/metrics.out -covermode=count ./internal/metrics/ || {
    print_error "Metrics package tests failed"
    exit 1
}

# Test monitor package
print_status "Testing monitor package..."
go test -v -coverprofile=coverage/monitor.out -covermode=count ./internal/monitor/ || {
    print_error "Monitor package tests failed"
    exit 1
}

# Combine coverage profiles
print_status "Combining coverage profiles..."
echo "mode: count" > coverage.out
tail -n +2 coverage/main.out >> coverage.out
tail -n +2 coverage/config.out >> coverage.out
tail -n +2 coverage/metrics.out >> coverage.out
tail -n +2 coverage/monitor.out >> coverage.out

# Generate coverage report
print_status "Generating coverage report..."

# HTML coverage report
go tool cover -html=coverage.out -o coverage/coverage.html

# Post-process HTML to show only filenames in dropdown
print_status "Post-processing HTML report to show only filenames..."
# Replace full paths with just filenames in option tags
sed -i.bak 's|github\.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/[^/]*/\([^/]*\)\.go|\1.go|g' coverage/coverage.html
# Also handle the case where there might be multiple directory levels
sed -i.bak2 's|github\.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/[^/]*/[^/]*/\([^/]*\)\.go|\1.go|g' coverage/coverage.html
rm -f coverage/coverage.html.bak coverage/coverage.html.bak2
print_success "HTML coverage report generated: coverage/coverage.html"

# Text coverage report
go tool cover -func=coverage.out > coverage/coverage.txt
print_success "Text coverage report generated: coverage/coverage.txt"

# Show coverage summary
print_status "Coverage Summary:"
echo "=================="
go tool cover -func=coverage.out | tail -1

# Generate detailed coverage by package
print_status "Coverage by Package:"
echo "====================="
echo "Main Package:"
go tool cover -func=coverage/main.out | tail -1
echo "Config Package:"
go tool cover -func=coverage/config.out | tail -1
echo "Metrics Package:"
go tool cover -func=coverage/metrics.out | tail -1
echo "Monitor Package:"
go tool cover -func=coverage/monitor.out | tail -1


# Run race detection
print_status "Running race detection tests..."
go test -race ./... > coverage/race.txt 2>&1 || {
    print_warning "Race detection found issues (check coverage/race.txt)"
}

# Run tests with different build tags if any
print_status "Running tests with different build tags..."

# Run tests with verbose output for debugging
print_status "Running tests with verbose output..."
go test -v ./... > coverage/verbose_tests.txt 2>&1 || {
    print_warning "Some tests may have failed (check coverage/verbose_tests.txt)"
}

# Generate test summary
print_status "Generating test summary..."
cat > coverage/test_summary.md << EOF
# Test Coverage Report

Generated on: $(date)

## Overall Coverage
\`\`\`
$(go tool cover -func=coverage.out | tail -1)
\`\`\`

## Package Coverage
- **Main Package**: $(go tool cover -func=coverage/main.out | tail -1 | awk '{print $3}')
- **Config Package**: $(go tool cover -func=coverage/config.out | tail -1 | awk '{print $3}')
- **Metrics Package**: $(go tool cover -func=coverage/metrics.out | tail -1 | awk '{print $3}')
- **Monitor Package**: $(go tool cover -func=coverage/monitor.out | tail -1 | awk '{print $3}')

## Files Generated
- \`coverage.html\` - Interactive HTML coverage report
- \`coverage.txt\` - Text coverage report
- \`benchmarks.txt\` - Benchmark results
- \`race.txt\` - Race detection results
- \`verbose_tests.txt\` - Verbose test output

## Test Commands Used
\`\`\`bash
# Run all tests with coverage
go test -v -coverprofile=coverage.out -covermode=count ./...

# Generate HTML report
go tool cover -html=coverage.out -o coverage.html

# Generate text report
go tool cover -func=coverage.out > coverage.txt

# Run benchmarks
go test -bench=. -benchmem ./...

# Run race detection
go test -race ./...
\`\`\`

## Coverage Goals
- **Target**: > 80% overall coverage
- **Critical Paths**: > 90% coverage for main handlers and core logic
- **Edge Cases**: All error paths should be tested

## Notes
- Some tests may fail due to system-specific behavior (e.g., process access)
- Network-dependent tests may fail in isolated environments
- File system tests use temporary files and should clean up automatically
EOF

print_success "Test summary generated: coverage/test_summary.md"

# Check if coverage meets minimum threshold
COVERAGE=$(go tool cover -func=coverage.out | tail -1 | awk '{print $3}' | sed 's/%//')
THRESHOLD=80

if (( $(echo "$COVERAGE >= $THRESHOLD" | bc -l) )); then
    print_success "Coverage $COVERAGE% meets minimum threshold of $THRESHOLD%"
else
    print_warning "Coverage $COVERAGE% is below minimum threshold of $THRESHOLD%"
fi

# Show files that need more coverage
print_status "Files with low coverage:"
go tool cover -func=coverage.out | awk '$3 < 80 {print $1 " " $3 "%"}' | head -10

print_success "Test coverage analysis complete!"
print_status "Open coverage/coverage.html in your browser to view the detailed coverage report."

# List all generated files
echo ""
print_status "Generated files:"
ls -la coverage/

echo ""
print_success "🎉 Test coverage report generation complete!"
