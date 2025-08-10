// -*- coding: utf-8 -*-
// fast-time-server - ultra-fast MCP server exposing time-related tools
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti, Manav Gupta
//
// This file implements an MCP (Model Context Protocol) server written in Go
// that provides time-related tools for LLM applications. The server exposes
// both get_system_time and convert_time tools for comprehensive timezone support.
//
// Build:
//   go build -o fast-time-server .
//
// Available Tools:
//   - get_system_time: Returns current time in any IANA timezone
//   - convert_time: Converts time between different timezones
//
// Transport Modes:
//   - stdio: For desktop clients like Claude Desktop (default)
//   - sse: Server-Sent Events for web-based MCP clients
//   - http: HTTP streaming for REST-like interactions
//   - dual: Both SSE and HTTP on the same port (SSE at /sse, HTTP at /http)
//   - rest: REST API endpoints for direct HTTP access (no MCP protocol)
//
// Authentication:
//   Optional Bearer token authentication for SSE and HTTP transports.
//   Use -auth-token flag or AUTH_TOKEN environment variable.
//
// Usage Examples:
//
//   # 1) STDIO transport (for Claude Desktop integration)
//   ./fast-time-server
//   ./fast-time-server -log-level=debug    # with debug logging
//   ./fast-time-server -log-level=none     # silent mode
//
//   # 2) SSE transport (for web clients)
//   # Basic SSE server on localhost:8080
//   ./fast-time-server -transport=sse
//
//   # SSE on all interfaces with custom port
//   ./fast-time-server -transport=sse -listen=0.0.0.0 -port=3000
//
//   # SSE with public URL for remote access
//   ./fast-time-server -transport=sse -port=8080 \
//                      -public-url=https://time.example.com
//
//   # SSE with Bearer token authentication
//   ./fast-time-server -transport=sse -auth-token=secret123
//   # Or using environment variable:
//   AUTH_TOKEN=secret123 ./fast-time-server -transport=sse
//
//   # 3) HTTP transport (for REST-style access)
//   # Basic HTTP server
//   ./fast-time-server -transport=http
//
//   # HTTP with custom address and base path
//   ./fast-time-server -transport=http -addr=127.0.0.1:9090 \
//                      -log-level=debug
//
//   # 4) DUAL mode (both SSE and HTTP)
//   ./fast-time-server -transport=dual -port=8080
//   # SSE will be at /sse, HTTP at /http, REST at /api/v1
//
//   # 5) REST API mode (direct HTTP REST endpoints)
//   ./fast-time-server -transport=rest -port=8080
//   # REST API at /api/v1/* with OpenAPI docs at /api/v1/docs
//
// Endpoint URLs:
//
//   SSE Transport:
//     Events:    http://localhost:8080/sse
//     Messages:  http://localhost:8080/messages
//     Health:    http://localhost:8080/health
//     Version:   http://localhost:8080/version
//
//   HTTP Transport:
//     MCP:       http://localhost:8080/
//     Health:    http://localhost:8080/health
//     Version:   http://localhost:8080/version
//
//   DUAL Transport:
//     SSE Events:    http://localhost:8080/sse
//     SSE Messages:  http://localhost:8080/messages and http://localhost:8080/message
//     HTTP MCP:      http://localhost:8080/http
//     REST API:      http://localhost:8080/api/v1/*
//     API Docs:      http://localhost:8080/api/v1/docs
//     Health:        http://localhost:8080/health
//     Version:       http://localhost:8080/version
//
//   REST Transport:
//     REST API:      http://localhost:8080/api/v1/*
//     API Docs:      http://localhost:8080/api/v1/docs
//     OpenAPI:       http://localhost:8080/api/v1/openapi.json
//     Health:        http://localhost:8080/health
//     Version:       http://localhost:8080/version
//
// Authentication Headers:
//   When auth-token is configured, include in requests:
//     Authorization: Bearer <token>
//
//   Example with curl:
//     curl -H "Authorization: Bearer <token>" http://localhost:8080/sse
//
// Claude Desktop Configuration (stdio):
//   Add to claude_desktop_config.json:
//   {
//     "mcpServers": {
//       "fast-time": {
//         "command": "/path/to/fast-time-server",
//         "args": ["-log-level=error"]
//       }
//     }
//   }
//
// Web Client Configuration (SSE with auth):
//   const client = new MCPClient({
//     transport: 'sse',
//     endpoint: 'http://localhost:8080',
//     headers: {
//       'Authorization': 'Bearer secret123'
//     }
//   });
//
// Testing Examples:
//
//   # HTTP Transport - Use POST with JSON-RPC:
//   # Initialize connection
//   curl -X POST http://localhost:8080/ \
//     -H "Content-Type: application/json" \
//     -d '{"jsonrpc":"2.0","method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
//
//   # List available tools
//   curl -X POST http://localhost:8080/ \
//     -H "Content-Type: application/json" \
//     -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
//
//   # Call get_system_time tool
//   curl -X POST http://localhost:8080/ \
//     -H "Content-Type: application/json" \
//     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"America/New_York"}},"id":3}'
//
//   # SSE Transport - For event streaming:
//   # Connect to SSE endpoint (this will stream events)
//   curl -N http://localhost:8080/sse
//
//   # Send messages via the messages endpoint (in another terminal)
//   curl -X POST http://localhost:8080/messages \
//     -H "Content-Type: application/json" \
//     -d '{"jsonrpc":"2.0","method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
//
// Environment Variables:
//   AUTH_TOKEN - Bearer token for authentication (overrides -auth-token flag)
//
// -------------------------------------------------------------------

