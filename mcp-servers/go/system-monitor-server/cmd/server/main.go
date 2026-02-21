// -*- coding: utf-8 -*-
// system-monitor-server - comprehensive system monitoring MCP server
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti, Manav Gupta
//
// This file implements an MCP (Model Context Protocol) server written in Go
// that provides comprehensive system monitoring capabilities including process
// management, resource usage, and system health metrics.
//
// Build:
//   go build -o system-monitor-server ./cmd/server
//
// Available Tools:
//   - get_system_metrics: Retrieve current system resource usage
//   - list_processes: List running processes with filtering options
//   - monitor_process: Monitor specific process health and resource usage
//   - check_service_health: Check health of system services and applications
//   - tail_logs: Stream log file contents with filtering
//   - get_disk_usage: Analyze disk usage with detailed breakdowns
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
//   ./system-monitor-server
//   ./system-monitor-server -log-level=debug    # with debug logging
//   ./system-monitor-server -log-level=none     # silent mode
//
//   # 2) SSE transport (for web clients)
//   # Basic SSE server on localhost:8080
//   ./system-monitor-server -transport=sse
//
//   # SSE on all interfaces with custom port
//   ./system-monitor-server -transport=sse -listen=0.0.0.0 -port=3000
//
//   # SSE with public URL for remote access
//   ./system-monitor-server -transport=sse -port=8080 \
//                      -public-url=https://monitor.example.com
//
//   # SSE with Bearer token authentication
//   ./system-monitor-server -transport=sse -auth-token=secret123
//   # Or using environment variable:
//   AUTH_TOKEN=secret123 ./system-monitor-server -transport=sse
//
//   # 3) HTTP transport (for REST-style access)
//   # Basic HTTP server
//   ./system-monitor-server -transport=http
//
//   # HTTP with custom address and base path
//   ./system-monitor-server -transport=http -addr=127.0.0.1:9090 \
//                      -log-level=debug
//
//   # 4) DUAL mode (both SSE and HTTP)
//   ./system-monitor-server -transport=dual -port=8080
//   # SSE will be at /sse, HTTP at /http, REST at /api/v1
//
//   # 5) REST API mode (direct HTTP REST endpoints)
//   ./system-monitor-server -transport=rest -port=8080
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
//       "system-monitor": {
//         "command": "/path/to/system-monitor-server",
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
//   # Call get_system_metrics tool
//   curl -X POST http://localhost:8080/ \
//     -H "Content-Type: application/json" \
//     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_metrics","arguments":{}},"id":3}'
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
    "encoding/json"
    "flag"
    "fmt"
    "io"
    "log"
    "math"
    "net"
    "net/http"
    "os"
    "strings"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/internal/config"
    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/internal/metrics"
    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/internal/monitor"
    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

/* ------------------------------------------------------------------ */
/*                             constants                              */
/* ------------------------------------------------------------------ */

const (
    appName    = "system-monitor-server"
    appVersion = "1.0.0"

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
/*                         tool handlers                              */
/* ------------------------------------------------------------------ */

// handleGetSystemMetrics returns current system resource usage
func handleGetSystemMetrics(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    collector := metrics.NewSystemCollector()
    metrics, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to get system metrics: %v", err)), nil
    }

    jsonData, err := json.Marshal(metrics)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal metrics: %v", err)), nil
    }

    logAt(logInfo, "get_system_metrics: collected system metrics")
    return mcp.NewToolResultText(string(jsonData)), nil
}

// handleListProcesses lists running processes with filtering options
func handleListProcesses(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    // Parse request parameters
    processReq := &types.ProcessListRequest{
        FilterBy:       req.GetString("filter_by", ""),
        FilterValue:    req.GetString("filter_value", ""),
        SortBy:         req.GetString("sort_by", "cpu"),
        Limit:          req.GetInt("limit", 0),
        IncludeThreads: req.GetBool("include_threads", false),
    }

    collector := metrics.NewProcessCollector()
    processes, err := collector.ListProcesses(ctx, processReq)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to list processes: %v", err)), nil
    }

    jsonData, err := json.Marshal(processes)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal processes: %v", err)), nil
    }

    logAt(logInfo, "list_processes: found %d processes", len(processes))
    return mcp.NewToolResultText(string(jsonData)), nil
}

