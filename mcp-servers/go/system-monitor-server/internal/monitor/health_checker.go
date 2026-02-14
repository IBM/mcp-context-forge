package monitor

import (
    "context"
    "fmt"
    "net"
    "net/http"
    "os"
    "path/filepath"
    "strings"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
)

// HealthChecker handles health checking of various services
type HealthChecker struct {
    httpClient *http.Client
}

// NewHealthChecker creates a new health checker
func NewHealthChecker() *HealthChecker {
    return &HealthChecker{
        httpClient: &http.Client{
            Timeout: 10 * time.Second,
        },
    }
}

// CheckServiceHealth performs health checks on the specified services
func (hc *HealthChecker) CheckServiceHealth(ctx context.Context, req *types.HealthCheckRequest) ([]types.HealthCheckResult, error) {
    timeout := time.Duration(req.Timeout) * time.Second
    if timeout == 0 {
        timeout = 10 * time.Second
    }

    var results []types.HealthCheckResult

    for _, service := range req.Services {
        ctx, cancel := context.WithTimeout(ctx, timeout)
        result := hc.checkSingleService(ctx, service)
        cancel()

        results = append(results, result)
    }

    return results, nil
}

// checkSingleService performs a health check on a single service
func (hc *HealthChecker) checkSingleService(ctx context.Context, service types.ServiceCheck) types.HealthCheckResult {
    startTime := time.Now()

    result := types.HealthCheckResult{
        ServiceName: service.Name,
        Timestamp:   time.Now(),
    }

    switch strings.ToLower(service.Type) {
    case "http", "https":
        result = hc.checkHTTPService(ctx, service, result)
    case "port", "tcp":
        result = hc.checkPortService(ctx, service, result)
    case "command":
        // SECURITY: Command execution removed due to command injection risk
        // Users should check process status via list_processes tool instead
        result.Status = "unsupported"
        result.Message = "command type disabled for security - use list_processes tool to check process status"
    case "file":
        result = hc.checkFileService(ctx, service, result)
    default:
        result.Status = "unknown"
        result.Message = fmt.Sprintf("unsupported service type: %s", service.Type)
    }

    result.ResponseTime = time.Since(startTime).Milliseconds()
    return result
}

// checkHTTPService checks HTTP/HTTPS service health
func (hc *HealthChecker) checkHTTPService(ctx context.Context, service types.ServiceCheck, result types.HealthCheckResult) types.HealthCheckResult {
    req, err := http.NewRequestWithContext(ctx, "GET", service.Target, nil)
    if err != nil {
        result.Status = "unhealthy"
        result.Message = fmt.Sprintf("failed to create request: %v", err)
        return result
    }

    resp, err := hc.httpClient.Do(req) // #nosec G704 -- Target endpoint comes from operator-supplied health-check configuration.
    if err != nil {
        result.Status = "unhealthy"
        result.Message = fmt.Sprintf("request failed: %v", err)
        return result
    }
    defer resp.Body.Close()

    // Check status code
    if resp.StatusCode >= 200 && resp.StatusCode < 300 {
        result.Status = "healthy"
        result.Message = fmt.Sprintf("HTTP %d", resp.StatusCode)
    } else {
        result.Status = "unhealthy"
        result.Message = fmt.Sprintf("HTTP %d", resp.StatusCode)
    }

    // Check expected headers if specified
    if service.Expected != nil {
        for key, expectedValue := range service.Expected {
            actualValue := resp.Header.Get(key)
            if actualValue != expectedValue {
                result.Status = "unhealthy"
                result.Message = fmt.Sprintf("header %s mismatch: expected %s, got %s", key, expectedValue, actualValue)
                break
            }
        }
    }

    return result
}

// checkPortService checks TCP port service health
func (hc *HealthChecker) checkPortService(ctx context.Context, service types.ServiceCheck, result types.HealthCheckResult) types.HealthCheckResult {
    conn, err := net.DialTimeout("tcp", service.Target, 5*time.Second)
    if err != nil {
        result.Status = "unhealthy"
        result.Message = fmt.Sprintf("connection failed: %v", err)
        return result
    }
    defer conn.Close()

    result.Status = "healthy"
    result.Message = "port is open and accessible"
    return result
}

// checkCommandService is DISABLED for security - command injection vulnerability
// SECURITY: This function previously allowed arbitrary command execution which
// created a critical command injection vulnerability. An attacker could execute
// any system command via the MCP tool API.
//
// Users should use the list_processes tool instead to check if processes are running.
func (hc *HealthChecker) checkCommandService(ctx context.Context, service types.ServiceCheck, result types.HealthCheckResult) types.HealthCheckResult {
    result.Status = "unsupported"
    result.Message = "command type disabled for security (command injection risk) - use list_processes tool instead"
    return result
}

// checkFileService checks service health by verifying file existence/properties
func (hc *HealthChecker) checkFileService(ctx context.Context, service types.ServiceCheck, result types.HealthCheckResult) types.HealthCheckResult {
    // Check if file exists
    info, err := os.Stat(service.Target)
    if err != nil {
        if os.IsNotExist(err) {
            result.Status = "unhealthy"
            result.Message = "file does not exist"
        } else {
            result.Status = "unhealthy"
            result.Message = fmt.Sprintf("file access error: %v", err)
        }
        return result
    }

    // Check file age if specified
    if service.Expected != nil {
        if maxAge, exists := service.Expected["max_age"]; exists {
            if maxAgeDuration, err := time.ParseDuration(maxAge); err == nil {
                if time.Since(info.ModTime()) > maxAgeDuration {
                    result.Status = "unhealthy"
                    result.Message = fmt.Sprintf("file is too old: %v", time.Since(info.ModTime()))
                    return result
                }
            }
        }

        // Check file size if specified
        if minSize, exists := service.Expected["min_size"]; exists {
            if minSizeBytes, err := parseSize(minSize); err == nil {
                if info.Size() < minSizeBytes {
                    result.Status = "unhealthy"
                    result.Message = fmt.Sprintf("file too small: %d bytes", info.Size())
                    return result
                }
            }
        }
    }

    result.Status = "healthy"
    result.Message = fmt.Sprintf("file exists and meets criteria: %s", filepath.Base(service.Target))
    return result
}

// parseSize parses a size string like "1MB", "500KB", etc.
func parseSize(sizeStr string) (int64, error) {
    sizeStr = strings.TrimSpace(sizeStr)
    sizeStr = strings.ToUpper(sizeStr)

    var multiplier int64 = 1
    var numStr string

    if strings.HasSuffix(sizeStr, "KB") {
        multiplier = 1024
        numStr = strings.TrimSuffix(sizeStr, "KB")
    } else if strings.HasSuffix(sizeStr, "MB") {
        multiplier = 1024 * 1024
        numStr = strings.TrimSuffix(sizeStr, "MB")
    } else if strings.HasSuffix(sizeStr, "GB") {
        multiplier = 1024 * 1024 * 1024
        numStr = strings.TrimSuffix(sizeStr, "GB")
    } else {
        numStr = sizeStr
    }

    var size int64
    _, err := fmt.Sscanf(numStr, "%d", &size)
    if err != nil {
        return 0, fmt.Errorf("invalid size format: %s", sizeStr)
    }

    return size * multiplier, nil
}