package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

/* ------------------------------------------------------------------ */
/*                             constants                              */
/* ------------------------------------------------------------------ */

const (
	appName    = "fast-time-server"
	appVersion = "1.5.0"

	// Default values
	defaultPort     = 8080
	defaultListen   = "0.0.0.0"
	defaultLogLevel = "info"

	// Environment variables
	envAuthToken = "AUTH_TOKEN"
)

/* ------------------------------------------------------------------ */
/*                             logging                                */
/* ------------------------------------------------------------------ */

// logLvl represents logging verbosity levels
type logLvl int

const (
	logNone logLvl = iota
	logError
	logWarn
	logInfo
	logDebug
)

var (
	curLvl = logInfo
	logger = log.New(os.Stderr, "", log.LstdFlags)
)

// parseLvl converts a string log level to logLvl type
func parseLvl(s string) logLvl {
	switch strings.ToLower(s) {
	case "debug":
		return logDebug
	case "info":
		return logInfo
	case "warn", "warning":
		return logWarn
	case "error":
		return logError
	case "none", "off", "silent":
		return logNone
	default:
		return logInfo
	}
}

// logAt logs a message if the current log level permits
func logAt(l logLvl, f string, v ...any) {
	if curLvl >= l {
		logger.Printf(f, v...)
	}
}

/* ------------------------------------------------------------------ */
/*                    version / health helpers                        */
/* ------------------------------------------------------------------ */

// versionJSON returns server version information as JSON
func versionJSON() string {
	return fmt.Sprintf(`{"name":%q,"version":%q,"mcp_version":"1.0"}`, appName, appVersion)
}

// healthJSON returns server health status as JSON
func healthJSON() string {
	return fmt.Sprintf(`{"status":"healthy","uptime_seconds":%d}`, int(time.Since(startTime).Seconds()))
}

var startTime = time.Now()

/* ------------------------------------------------------------------ */
/*                         timezone cache                             */
/* ------------------------------------------------------------------ */

// tzCache stores loaded time.Location objects to avoid repeated parsing
var tzCache sync.Map

