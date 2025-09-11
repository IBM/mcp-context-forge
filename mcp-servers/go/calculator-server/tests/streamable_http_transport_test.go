package tests

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	"calculator-server/internal/config"
	"calculator-server/internal/handlers"
	"calculator-server/internal/types"
	"calculator-server/pkg/mcp"
)

func TestStreamableHTTPTransportIntegrationWithConfig(t *testing.T) {
	// Create config
	cfg := config.Default()
	cfg.Server.Transport = "http"
	cfg.Server.HTTP.Host = "localhost"
	cfg.Server.HTTP.Port = 8084 // Use different port for test
	cfg.Server.HTTP.CORS.Enabled = true
	cfg.Server.HTTP.CORS.Origins = []string{"*"}

	// Create MCP server
	server := mcp.NewServer()

	// Register handlers
	mathHandler := handlers.NewMathHandler()
	statsHandler := handlers.NewStatsHandler()

	server.RegisterTool("basic_math", "Basic math operations", getBasicMathSchema(), mathHandler.HandleBasicMath)
	server.RegisterTool("statistics", "Statistical analysis", getStatisticsSchema(), statsHandler.HandleStatistics)

	// Create streamable HTTP transport with config
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

	// Test MCP endpoint with basic requests
	t.Run("MCP Tools List via HTTP POST", func(t *testing.T) {
		mcpRequest := types.MCPRequest{
			JSONRPC: "2.0",
			ID:      1,
			Method:  "tools/list",
		}

		requestBody, _ := json.Marshal(mcpRequest)

		client := &http.Client{Timeout: 5 * time.Second}
		req, _ := http.NewRequest("POST", fmt.Sprintf("http://localhost:%d/mcp", cfg.Server.HTTP.Port), bytes.NewBuffer(requestBody))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json")
		req.Header.Set("MCP-Protocol-Version", "2024-11-05")

		resp, err := client.Do(req)
		if err != nil {
			t.Fatalf("Request failed: %v", err)
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

	t.Run("MCP Basic Math Call via HTTP POST", func(t *testing.T) {
		mcpRequest := types.MCPRequest{
			JSONRPC: "2.0",
			ID:      1,
			Method:  "tools/call",
			Params:  json.RawMessage(`{"name":"basic_math","arguments":{"operation":"add","operands":[10,20,30],"precision":2}}`),
		}

		requestBody, _ := json.Marshal(mcpRequest)

		client := &http.Client{Timeout: 5 * time.Second}
		req, _ := http.NewRequest("POST", fmt.Sprintf("http://localhost:%d/mcp", cfg.Server.HTTP.Port), bytes.NewBuffer(requestBody))
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

	t.Run("CORS Headers", func(t *testing.T) {
		client := &http.Client{Timeout: 5 * time.Second}
		req, _ := http.NewRequest("OPTIONS", fmt.Sprintf("http://localhost:%d/mcp", cfg.Server.HTTP.Port), nil)
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

func TestMCPProtocolCompliance(t *testing.T) {
	// Test that our implementation follows MCP specification exactly
	server := mcp.NewServer()
	mathHandler := handlers.NewMathHandler()
	server.RegisterTool("basic_math", "Basic math operations", getBasicMathSchema(), mathHandler.HandleBasicMath)

	config := &mcp.StreamableHTTPConfig{
		Host:           "127.0.0.1",
		Port:           8085,
		SessionTimeout: 5 * time.Minute,
		MaxConnections: 100,
		CORSEnabled:    true,
		CORSOrigins:    []string{"*"},
	}

	httpTransport := mcp.NewStreamableHTTPTransport(server, config)

	// Start server for compliance testing
	go func() {
		if err := httpTransport.Start(); err != nil {
			t.Logf("HTTP server error: %v", err)
		}
	}()

	time.Sleep(100 * time.Millisecond)

	t.Run("MCP Protocol Headers Required", func(t *testing.T) {
		client := &http.Client{Timeout: 5 * time.Second}

		// Test missing MCP-Protocol-Version
		req, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/mcp", config.Port), strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`))
		req.Header.Set("Content-Type", "application/json")

		resp, err := client.Do(req)
		if err != nil {
			t.Fatalf("Request failed: %v", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusBadRequest {
			t.Errorf("Expected 400 for missing MCP-Protocol-Version, got %d", resp.StatusCode)
		}
	})

	t.Run("Single MCP Endpoint Only", func(t *testing.T) {
		client := &http.Client{Timeout: 5 * time.Second}

		// Test that non-MCP endpoints don't exist (MCP spec requires single endpoint)
		nonMCPEndpoints := []string{"/health", "/tools", "/metrics", "/status"}

		for _, endpoint := range nonMCPEndpoints {
			req, _ := http.NewRequest("GET", fmt.Sprintf("http://127.0.0.1:%d%s", config.Port, endpoint), nil)
			resp, err := client.Do(req)
			if err != nil {
				continue // Expected for non-existent endpoints
			}
			defer resp.Body.Close()

			if resp.StatusCode == http.StatusOK {
				t.Errorf("Non-MCP endpoint %s should not exist (MCP spec requires single endpoint)", endpoint)
			}
		}
	})

	// Graceful shutdown
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()

	if err := httpTransport.Stop(shutdownCtx); err != nil {
		t.Errorf("Failed to shutdown gracefully: %v", err)
	}
}

// Helper function to get basic math schema
func getBasicMathSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"operation": map[string]interface{}{
				"type": "string",
				"enum": []string{"add", "subtract", "multiply", "divide"},
			},
			"operands": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems": 2,
			},
			"precision": map[string]interface{}{
				"type":    "integer",
				"minimum": 0,
				"maximum": 15,
				"default": 2,
			},
		},
		"required": []string{"operation", "operands"},
	}
}
