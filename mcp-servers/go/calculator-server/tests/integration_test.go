package tests

import (
    "bytes"
    "context"
    "encoding/json"
    "net/http"
    "testing"
    "time"

    "calculator-server/internal/config"
    "calculator-server/internal/handlers"
    "calculator-server/internal/types"
    "calculator-server/pkg/mcp"
)

func TestIntegrationHTTPTransportWithConfig(t *testing.T) {
    // Create config
    cfg := config.Default()
    cfg.Server.Transport = "http"
    cfg.Server.HTTP.Host = "localhost"
    cfg.Server.HTTP.Port = 8082 // Use different port for integration test
    cfg.Server.HTTP.CORS.Enabled = true
    cfg.Server.HTTP.CORS.Origins = []string{"*"}

    // Create MCP server
    server := mcp.NewServer()

    // Register handlers
    mathHandler := handlers.NewMathHandler()
    statsHandler := handlers.NewStatsHandler()

    server.RegisterTool("basic_math", "Basic math operations", getBasicMathSchema(), mathHandler.HandleBasicMath)
    server.RegisterTool("statistics", "Statistical analysis", getStatisticsSchema(), statsHandler.HandleStatistics)

    // Create MCP-compliant streamable HTTP transport with config
    httpConfig := &mcp.StreamableHTTPConfig{
        Host:           cfg.Server.HTTP.Host,
        Port:           cfg.Server.HTTP.Port,
        SessionTimeout: cfg.Server.HTTP.SessionTimeout,
        MaxConnections: cfg.Server.HTTP.MaxConnections,
        CORSEnabled:    cfg.Server.HTTP.CORS.Enabled,
        CORSOrigins:    cfg.Server.HTTP.CORS.Origins,
    }

    httpTransport := mcp.NewStreamableHTTPTransport(server, httpConfig)

    // Start server in background
    go func() {
        if err := httpTransport.Start(); err != nil {
            t.Logf("HTTP server error: %v", err)
        }
    }()

    // Give server time to start
    time.Sleep(100 * time.Millisecond)

    // Test MCP tools list via single endpoint
    t.Run("MCP Tools List", func(t *testing.T) {
        mcpRequest := types.MCPRequest{
            JSONRPC: "2.0",
            ID:      "tools-list",
            Method:  "tools/list",
        }

        requestBody, _ := json.Marshal(mcpRequest)
        client := &http.Client{}
        req, _ := http.NewRequest("POST", "http://localhost:8082/mcp", bytes.NewBuffer(requestBody))
        req.Header.Set("Content-Type", "application/json")
        req.Header.Set("Accept", "application/json")
        req.Header.Set("MCP-Protocol-Version", "2024-11-05")

        resp, err := client.Do(req)
        if err != nil {
            t.Fatalf("Tools list failed: %v", err)
        }
        defer resp.Body.Close()

        if resp.StatusCode != http.StatusOK {
            t.Errorf("Expected status 200, got %d", resp.StatusCode)
        }

        var response types.MCPResponse
        if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
            t.Errorf("Failed to decode tools response: %v", err)
        }

        if response.Error != nil {
            t.Errorf("Unexpected error in tools response: %v", response.Error)
        }
    })

    // Test MCP basic math endpoint
    t.Run("Basic Math MCP Call", func(t *testing.T) {
        mcpRequest := types.MCPRequest{
            JSONRPC: "2.0",
            ID:      1,
            Method:  "tools/call",
            Params:  json.RawMessage(`{"name":"basic_math","arguments":{"operation":"add","operands":[10,20,30],"precision":2}}`),
        }

        requestBody, _ := json.Marshal(mcpRequest)
        client := &http.Client{}
        req, _ := http.NewRequest("POST", "http://localhost:8082/mcp", bytes.NewBuffer(requestBody))
        req.Header.Set("Content-Type", "application/json")
        req.Header.Set("Accept", "application/json")
        req.Header.Set("MCP-Protocol-Version", "2024-11-05")

        resp, err := client.Do(req)
        if err != nil {
            t.Fatalf("MCP request failed: %v", err)
        }
        defer resp.Body.Close()

        if resp.StatusCode != http.StatusOK {
            t.Errorf("Expected status 200, got %d", resp.StatusCode)
        }

        var response types.MCPResponse
        if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
            t.Errorf("Failed to decode MCP response: %v", err)
        }

        if response.Error != nil {
            t.Errorf("Unexpected error in MCP response: %v", response.Error)
        }

        if response.Result == nil {
            t.Error("Expected result in MCP response")
        }
    })

    // Test CORS headers
    t.Run("CORS Headers", func(t *testing.T) {
        client := &http.Client{}
        req, _ := http.NewRequest("OPTIONS", "http://localhost:8082/mcp", nil)
        req.Header.Set("Origin", "http://localhost:3000")
        req.Header.Set("Access-Control-Request-Method", "POST")

        resp, err := client.Do(req)
        if err != nil {
            t.Fatalf("CORS preflight failed: %v", err)
        }
        defer resp.Body.Close()

        if resp.StatusCode != http.StatusOK {
            t.Errorf("Expected status 200 for CORS preflight, got %d", resp.StatusCode)
        }

        allowOrigin := resp.Header.Get("Access-Control-Allow-Origin")
        if allowOrigin == "" {
            t.Error("Expected Access-Control-Allow-Origin header")
        }
    })

    // Graceful shutdown
    shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer shutdownCancel()

    if err := httpTransport.Stop(shutdownCtx); err != nil {
        t.Errorf("Failed to shutdown gracefully: %v", err)
    }
}