// loadLocation loads a timezone location, using cache when possible
func loadLocation(name string) (*time.Location, error) {
	// Check cache first
	if loc, ok := tzCache.Load(name); ok {
		return loc.(*time.Location), nil
	}

	// Load from system
	loc, err := time.LoadLocation(name)
	if err != nil {
		return nil, fmt.Errorf("invalid timezone %q: %w", name, err)
	}

	// Cache for future use
	tzCache.Store(name, loc)
	return loc, nil
}

/* ------------------------------------------------------------------ */
/*                         tool handlers                              */
/* ------------------------------------------------------------------ */

// handleGetSystemTime returns the current time in the specified timezone
func handleGetSystemTime(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	// Get timezone parameter with UTC as default
	tz := req.GetString("timezone", "UTC")

	// Load timezone location
	loc, err := loadLocation(tz)
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	// Get current time in the specified timezone
	now := time.Now().In(loc).Format(time.RFC3339)

	logAt(logInfo, "get_system_time: timezone=%s result=%s", tz, now)
	return mcp.NewToolResultText(now), nil
}

// handleConvertTime converts time between different timezones
func handleConvertTime(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	// Get required parameters
	timeStr, err := req.RequireString("time")
	if err != nil {
		return mcp.NewToolResultError("time parameter is required"), nil
	}

	sourceTimezone, err := req.RequireString("source_timezone")
	if err != nil {
		return mcp.NewToolResultError("source_timezone parameter is required"), nil
	}

	targetTimezone, err := req.RequireString("target_timezone")
	if err != nil {
		return mcp.NewToolResultError("target_timezone parameter is required"), nil
	}

	// Load source timezone
	sourceLoc, err := loadLocation(sourceTimezone)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("invalid source timezone: %v", err)), nil
	}

	// Load target timezone
	targetLoc, err := loadLocation(targetTimezone)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("invalid target timezone: %v", err)), nil
	}

	// Parse the time string in the source timezone
	parsedTime, err := time.ParseInLocation(time.RFC3339, timeStr, sourceLoc)
	if err != nil {
		// Try other common formats
		for _, format := range []string{
			"2006-01-02 15:04:05",
			"2006-01-02T15:04:05",
			"2006-01-02",
		} {
			if parsedTime, err = time.ParseInLocation(format, timeStr, sourceLoc); err == nil {
				break
			}
		}
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("invalid time format: %v", err)), nil
		}
	}

	// Convert to target timezone
	convertedTime := parsedTime.In(targetLoc).Format(time.RFC3339)

	logAt(logInfo, "convert_time: %s from %s to %s = %s", timeStr, sourceTimezone, targetTimezone, convertedTime)
	return mcp.NewToolResultText(convertedTime), nil
}

/* ------------------------------------------------------------------ */
/*                       authentication middleware                    */
/* ------------------------------------------------------------------ */

// authMiddleware creates a middleware that checks for Bearer token authentication
func authMiddleware(token string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Skip auth for health and version endpoints
		if r.URL.Path == "/health" || r.URL.Path == "/version" {
			next.ServeHTTP(w, r)
			return
		}

		// Get Authorization header
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			logAt(logWarn, "missing authorization header from %s for %s", r.RemoteAddr, r.URL.Path)
			w.Header().Set("WWW-Authenticate", `Bearer realm="MCP Server"`)
			http.Error(w, "Authorization required", http.StatusUnauthorized)
			return
		}

		// Check Bearer token format
		const bearerPrefix = "Bearer "
		if !strings.HasPrefix(authHeader, bearerPrefix) {
			logAt(logWarn, "invalid authorization format from %s", r.RemoteAddr)
			http.Error(w, "Invalid authorization format", http.StatusUnauthorized)
			return
		}

		// Verify token
		providedToken := strings.TrimPrefix(authHeader, bearerPrefix)
		if providedToken != token {
			logAt(logWarn, "invalid token from %s", r.RemoteAddr)
			http.Error(w, "Invalid token", http.StatusUnauthorized)
			return
		}

		// Token valid, proceed with request
		logAt(logDebug, "authenticated request from %s to %s", r.RemoteAddr, r.URL.Path)
		next.ServeHTTP(w, r)
	})
}

