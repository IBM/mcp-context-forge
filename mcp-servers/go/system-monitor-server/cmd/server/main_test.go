package main

import (
    "context"
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "os"
    "strings"
    "testing"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
)

func TestVersionJSON(t *testing.T) {
    version := versionJSON()
    if version == "" {
        t.Error("Version JSON should not be empty")
    }

    // Test that it's valid JSON
    var v map[string]interface{}
    if err := json.Unmarshal([]byte(version), &v); err != nil {
        t.Errorf("Version JSON should be valid JSON: %v", err)
    }

    // Test that it contains expected fields
    if v["name"] != appName {
        t.Errorf("Expected name %s, got %s", appName, v["name"])
    }
    if v["version"] != appVersion {
        t.Errorf("Expected version %s, got %s", appVersion, v["version"])
    }
}

func TestHealthJSON(t *testing.T) {
    health := healthJSON()
    if health == "" {
        t.Error("Health JSON should not be empty")
    }

    // Test that it's valid JSON
    var h map[string]interface{}
    if err := json.Unmarshal([]byte(health), &h); err != nil {
        t.Errorf("Health JSON should be valid JSON: %v", err)
    }

    // Test that it contains expected fields
    if h["status"] != "healthy" {
        t.Errorf("Expected status 'healthy', got %s", h["status"])
    }
    if _, ok := h["uptime_seconds"]; !ok {
        t.Error("Expected uptime_seconds field")
    }
}

func TestParseLvl(t *testing.T) {
    tests := []struct {
        input    string
        expected logLvl
    }{
        {"debug", logDebug},
        {"DEBUG", logDebug},
        {"info", logInfo},
        {"INFO", logInfo},
        {"warn", logWarn},
        {"warning", logWarn},
        {"error", logError},
        {"none", logNone},
        {"off", logNone},
        {"silent", logNone},
        {"invalid", logInfo}, // default
        {"", logInfo},        // default
    }

    for _, test := range tests {
        result := parseLvl(test.input)
        if result != test.expected {
            t.Errorf("parseLvl(%s) = %v, expected %v", test.input, result, test.expected)
        }
    }
}

func TestLogAt(t *testing.T) {
    // Test that logAt respects log levels
    // This is a bit tricky to test without capturing output, but we can test the logic
    originalLevel := curLvl
    defer func() { curLvl = originalLevel }()

    // Test with different log levels
    curLvl = logDebug
    logAt(logDebug, "debug message")
    logAt(logInfo, "info message")
    logAt(logWarn, "warn message")
    logAt(logError, "error message")

    curLvl = logWarn
    logAt(logDebug, "debug message") // Should not log
    logAt(logInfo, "info message")   // Should not log
    logAt(logWarn, "warn message")   // Should log
    logAt(logError, "error message") // Should log
}

func TestHandleGetSystemMetrics(t *testing.T) {
    ctx := context.Background()
    req := mcp.CallToolRequest{}

    result, err := handleGetSystemMetrics(ctx, req)
    if err != nil {
        t.Fatalf("handleGetSystemMetrics failed: %v", err)
    }

    if result.IsError {
        // Get text content from the result
        if len(result.Content) > 0 {
            if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
                t.Errorf("Expected success, got error: %s", textContent.Text)
            } else {
                t.Error("Expected success, got error")
            }
        } else {
            t.Error("Expected success, got error")
        }
    }

    // Test that result contains valid JSON
    if len(result.Content) > 0 {
        if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
            var metrics map[string]interface{}
            if err := json.Unmarshal([]byte(textContent.Text), &metrics); err != nil {
                t.Errorf("Result should be valid JSON: %v", err)
            }

            // Test that it contains expected fields
            expectedFields := []string{"timestamp", "cpu", "memory", "disk", "network"}
            for _, field := range expectedFields {
                if _, ok := metrics[field]; !ok {
                    t.Errorf("Expected field %s in metrics", field)
                }
            }
        } else {
            t.Error("Expected text content in result")
        }
    } else {
        t.Error("Expected content in result")
    }
}

func TestHandleListProcesses(t *testing.T) {
    ctx := context.Background()

    // Test basic request
    req := mcp.CallToolRequest{}
    result, err := handleListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("handleListProcesses failed: %v", err)
    }

    if result.IsError {
        if len(result.Content) > 0 {
            if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
                t.Errorf("Expected success, got error: %s", textContent.Text)
            } else {
                t.Error("Expected success, got error")
            }
        } else {
            t.Error("Expected success, got error")
        }
    }

    // Test with parameters - create a proper CallToolRequest
    req = mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "filter_by":    "name",
                "filter_value": "go",
                "sort_by":      "cpu",
                "limit":        10,
            },
        },
    }

    result, err = handleListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("handleListProcesses with params failed: %v", err)
    }

    if result.IsError {
        if len(result.Content) > 0 {
            if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
                t.Errorf("Expected success with params, got error: %s", textContent.Text)
            } else {
                t.Error("Expected success with params, got error")
            }
        } else {
            t.Error("Expected success with params, got error")
        }
    }
}