func TestIntegrationConfigLoaderWithServer(t *testing.T) {
    // Test that configuration loading integrates properly with server startup
    cfg := config.Default()
    cfg.Server.Transport = "http"
    cfg.Server.HTTP.Port = 8083

    // Validate configuration
    if err := cfg.Validate(); err != nil {
        t.Fatalf("Configuration validation failed: %v", err)
    }

    // Test that we can create MCP-compliant streamable HTTP transport from config
    httpConfig := &mcp.StreamableHTTPConfig{
        Host:           cfg.Server.HTTP.Host,
        Port:           cfg.Server.HTTP.Port,
        SessionTimeout: cfg.Server.HTTP.SessionTimeout,
        MaxConnections: cfg.Server.HTTP.MaxConnections,
        CORSEnabled:    cfg.Server.HTTP.CORS.Enabled,
        CORSOrigins:    cfg.Server.HTTP.CORS.Origins,
    }

    server := mcp.NewServer()
    httpTransport := mcp.NewStreamableHTTPTransport(server, httpConfig)

    // Test that address is correctly configured
    expectedAddr := "127.0.0.1:8083"
    if httpTransport.GetAddr() != expectedAddr {
        t.Errorf("Expected address %s, got %s", expectedAddr, httpTransport.GetAddr())
    }
}

func TestStdioTransportBackwardCompatibility(t *testing.T) {
    // Test that stdio transport still works after refactoring
    server := mcp.NewServer()

    // Register a handler
    mathHandler := handlers.NewMathHandler()
    server.RegisterTool("basic_math", "Basic math operations", getBasicMathSchema(), mathHandler.HandleBasicMath)

    // Create stdio transport
    stdioTransport := mcp.NewStdioTransport(server)
    if stdioTransport == nil {
        t.Error("Failed to create stdio transport")
    }

    // Test that server.Run() still works (backwards compatibility)
    // Note: We can't actually test stdio input/output in unit tests easily,
    // but we can verify that the method exists and returns the right type
    go func() {
        // This would block waiting for stdin, so we run it in a goroutine
        // and immediately stop it
        server.Run()
    }()

    time.Sleep(10 * time.Millisecond) // Give it a moment to start
}

// Helper schemas for integration tests
func getStatisticsSchema() map[string]interface{} {
    return map[string]interface{}{
        "type": "object",
        "properties": map[string]interface{}{
            "data": map[string]interface{}{
                "type": "array",
                "items": map[string]interface{}{
                    "type": "number",
                },
                "minItems": 1,
            },
            "operation": map[string]interface{}{
                "type": "string",
                "enum": []string{"mean", "median", "mode", "std_dev", "variance"},
            },
        },
        "required": []string{"data", "operation"},
    }
}
