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

    // SECURITY: Test that command execution is disabled
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
    // SECURITY: Command type should be disabled
    if result.Status != "unsupported" {
        t.Errorf("Expected unsupported status (security disabled), got %s", result.Status)
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

func TestHealthChecker_CheckServiceHealthEmpty(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test with empty services list
    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{},
        Timeout:  10,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check empty services: %v", err)
    }

    if len(results) != 0 {
        t.Errorf("Expected 0 results for empty services, got %d", len(results))
    }
}

func TestHealthChecker_CheckServiceHealthTimeout(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test with very short timeout
    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{
            {
                Name:   "test-http",
                Type:   "http",
                Target: "http://httpbin.org/delay/5", // 5 second delay
            },
        },
        Timeout: 1, // 1 second timeout
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check services with timeout: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // Should be unhealthy due to timeout
    if result.Status != "unhealthy" {
        t.Errorf("Expected unhealthy status due to timeout, got %s", result.Status)
    }
}

func TestHealthChecker_CheckServiceHealthZeroTimeout(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test with zero timeout (should use default)
    // SECURITY: Using command type to verify it's disabled
    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{
            {
                Name:   "test-command",
                Type:   "command",
                Target: "echo 'test'",
            },
        },
        Timeout: 0, // Zero timeout
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check services with zero timeout: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // SECURITY: Command type should be disabled
    if result.Status != "unsupported" {
        t.Errorf("Expected unsupported status (security disabled), got %s", result.Status)
    }
}

func TestHealthChecker_CheckHTTPServiceWithHeaders(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test HTTP service with expected headers
    service := types.ServiceCheck{
        Name:   "test-http-headers",
        Type:   "http",
        Target: "http://httpbin.org/headers",
        Expected: map[string]string{
            "Content-Type": "application/json",
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  10,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check HTTP service with headers: %v", err)
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

func TestHealthChecker_CheckCommandServiceEmpty(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // SECURITY: Test that command type is disabled even with empty command
    service := types.ServiceCheck{
        Name:   "test-empty-command",
        Type:   "command",
        Target: "", // Empty command
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check empty command service: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // SECURITY: Command type should be disabled
    if result.Status != "unsupported" {
        t.Errorf("Expected unsupported status (security disabled), got %s", result.Status)
    }
}

func TestHealthChecker_CheckCommandServiceWithOutput(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // SECURITY: Test that command type is disabled
    service := types.ServiceCheck{
        Name:   "test-command-output",
        Type:   "command",
        Target: "echo 'hello world'",
        Expected: map[string]string{
            "output": "hello world",
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check command service with output: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // SECURITY: Command type should be disabled
    if result.Status != "unsupported" {
        t.Errorf("Expected unsupported status (security disabled), got %s", result.Status)
    }
}

func TestHealthChecker_CheckCommandServiceWithWrongOutput(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // SECURITY: Test that command type is disabled
    service := types.ServiceCheck{
        Name:   "test-command-wrong-output",
        Type:   "command",
        Target: "echo 'hello world'",
        Expected: map[string]string{
            "output": "wrong output",
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check command service with wrong output: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // SECURITY: Command type should be disabled
    if result.Status != "unsupported" {
        t.Errorf("Expected unsupported status (security disabled), got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileServiceWithAge(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-age-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    tmpFile.WriteString("test content")
    tmpFile.Close()

    // Test file service with age check
    service := types.ServiceCheck{
        Name:   "test-file-age",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "max_age": "1h", // 1 hour max age
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service with age: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileServiceWithInvalidAge(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-invalid-age-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    tmpFile.WriteString("test content")
    tmpFile.Close()

    // Test file service with invalid age format
    service := types.ServiceCheck{
        Name:   "test-file-invalid-age",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "max_age": "invalid-age", // Invalid age format
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service with invalid age: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // Should still be healthy since invalid age format is ignored
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileServiceWithSize(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-size-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    content := "test content"
    tmpFile.WriteString(content)
    tmpFile.Close()

    // Test file service with size check
    service := types.ServiceCheck{
        Name:   "test-file-size",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "min_size": "1B", // 1 byte minimum
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service with size: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileServiceWithTooSmallSize(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-small-size-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    content := "test content"
    tmpFile.WriteString(content)
    tmpFile.Close()

    // Test file service with size check that's too large
    service := types.ServiceCheck{
        Name:   "test-file-small-size",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "min_size": "1KB", // 1KB minimum (larger than our file)
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service with small size: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "unhealthy" {
        t.Errorf("Expected unhealthy status for small file, got %s", result.Status)
    }
}

func TestHealthChecker_CheckFileServiceWithInvalidSize(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "health-test-invalid-size-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    tmpFile.WriteString("test content")
    tmpFile.Close()

    // Test file service with invalid size format
    service := types.ServiceCheck{
        Name:   "test-file-invalid-size",
        Type:   "file",
        Target: tmpFile.Name(),
        Expected: map[string]string{
            "min_size": "invalid-size", // Invalid size format
        },
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check file service with invalid size: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    // Should still be healthy since invalid size format is ignored
    if result.Status != "healthy" {
        t.Errorf("Expected healthy status, got %s", result.Status)
    }
}

func TestHealthChecker_CheckUnknownServiceType(t *testing.T) {
    checker := NewHealthChecker()
    ctx := context.Background()

    // Test unknown service type
    service := types.ServiceCheck{
        Name:   "test-unknown",
        Type:   "unknown",
        Target: "some-target",
    }

    req := &types.HealthCheckRequest{
        Services: []types.ServiceCheck{service},
        Timeout:  5,
    }

    results, err := checker.CheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("Failed to check unknown service type: %v", err)
    }

    if len(results) != 1 {
        t.Fatalf("Expected 1 result, got %d", len(results))
    }

    result := results[0]
    if result.Status != "unknown" {
        t.Errorf("Expected unknown status, got %s", result.Status)
    }
}

func TestParseSizeEdgeCases(t *testing.T) {
    tests := []struct {
        input    string
        expected int64
        hasError bool
    }{
        {"", 0, true},
        {"0", 0, false},
        {"0KB", 0, false},
        {"0MB", 0, false},
        {"0GB", 0, false},
        {"1.5KB", 1024, false}, // Decimal parsed as integer (1) * 1024
        {"-1KB", -1024, false}, // Negative parsed as integer (-1) * 1024
        {"1KB ", 1024, false},  // Trailing space (trimmed)
        {" 1KB", 1024, false},  // Leading space (trimmed)
        {"1kb", 1024, false},   // Lowercase
        {"1Kb", 1024, false},   // Mixed case
        {"1", 1, false},        // No unit (bytes)
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