func TestHandleMonitorProcess(t *testing.T) {
    ctx := context.Background()

    // Test with invalid request (no PID or name)
    req := mcp.CallToolRequest{}
    result, err := handleMonitorProcess(ctx, req)
    if err != nil {
        t.Fatalf("handleMonitorProcess failed: %v", err)
    }

    if !result.IsError {
        t.Error("Expected error for invalid request")
    }

    // Test with valid PID (use current process)
    req = mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "pid":      int(os.Getpid()),
                "duration": 1,
                "interval": 1,
            },
        },
    }

    result, err = handleMonitorProcess(ctx, req)
    if err != nil {
        t.Fatalf("handleMonitorProcess with PID failed: %v", err)
    }

    // This might succeed or fail depending on process access, but shouldn't panic
}

func TestHandleCheckServiceHealth(t *testing.T) {
    ctx := context.Background()

    // Test with empty services
    req := mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "services": "[]",
            },
        },
    }

    result, err := handleCheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("handleCheckServiceHealth failed: %v", err)
    }

    if result.IsError {
        if len(result.Content) > 0 {
            if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
                t.Errorf("Expected success, got error: %s", textContent.Text)
            } else {
                t.Error("Expected success, got error")
            }
        } else {
            t.Error("Expected success, got error")
        }
    }

    // Test with invalid JSON
    req = mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "services": "invalid json",
            },
        },
    }

    result, err = handleCheckServiceHealth(ctx, req)
    if err != nil {
        t.Fatalf("handleCheckServiceHealth failed: %v", err)
    }

    if !result.IsError {
        t.Error("Expected error for invalid JSON")
    }
}

func TestHandleTailLogs(t *testing.T) {
    ctx := context.Background()

    // Test with missing file_path
    req := mcp.CallToolRequest{}
    result, err := handleTailLogs(ctx, req)
    if err != nil {
        t.Fatalf("handleTailLogs failed: %v", err)
    }

    if !result.IsError {
        t.Error("Expected error for missing file_path")
    }

    // SECURITY TEST: Verify that /tmp is not allowed (security hardening)
    // Create a temp file in /tmp to test that access is properly denied
    tmpFile, err := os.CreateTemp("/tmp", "test-log-*.txt")
    if err != nil {
        t.Skip("Cannot create temp file for security test")
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    tmpFile.WriteString("test log line\n")
    tmpFile.Close()

    req = mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "file_path": tmpFile.Name(),
                "lines":     10,
            },
        },
    }

    result, err = handleTailLogs(ctx, req)
    if err != nil {
        t.Fatalf("handleTailLogs failed: %v", err)
    }

    // SECURITY: Expect error because /tmp is not in allowed paths
    if !result.IsError {
        t.Error("Expected error for /tmp access (security hardening), but got success")
    }

    // Verify the error message mentions path validation
    if len(result.Content) > 0 {
        if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
            if !strings.Contains(textContent.Text, "file path validation failed") &&
                !strings.Contains(textContent.Text, "not in allowed directories") {
                t.Errorf("Expected path validation error, got: %s", textContent.Text)
            }
        }
    }
}

func TestHandleGetDiskUsage(t *testing.T) {
    ctx := context.Background()

    // SECURITY TEST: Verify that /tmp is not allowed (security hardening)
    req := mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Arguments: map[string]interface{}{
                "path":      "/tmp",
                "max_depth": 1,
            },
        },
    }

    result, err := handleGetDiskUsage(ctx, req)
    if err != nil {
        t.Fatalf("handleGetDiskUsage failed: %v", err)
    }

    // SECURITY: Expect error because /tmp is not in allowed paths
    if !result.IsError {
        t.Error("Expected error for /tmp access (security hardening), but got success")
    }

    // Verify the error message mentions path validation
    if len(result.Content) > 0 {
        if textContent, ok := mcp.AsTextContent(result.Content[0]); ok {
            if !strings.Contains(textContent.Text, "failed to get disk usage") &&
                !strings.Contains(textContent.Text, "not in allowed directories") {
                t.Errorf("Expected path validation error, got: %s", textContent.Text)
            }
        }
    }
}

func TestAuthMiddleware(t *testing.T) {
    // Test without token
    handler := authMiddleware("", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
    }))

    req := httptest.NewRequest("GET", "/test", nil)
    w := httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusUnauthorized {
        t.Errorf("Expected 401, got %d", w.Code)
    }

    // Test with invalid token
    req.Header.Set("Authorization", "Bearer invalid")
    w = httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusUnauthorized {
        t.Errorf("Expected 401, got %d", w.Code)
    }

    // Test with valid token
    req.Header.Set("Authorization", "Bearer valid-token")
    w = httptest.NewRecorder()

    handler = authMiddleware("valid-token", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
    }))

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200, got %d", w.Code)
    }

    // Test health endpoint (should skip auth)
    req = httptest.NewRequest("GET", "/health", nil)
    w = httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200 for health endpoint, got %d", w.Code)
    }
}