// handleMonitorProcess monitors a specific process for a given duration
func handleMonitorProcess(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    // Parse request parameters
    pidValue := req.GetInt("pid", 0)
    if pidValue < 0 || pidValue > math.MaxInt32 {
        return mcp.NewToolResultError("pid must be between 0 and 2147483647"), nil
    }

    processReq := &types.ProcessMonitorRequest{
        PID:         int32(pidValue),
        ProcessName: req.GetString("process_name", ""),
        Duration:    req.GetInt("duration", 60),
        Interval:    req.GetInt("interval", 5),
    }

    // Parse alert thresholds if provided
    if cpuThreshold := req.GetFloat("cpu_threshold", 0); cpuThreshold > 0 {
        processReq.AlertThresholds.CPUPercent = cpuThreshold
    }
    if memThreshold := req.GetFloat("memory_threshold", 0); memThreshold > 0 {
        processReq.AlertThresholds.MemoryPercent = memThreshold
    }
    if memRSSThreshold := req.GetInt("memory_rss_threshold", 0); memRSSThreshold > 0 {
        processReq.AlertThresholds.MemoryRSS = uint64(memRSSThreshold)
    }

    collector := metrics.NewProcessCollector()
    results, err := collector.MonitorProcess(ctx, processReq)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to monitor process: %v", err)), nil
    }

    jsonData, err := json.Marshal(results)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal monitoring results: %v", err)), nil
    }

    logAt(logInfo, "monitor_process: monitored process for %d seconds", processReq.Duration)
    return mcp.NewToolResultText(string(jsonData)), nil
}

// handleCheckServiceHealth checks health of system services
func handleCheckServiceHealth(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    // Parse services from request
    servicesJSON := req.GetString("services", "[]")
    var services []types.ServiceCheck
    if err := json.Unmarshal([]byte(servicesJSON), &services); err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to parse services: %v", err)), nil
    }

    healthReq := &types.HealthCheckRequest{
        Services: services,
        Timeout:  req.GetInt("timeout", 10),
    }

    checker := monitor.NewHealthChecker()
    results, err := checker.CheckServiceHealth(ctx, healthReq)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to check service health: %v", err)), nil
    }

    jsonData, err := json.Marshal(results)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal health check results: %v", err)), nil
    }

    logAt(logInfo, "check_service_health: checked %d services", len(services))
    return mcp.NewToolResultText(string(jsonData)), nil
}

// handleTailLogs streams log file contents with filtering
func handleTailLogs(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    // Parse request parameters
    logReq := &types.LogTailRequest{
        FilePath: req.GetString("file_path", ""),
        Lines:    req.GetInt("lines", 100),
        Follow:   req.GetBool("follow", false),
        Filter:   req.GetString("filter", ""),
        MaxSize:  int64(req.GetInt("max_size", 0)),
    }

    if logReq.FilePath == "" {
        return mcp.NewToolResultError("file_path parameter is required"), nil
    }

    // Create log monitor with default security settings
    cfg := config.DefaultConfig()
    monitor := monitor.NewLogMonitor(cfg.Security.RootPath, cfg.Security.AllowedPaths, cfg.Security.MaxFileSize)

    result, err := monitor.TailLogs(ctx, logReq)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to tail logs: %v", err)), nil
    }

    jsonData, err := json.Marshal(result)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal log tail result: %v", err)), nil
    }

    logAt(logInfo, "tail_logs: tailed %d lines from %s", result.TotalLines, logReq.FilePath)
    return mcp.NewToolResultText(string(jsonData)), nil
}