/* ------------------------------------------------------------------ */
/*                              main                                  */
/* ------------------------------------------------------------------ */

func main() {
	/* ---------------------------- flags --------------------------- */
	var (
		transport  = flag.String("transport", "stdio", "Transport: stdio | sse | http | dual | rest")
		addrFlag   = flag.String("addr", "", "Full listen address (host:port) - overrides -listen/-port")
		listenHost = flag.String("listen", defaultListen, "Listen interface for sse/http")
		port       = flag.Int("port", defaultPort, "TCP port for sse/http")
		publicURL  = flag.String("public-url", "", "External base URL advertised to SSE clients")
		authToken  = flag.String("auth-token", "", "Bearer token for authentication (SSE/HTTP only)")
		logLevel   = flag.String("log-level", defaultLogLevel, "Logging level: debug|info|warn|error|none")
		showHelp   = flag.Bool("help", false, "Show help message")
	)

	// Custom usage function
	flag.Usage = func() {
		const ind = "  "
		fmt.Fprintf(flag.CommandLine.Output(),
			"%s %s - ultra-fast time service for LLM agents via MCP\n\n",
			appName, appVersion)
		fmt.Fprintln(flag.CommandLine.Output(), "Options:")
		flag.VisitAll(func(fl *flag.Flag) {
			fmt.Fprintf(flag.CommandLine.Output(), ind+"-%s\n", fl.Name)
			fmt.Fprintf(flag.CommandLine.Output(), ind+ind+"%s (default %q)\n\n",
				fl.Usage, fl.DefValue)
		})
		fmt.Fprintf(flag.CommandLine.Output(),
			"Examples:\n"+
				ind+"%s -transport=stdio -log-level=none\n"+
				ind+"%s -transport=sse -listen=0.0.0.0 -port=8080\n"+
				ind+"%s -transport=http -addr=127.0.0.1:9090\n"+
				ind+"%s -transport=dual -port=8080 -auth-token=secret123\n"+
				ind+"%s -transport=rest -port=8080\n\n"+
				"MCP Protocol Endpoints:\n"+
				ind+"SSE:  /sse (events), /messages (messages)\n"+
				ind+"HTTP: / (single endpoint)\n"+
				ind+"DUAL: /sse & /messages (SSE), /http (HTTP), /api/v1/* (REST)\n"+
				ind+"REST: /api/v1/* (REST API only, no MCP)\n\n"+
				"Environment Variables:\n"+
				ind+"AUTH_TOKEN - Bearer token for authentication (overrides -auth-token flag)\n",
			os.Args[0], os.Args[0], os.Args[0], os.Args[0], os.Args[0])
	}

	flag.Parse()

	if *showHelp {
		flag.Usage()
		os.Exit(0)
	}

	/* ----------------------- configuration setup ------------------ */
	// Check for auth token in environment variable (overrides flag)
	if envToken := os.Getenv(envAuthToken); envToken != "" {
		*authToken = envToken
		logAt(logDebug, "using auth token from environment variable")
	}

	/* ------------------------- logging setup ---------------------- */
	curLvl = parseLvl(*logLevel)
	if curLvl == logNone {
		logger.SetOutput(io.Discard)
	}

	logAt(logDebug, "starting %s %s", appName, appVersion)
	if *authToken != "" && *transport != "stdio" {
		logAt(logInfo, "authentication enabled with Bearer token")
	}

	/* ----------------------- build MCP server --------------------- */
	// Create server with appropriate options
	s := server.NewMCPServer(
		appName,
		appVersion,
		server.WithToolCapabilities(false), // No progress reporting needed
		server.WithLogging(),               // Enable MCP protocol logging
		server.WithRecovery(),              // Recover from panics in handlers
	)

	/* ----------------------- register tools ----------------------- */
	// Register get_system_time tool
	getTimeTool := mcp.NewTool("get_system_time",
		mcp.WithDescription("Get current system time in specified timezone"),
		mcp.WithString("timezone",
			mcp.Description("IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Defaults to UTC"),
		),
	)
	s.AddTool(getTimeTool, handleGetSystemTime)

	// Register convert_time tool
	convertTimeTool := mcp.NewTool("convert_time",
		mcp.WithDescription("Convert time between different timezones"),
		mcp.WithString("time",
			mcp.Required(),
			mcp.Description("Time to convert in RFC3339 format or common formats like '2006-01-02 15:04:05'"),
		),
		mcp.WithString("source_timezone",
			mcp.Required(),
			mcp.Description("Source IANA timezone name"),
		),
		mcp.WithString("target_timezone",
			mcp.Required(),
			mcp.Description("Target IANA timezone name"),
		),
	)
	s.AddTool(convertTimeTool, handleConvertTime)

	/* -------------------- choose transport & serve ---------------- */
	switch strings.ToLower(*transport) {

	/* ---------------------------- stdio -------------------------- */
	case "stdio":
		if *authToken != "" {
			logAt(logWarn, "auth-token is ignored for stdio transport")
		}
		logAt(logInfo, "serving via stdio transport")
		if err := server.ServeStdio(s); err != nil {
			logger.Fatalf("stdio server error: %v", err)
		}

	/* ----------------------------- sse --------------------------- */
	case "sse":
		addr := effectiveAddr(*addrFlag, *listenHost, *port)
		mux := http.NewServeMux()

		// Configure SSE options - no base path for root serving
		opts := []server.SSEOption{}
		if *publicURL != "" {
			// Ensure public URL doesn't have trailing slash
			opts = append(opts, server.WithBaseURL(strings.TrimRight(*publicURL, "/")))
		}

		// Register SSE handler at root
		sseHandler := server.NewSSEServer(s, opts...)
		mux.Handle("/", sseHandler)

		// Register health and version endpoints
		registerHealthAndVersion(mux)

		logAt(logInfo, "SSE server ready on http://%s", addr)
		logAt(logInfo, "  MCP SSE events:   /sse")
		logAt(logInfo, "  MCP SSE messages: /messages")
		logAt(logInfo, "  Health check:     /health")
		logAt(logInfo, "  Version info:     /version")

		if *publicURL != "" {
			logAt(logInfo, "  Public URL:       %s", *publicURL)
		}

		if *authToken != "" {
			logAt(logInfo, "  Authentication:   Bearer token required")
		}

		// Create handler chain
		var handler http.Handler = mux
		handler = loggingHTTPMiddleware(handler)
		if *authToken != "" {
			handler = authMiddleware(*authToken, handler)
		}

		// Start server
		if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
			logger.Fatalf("SSE server error: %v", err)
		}

	/* ----------------------- streamable http --------------------- */
	case "http":
		addr := effectiveAddr(*addrFlag, *listenHost, *port)
		mux := http.NewServeMux()

		// Register HTTP handler at root
		httpHandler := server.NewStreamableHTTPServer(s)
		mux.Handle("/", httpHandler)

		// Register health and version endpoints
		registerHealthAndVersion(mux)

		// Add a helpful GET handler for root
		mux.HandleFunc("/info", func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"message":"MCP HTTP server ready","instructions":"Use POST requests with JSON-RPC 2.0 payloads","example":{"jsonrpc":"2.0","method":"tools/list","id":1}}`)
		})

		logAt(logInfo, "HTTP server ready on http://%s", addr)
		logAt(logInfo, "  MCP endpoint:     / (POST with JSON-RPC)")
		logAt(logInfo, "  Info:             /info")
		logAt(logInfo, "  Health check:     /health")
		logAt(logInfo, "  Version info:     /version")

		if *authToken != "" {
			logAt(logInfo, "  Authentication:   Bearer token required")
		}

		// Example command
		logAt(logInfo, "Test with: curl -X POST http://%s/ -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'", addr)

		// Create handler chain
		var handler http.Handler = mux
		handler = loggingHTTPMiddleware(handler)
		if *authToken != "" {
			handler = authMiddleware(*authToken, handler)
		}

		// Start server
		if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
			logger.Fatalf("HTTP server error: %v", err)
		}

	/* ---------------------------- dual --------------------------- */
	case "dual":
		addr := effectiveAddr(*addrFlag, *listenHost, *port)
		mux := http.NewServeMux()

		// Configure SSE handler for /sse and /messages
		sseOpts := []server.SSEOption{}
		if *publicURL != "" {
			sseOpts = append(sseOpts, server.WithBaseURL(strings.TrimRight(*publicURL, "/")))
		}
		sseHandler := server.NewSSEServer(s, sseOpts...)

		// Configure HTTP handler for /http
		httpHandler := server.NewStreamableHTTPServer(s, server.WithEndpointPath("/http"))

		// Register handlers
		mux.Handle("/sse", sseHandler)
		mux.Handle("/messages", sseHandler) // Support plural (backward compatibility)
		mux.Handle("/message", sseHandler)  // Support singular (MCP Gateway compatibility)
		mux.Handle("/http", httpHandler)

		// Register REST API handlers
		registerRESTHandlers(mux)

		// Register health and version endpoints
		registerHealthAndVersion(mux)

		logAt(logInfo, "DUAL server ready on http://%s", addr)
		logAt(logInfo, "  SSE events:       /sse")
		logAt(logInfo, "  SSE messages:     /messages (plural) and /message (singular)")
		logAt(logInfo, "  HTTP endpoint:    /http")
		logAt(logInfo, "  REST API:         /api/v1/*")
		logAt(logInfo, "  API Docs:         /api/v1/docs")
		logAt(logInfo, "  Health check:     /health")
		logAt(logInfo, "  Version info:     /version")

		if *publicURL != "" {
			logAt(logInfo, "  Public URL:       %s", *publicURL)
		}

		if *authToken != "" {
			logAt(logInfo, "  Authentication:   Bearer token required")
		}

		// Create handler chain
		var handler http.Handler = mux
		handler = corsMiddleware(handler) // Add CORS support for REST API
		handler = loggingHTTPMiddleware(handler)
		if *authToken != "" {
			handler = authMiddleware(*authToken, handler)
		}

		// Start server
		if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
			logger.Fatalf("DUAL server error: %v", err)
		}

	/* ---------------------------- rest --------------------------- */
	case "rest":
		addr := effectiveAddr(*addrFlag, *listenHost, *port)
		mux := http.NewServeMux()

		// Register REST API handlers
		registerRESTHandlers(mux)

		// Register health and version endpoints
		registerHealthAndVersion(mux)

		logAt(logInfo, "REST API server ready on http://%s", addr)
		logAt(logInfo, "  API Base:         /api/v1")
		logAt(logInfo, "  API Docs:         /api/v1/docs")
		logAt(logInfo, "  OpenAPI Spec:     /api/v1/openapi.json")
		logAt(logInfo, "  Health check:     /health")
		logAt(logInfo, "  Version info:     /version")

		if *authToken != "" {
			logAt(logInfo, "  Authentication:   Bearer token required")
		}

		// Example commands
		logAt(logInfo, "Test commands:")
		logAt(logInfo, "  Get time:    curl http://%s/api/v1/time?timezone=UTC", addr)
		logAt(logInfo, "  List zones:  curl http://%s/api/v1/timezones", addr)
		logAt(logInfo, "  Echo test:   curl http://%s/api/v1/test/echo", addr)

		// Create handler chain
		var handler http.Handler = mux
		handler = corsMiddleware(handler) // Add CORS support
		handler = loggingHTTPMiddleware(handler)
		if *authToken != "" {
			handler = authMiddleware(*authToken, handler)
		}

		// Start server
		if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
			logger.Fatalf("REST server error: %v", err)
		}

	default:
		fmt.Fprintf(os.Stderr, "Error: unknown transport %q\n\n", *transport)
		flag.Usage()
		os.Exit(2)
	}
}

/* ------------------------------------------------------------------ */
/*                        helper functions                            */
/* ------------------------------------------------------------------ */

// effectiveAddr determines the actual address to listen on
func effectiveAddr(addrFlag, listen string, port int) string {
	if addrFlag != "" {
		return addrFlag
	}
	return fmt.Sprintf("%s:%d", listen, port)
}

// registerHealthAndVersion adds health and version endpoints to the mux
func registerHealthAndVersion(mux *http.ServeMux) {
	// Health endpoint - JSON response
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(healthJSON()))
	})

	// Version endpoint - JSON response
	mux.HandleFunc("/version", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(versionJSON()))
	})
}

/* -------------------- HTTP middleware ----------------------------- */

// loggingHTTPMiddleware provides request logging when log level permits
func loggingHTTPMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if curLvl < logInfo {
			next.ServeHTTP(w, r)
			return
		}

		start := time.Now()

		// Wrap response writer to capture status code
		rw := &statusWriter{ResponseWriter: w, status: http.StatusOK, written: false}

		// Call the next handler
		next.ServeHTTP(rw, r)

		// Log the request with body size for POST requests
		duration := time.Since(start)
		if r.Method == "POST" && curLvl >= logDebug {
			logAt(logDebug, "%s %s %s %d (Content-Length: %s) %v",
				r.RemoteAddr, r.Method, r.URL.Path, rw.status, r.Header.Get("Content-Length"), duration)
		} else {
			logAt(logInfo, "%s %s %s %d %v",
				r.RemoteAddr, r.Method, r.URL.Path, rw.status, duration)
		}
	})
}

// statusWriter wraps http.ResponseWriter so we can capture the status code
// *and* still pass through streaming-related interfaces (Flusher, Hijacker,
// CloseNotifier) that SSE / HTTP streaming require.
type statusWriter struct {
	http.ResponseWriter
	status  int
	written bool
}

/* -------- core ResponseWriter behaviour -------- */

func (sw *statusWriter) WriteHeader(code int) {
	if !sw.written {
		sw.status = code
		sw.written = true
		sw.ResponseWriter.WriteHeader(code)
	}
}

func (sw *statusWriter) Write(b []byte) (int, error) {
	if !sw.written {
		sw.WriteHeader(http.StatusOK)
	}
	return sw.ResponseWriter.Write(b)
}

/* -------- pass-through for streaming interfaces -------- */

// Flush lets the underlying handler stream (needed for SSE)
func (sw *statusWriter) Flush() {
	if f, ok := sw.ResponseWriter.(http.Flusher); ok {
		if !sw.written {
			sw.WriteHeader(http.StatusOK)
		}
		f.Flush()
	}
}

// Hijack lets handlers switch to raw TCP (not used by SSE but good hygiene)
func (sw *statusWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	if h, ok := sw.ResponseWriter.(http.Hijacker); ok {
		return h.Hijack()
	}
	return nil, nil, fmt.Errorf("hijacking not supported")
}

// CloseNotify keeps SSE clients informed if the peer goes away
// Deprecated: Use Request.Context() instead. Kept for compatibility with older SSE implementations.
func (sw *statusWriter) CloseNotify() <-chan bool {
	// nolint:staticcheck // SA1019: http.CloseNotifier is deprecated but required for SSE compatibility
	if cn, ok := sw.ResponseWriter.(http.CloseNotifier); ok {
		return cn.CloseNotify()
	}
	// If the underlying writer doesn't support it, fabricate a never-closing chan
	done := make(chan bool, 1)
	return done
}