func TestEffectiveAddr(t *testing.T) {
    tests := []struct {
        addrFlag string
        listen   string
        port     int
        expected string
    }{
        {"", "0.0.0.0", 8080, "0.0.0.0:8080"},
        {"", "localhost", 3000, "localhost:3000"},
        {"127.0.0.1:9090", "0.0.0.0", 8080, "127.0.0.1:9090"},
        {"", "", 8080, ":8080"},
    }

    for _, test := range tests {
        result := effectiveAddr(test.addrFlag, test.listen, test.port)
        if result != test.expected {
            t.Errorf("effectiveAddr(%s, %s, %d) = %s, expected %s",
                test.addrFlag, test.listen, test.port, result, test.expected)
        }
    }
}

func TestRegisterHealthAndVersion(t *testing.T) {
    mux := http.NewServeMux()
    registerHealthAndVersion(mux)

    // Test health endpoint
    req := httptest.NewRequest("GET", "/health", nil)
    w := httptest.NewRecorder()
    mux.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200 for health, got %d", w.Code)
    }

    if w.Header().Get("Content-Type") != "application/json" {
        t.Errorf("Expected JSON content type, got %s", w.Header().Get("Content-Type"))
    }

    // Test version endpoint
    req = httptest.NewRequest("GET", "/version", nil)
    w = httptest.NewRecorder()
    mux.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200 for version, got %d", w.Code)
    }

    if w.Header().Get("Content-Type") != "application/json" {
        t.Errorf("Expected JSON content type, got %s", w.Header().Get("Content-Type"))
    }
}

func TestLoggingHTTPMiddleware(t *testing.T) {
    // Test with different log levels
    originalLevel := curLvl
    defer func() { curLvl = originalLevel }()

    handler := loggingHTTPMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
    }))

    req := httptest.NewRequest("GET", "/test", nil)
    w := httptest.NewRecorder()

    // Test with info level
    curLvl = logInfo
    handler.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200, got %d", w.Code)
    }

    // Test with debug level and POST request
    curLvl = logDebug
    req = httptest.NewRequest("POST", "/test", strings.NewReader("test body"))
    req.Header.Set("Content-Length", "9")
    w = httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("Expected 200, got %d", w.Code)
    }
}

func TestStatusWriter(t *testing.T) {
    w := httptest.NewRecorder()
    sw := &statusWriter{ResponseWriter: w, status: http.StatusOK, written: false}

    // Test WriteHeader
    sw.WriteHeader(http.StatusCreated)
    if sw.status != http.StatusCreated {
        t.Errorf("Expected status %d, got %d", http.StatusCreated, sw.status)
    }
    if !sw.written {
        t.Error("Expected written to be true")
    }

    // Test Write (should call WriteHeader automatically)
    w2 := httptest.NewRecorder()
    sw2 := &statusWriter{ResponseWriter: w2, status: http.StatusOK, written: false}

    sw2.Write([]byte("test"))
    if sw2.status != http.StatusOK {
        t.Errorf("Expected status %d, got %d", http.StatusOK, sw2.status)
    }
    if !sw2.written {
        t.Error("Expected written to be true")
    }

    // Test Flush
    w3 := httptest.NewRecorder()
    sw3 := &statusWriter{ResponseWriter: w3, status: http.StatusOK, written: false}

    sw3.Flush()
    if sw3.status != http.StatusOK {
        t.Errorf("Expected status %d, got %d", http.StatusOK, sw3.status)
    }
    if !sw3.written {
        t.Error("Expected written to be true")
    }
}

func TestStatusWriterHijack(t *testing.T) {
    w := httptest.NewRecorder()
    sw := &statusWriter{ResponseWriter: w, status: http.StatusOK, written: false}

    // Test Hijack (should return error since httptest.ResponseRecorder doesn't support it)
    conn, rw, err := sw.Hijack()
    if err == nil {
        t.Error("Expected error for Hijack")
    }
    if conn != nil || rw != nil {
        t.Error("Expected nil conn and rw")
    }
}

func TestStatusWriterCloseNotify(t *testing.T) {
    w := httptest.NewRecorder()
    sw := &statusWriter{ResponseWriter: w, status: http.StatusOK, written: false}

    // Test CloseNotify (should return a channel)
    ch := sw.CloseNotify()
    if ch == nil {
        t.Error("Expected non-nil channel")
    }

    // Test that the channel doesn't close immediately
    select {
    case <-ch:
        t.Error("Channel should not be closed immediately")
    case <-time.After(10 * time.Millisecond):
        // Expected - channel should not close
    }
}