// handleGetDiskUsage analyzes disk usage with detailed breakdowns
func handleGetDiskUsage(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    // Parse request parameters
    diskReq := &types.DiskUsageRequest{
        Path:      req.GetString("path", "."),
        MaxDepth:  req.GetInt("max_depth", 0),
        MinSize:   int64(req.GetInt("min_size", 0)),
        SortBy:    req.GetString("sort_by", "size"),
        FileTypes: req.GetStringSlice("file_types", []string{}),
    }

    // Create log monitor with default security settings
    cfg := config.DefaultConfig()
    monitor := monitor.NewLogMonitor(cfg.Security.RootPath, cfg.Security.AllowedPaths, cfg.Security.MaxFileSize)

    result, err := monitor.GetDiskUsage(ctx, diskReq)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to get disk usage: %v", err)), nil
    }

    jsonData, err := json.Marshal(result)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("failed to marshal disk usage result: %v", err)), nil
    }

    logAt(logInfo, "get_disk_usage: analyzed %d items in %s", result.ItemCount, diskReq.Path)
    return mcp.NewToolResultText(string(jsonData)), nil
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
            "%s %s - comprehensive system monitoring for LLM agents via MCP\n\n",
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
            appName, appName, appName, appName, appName)
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
        server.WithResourceCapabilities(false, false), // No resource capabilities
        server.WithPromptCapabilities(false),          // No prompt capabilities
        server.WithLogging(),                          // Enable MCP protocol logging
        server.WithRecovery(),                         // Recover from panics in handlers
    )

    /* ----------------------- register tools ----------------------- */
    // Register get_system_metrics tool
    getSystemMetricsTool := mcp.NewTool("get_system_metrics",
        mcp.WithDescription("Get current system resource usage including CPU, memory, disk, and network metrics"),
        mcp.WithTitleAnnotation("Get System Metrics"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
    )
    s.AddTool(getSystemMetricsTool, handleGetSystemMetrics)

    // Register list_processes tool
    listProcessesTool := mcp.NewTool("list_processes",
        mcp.WithDescription("List running processes with filtering and sorting options"),
        mcp.WithTitleAnnotation("List Processes"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("filter_by",
            mcp.Description("Filter processes by: name, user, pid"),
        ),
        mcp.WithString("filter_value",
            mcp.Description("Value to filter by"),
        ),
        mcp.WithString("sort_by",
            mcp.Description("Sort processes by: cpu, memory, name, pid (default: cpu)"),
        ),
        mcp.WithNumber("limit",
            mcp.Description("Maximum number of processes to return (0 = no limit)"),
        ),
        mcp.WithBoolean("include_threads",
            mcp.Description("Include thread count information"),
        ),
    )
    s.AddTool(listProcessesTool, handleListProcesses)

    // Register monitor_process tool
    monitorProcessTool := mcp.NewTool("monitor_process",
        mcp.WithDescription("Monitor specific process health and resource usage over time"),
        mcp.WithTitleAnnotation("Monitor Process"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithNumber("pid",
            mcp.Description("Process ID to monitor"),
        ),
        mcp.WithString("process_name",
            mcp.Description("Process name to monitor (alternative to PID)"),
        ),
        mcp.WithNumber("duration",
            mcp.Description("Monitoring duration in seconds (default: 60)"),
        ),
        mcp.WithNumber("interval",
            mcp.Description("Monitoring interval in seconds (default: 5)"),
        ),
        mcp.WithNumber("cpu_threshold",
            mcp.Description("CPU usage threshold for alerts (percentage)"),
        ),
        mcp.WithNumber("memory_threshold",
            mcp.Description("Memory usage threshold for alerts (percentage)"),
        ),
        mcp.WithNumber("memory_rss_threshold",
            mcp.Description("Memory RSS threshold for alerts (bytes)"),
        ),
    )
    s.AddTool(monitorProcessTool, handleMonitorProcess)

    // Register check_service_health tool
    checkServiceHealthTool := mcp.NewTool("check_service_health",
        mcp.WithDescription("Check health of system services and applications"),
        mcp.WithTitleAnnotation("Check Service Health"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("services",
            mcp.Required(),
            mcp.Description("JSON array of services to check with name, type, target, and expected values"),
        ),
        mcp.WithNumber("timeout",
            mcp.Description("Timeout in seconds for health checks (default: 10)"),
        ),
    )
    s.AddTool(checkServiceHealthTool, handleCheckServiceHealth)

    // Register tail_logs tool
    tailLogsTool := mcp.NewTool("tail_logs",
        mcp.WithDescription("Stream log file contents with filtering and security controls"),
        mcp.WithTitleAnnotation("Tail Logs"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("file_path",
            mcp.Required(),
            mcp.Description("Path to the log file to tail"),
        ),
        mcp.WithNumber("lines",
            mcp.Description("Number of lines to tail (default: 100)"),
        ),
        mcp.WithBoolean("follow",
            mcp.Description("Follow the file for new lines (default: false)"),
        ),
        mcp.WithString("filter",
            mcp.Description("Regex filter for log lines"),
        ),
        mcp.WithNumber("max_size",
            mcp.Description("Maximum file size to process (bytes)"),
        ),
    )
    s.AddTool(tailLogsTool, handleTailLogs)

    // Register get_disk_usage tool
    getDiskUsageTool := mcp.NewTool("get_disk_usage",
        mcp.WithDescription("Analyze disk usage with detailed breakdowns and filtering"),
        mcp.WithTitleAnnotation("Get Disk Usage"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("path",
            mcp.Description("Path to analyze (default: current directory)"),
        ),
        mcp.WithNumber("max_depth",
            mcp.Description("Maximum directory depth to analyze (0 = unlimited)"),
        ),
        mcp.WithNumber("min_size",
            mcp.Description("Minimum file size to include (bytes)"),
        ),
        mcp.WithString("sort_by",
            mcp.Description("Sort results by: size, name, modified (default: size)"),
        ),
        mcp.WithArray("file_types",
            mcp.Description("Filter by file extensions (e.g., [\"txt\", \"log\"])"),
        ),
    )
    s.AddTool(getDiskUsageTool, handleGetDiskUsage)

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
        if err := serveHTTPWithTimeout(addr, handler); err != nil && err != http.ErrServerClosed {
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
        if err := serveHTTPWithTimeout(addr, handler); err != nil && err != http.ErrServerClosed {
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
        mux.Handle("/message", sseHandler)  // Support singular (ContextForge compatibility)
        mux.Handle("/http", httpHandler)

        // Register health and version endpoints
        registerHealthAndVersion(mux)

        logAt(logInfo, "DUAL server ready on http://%s", addr)
        logAt(logInfo, "  SSE events:       /sse")
        logAt(logInfo, "  SSE messages:     /messages (plural) and /message (singular)")
        logAt(logInfo, "  HTTP endpoint:    /http")
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
        if err := serveHTTPWithTimeout(addr, handler); err != nil && err != http.ErrServerClosed {
            logger.Fatalf("DUAL server error: %v", err)
        }

    /* ---------------------------- rest --------------------------- */
    case "rest":
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        mux := http.NewServeMux()

        // Register health and version endpoints
        registerHealthAndVersion(mux)

        logAt(logInfo, "REST API server ready on http://%s", addr)
        logAt(logInfo, "  Health check:     /health")
        logAt(logInfo, "  Version info:     /version")

        if *authToken != "" {
            logAt(logInfo, "  Authentication:   Bearer token required")
        }

        // Example commands
        logAt(logInfo, "Test commands:")
        logAt(logInfo, "  Get metrics:  curl http://%s/api/v1/metrics", addr)
        logAt(logInfo, "  List processes:  curl http://%s/api/v1/processes", addr)

        // Create handler chain
        var handler http.Handler = mux
        handler = loggingHTTPMiddleware(handler)
        if *authToken != "" {
            handler = authMiddleware(*authToken, handler)
        }

        // Start server
        if err := serveHTTPWithTimeout(addr, handler); err != nil && err != http.ErrServerClosed {
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

func serveHTTPWithTimeout(addr string, handler http.Handler) error {
    srv := &http.Server{
        Addr:              addr,
        Handler:           handler,
        ReadHeaderTimeout: 10 * time.Second,
    }
    return srv.ListenAndServe()
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
