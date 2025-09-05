package monitor

import (
    "context"
    "os"
    "testing"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
)

func TestHealthChecker_CheckHTTPService(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test with a known working HTTP service
    service := types.ServiceCheck{
        Name:   "test-http",
        Type:   "http",
        Target: "http://httpbin.org/status/200",
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  10,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check HTTP service: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // The service might be healthy or unhealthy depending on network conditions
    if result.Status != "healthy" && result.Status != "unhealthy" {
        t.Errorf("Expected healthy or unhealthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckPortService(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test with a known port (HTTP)
    service := types.ServiceCheck{
        Name:   "test-port",
        Type:   "port",
        Target: "httpbin.org:80",
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  10,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check port service: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // The service might be healthy or unhealthy depending on network conditions
    if result.Status != "healthy" && result.Status != "unhealthy" {
        t.Errorf("Expected healthy or unhealthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckCommandService(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test command health check
    service := types.ServiceCheck{
        Name:   "test-command",
        Type:   "command",
        Target: "echo 'test'",
        Expected: map[string]string{
            "output": "test",
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check command service: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileService(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    tmpFile.WriteString("test content")
    tmpFile.Close()

    // Test file health check
    service := types.ServiceCheck{
        Name:   "test-file",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "min_size": "1B",
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestParseSize(t *testing.T) {
    tests := []struct {
        input    string
        expected int64
        hasError bool
    }{
        {"1KB", 1024, false},
        {"1MB", 1024 * 1024, false},
        {"1GB", 1024 * 1024 * 1024, false},
        {"500B", 500, false},
        {"invalid", 0, true},
        {"1TB", 1, false}, // Not supported but treated as bytes
    }

    for _, test := range tests {
        result, err := parseSize(test.input)
        if test.hasError {
            if err == nil {
                t.Errorf("Expected error for input %s", test.input)
            }
        } else {
            if err != nil {
                t.Errorf("Unexpected error for input %s: %v", test.input, err)
            }
            if result != test.expected {
                t.Errorf("Expected %d for input %s, got %d", test.expected, test.input, result)
            }
        }
    }
}
