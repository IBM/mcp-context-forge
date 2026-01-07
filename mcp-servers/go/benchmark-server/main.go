// -*- coding: utf-8 -*-
// benchmark-server - configurable MCP server for benchmarking and load testing
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// This file implements an MCP (Model Context Protocol) server written in Go
// that can expose an arbitrary number of tools, resources, and prompts for
// benchmarking purposes.
//
// Usage Examples:
//
//   # 1) STDIO transport with default 100 items
//   ./benchmark-server
//
//   # 2) Generate 1000 tools, 500 resources, 200 prompts
//   ./benchmark-server -tools=1000 -resources=500 -prompts=200
//
//   # 3) Large scale test with 10000 items each
//   ./benchmark-server -tools=10000 -resources=10000 -prompts=10000
//
//   # 4) SSE transport for web testing
//   ./benchmark-server -transport=sse -port=8080 -tools=500
//
//   # 5) HTTP transport with authentication
//   ./benchmark-server -transport=http -port=9090 -auth-token=secret123
//
//   # 6) Custom payload sizes per type
//   ./benchmark-server -tools=100 -tool-size=5000 -resource-size=10000 -prompt-size=2000
//
//   # 7) Large tools with small resources
//   ./benchmark-server -tools=1000 -tool-size=50000 -resources=100 -resource-size=500
//
//   # 8) Minimal setup for quick tests
//   ./benchmark-server -tools=10 -resources=5 -prompts=5 -log-level=debug
//
// Build:
//   go build -o benchmark-server .
//
// Claude Desktop Configuration (stdio):
//   {
//     "mcpServers": {
//       "benchmark": {
//         "command": "/path/to/benchmark-server",
//         "args": ["-tools=1000", "-resources=500", "-prompts=200"]
//       }
//     }
//   }

package main

import (
    "context"
    "encoding/json"
    "flag"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "os/signal"
    "strings"
    "sync"
    "syscall"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

/* ------------------------------------------------------------------ */
/*                             constants                              */
/* ------------------------------------------------------------------ */

const (
    appName    = "benchmark-server"
    appVersion = "1.0.0"

    // Default values
    defaultPort           = 8080
    defaultListen         = "0.0.0.0"
    defaultLogLevel       = "info"
    defaultServerCount    = 1
    defaultToolCount      = 100
    defaultResourceCnt    = 100
    defaultPromptCount    = 100
    defaultToolSize       = 1000
    defaultResourceSize   = 1000
    defaultPromptSize     = 1000

    // Server timeouts
    shutdownTimeout = 10 * time.Second

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

var startTime = time.Now()

// versionJSON returns server version information as JSON
func versionJSON() string {
    return fmt.Sprintf(`{"name":%q,"version":%q,"mcp_version":"1.0"}`, appName, appVersion)
}

// healthJSON returns server health status as JSON
func healthJSON() string {
    return fmt.Sprintf(`{"status":"healthy","uptime_seconds":%d}`, int(time.Since(startTime).Seconds()))
}

/* ------------------------------------------------------------------ */
/*                      payload generation                            */
/* ------------------------------------------------------------------ */

// generatePayload creates a text payload of specified size
func generatePayload(name string, size int) string {
    base := fmt.Sprintf("Response from %s. ", name)
    if size <= len(base) {
        return base[:size]
    }

    // Fill the rest with repeating text
    filler := "This is benchmark data. "
    needed := size - len(base)
    count := (needed / len(filler)) + 1

    result := base
    for i := 0; i < count; i++ {
        result += filler
    }

    return result[:size]
}

/* ------------------------------------------------------------------ */
/*                     dynamic handler creators                       */
/* ------------------------------------------------------------------ */

// createToolHandler creates a handler function for a tool
func createToolHandler(toolName string, payloadSize int) func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    return func(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
        payload := generatePayload(toolName, payloadSize)

        response := map[string]interface{}{
            "tool":      toolName,
            "timestamp": time.Now().UTC().Format(time.RFC3339),
            "arguments": req.Params.Arguments,
            "data":      payload,
        }

        jsonData, err := json.Marshal(response)
        if err != nil {
            return mcp.NewToolResultError(fmt.Sprintf("failed to marshal response: %v", err)), nil
        }

        logAt(logDebug, "tool invoked: %s", toolName)
        return mcp.NewToolResultText(string(jsonData)), nil
    }
}

// createResourceHandler creates a handler function for a resource
func createResourceHandler(resourceName string, payloadSize int) func(context.Context, mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
    return func(_ context.Context, _ mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
        payload := generatePayload(resourceName, payloadSize)

        data := map[string]interface{}{
            "resource":  resourceName,
            "timestamp": time.Now().UTC().Format(time.RFC3339),
            "data":      payload,
        }

        jsonData, err := json.Marshal(data)
        if err != nil {
            return nil, fmt.Errorf("failed to marshal resource data: %w", err)
        }

        logAt(logDebug, "resource requested: %s", resourceName)
        return []mcp.ResourceContents{
            mcp.TextResourceContents{
                URI:      fmt.Sprintf("benchmark://%s", resourceName),
                MIMEType: "application/json",
                Text:     string(jsonData),
            },
        }, nil
    }
}

// createPromptHandler creates a handler function for a prompt
func createPromptHandler(promptName string, payloadSize int) func(context.Context, mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
    return func(_ context.Context, req mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
        payload := generatePayload(promptName, payloadSize)

        var promptText strings.Builder
        promptText.WriteString(fmt.Sprintf("Prompt: %s\n\n", promptName))
        promptText.WriteString(fmt.Sprintf("Timestamp: %s\n\n", time.Now().UTC().Format(time.RFC3339)))

        // Include any arguments
        if len(req.Params.Arguments) > 0 {
            promptText.WriteString("Arguments:\n")
            for k, v := range req.Params.Arguments {
                promptText.WriteString(fmt.Sprintf("  - %s: %s\n", k, v))
            }
            promptText.WriteString("\n")
        }

        promptText.WriteString(payload)

        logAt(logDebug, "prompt requested: %s", promptName)
        return &mcp.GetPromptResult{
            Description: fmt.Sprintf("Benchmark prompt %s", promptName),
            Messages: []mcp.PromptMessage{
                {
                    Role:    mcp.RoleUser,
                    Content: mcp.TextContent{Type: "text", Text: promptText.String()},
                },
            },
        }, nil
    }
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
            logAt(logWarn, "missing authorization header from %s", r.RemoteAddr)
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
        logAt(logDebug, "authenticated request from %s", r.RemoteAddr)
        next.ServeHTTP(w, r)
    })
}

/* ------------------------------------------------------------------ */
/*                      server creation helpers                       */
/* ------------------------------------------------------------------ */

// serverConfig holds configuration for creating an MCP server instance
type serverConfig struct {
    toolCount    int
    toolSize     int
    resourceCnt  int
    resourceSize int
    promptCount  int
    promptSize   int
}

// buildMCPServer creates and registers tools/resources/prompts for a server
func buildMCPServer(cfg serverConfig, serverID int, isMultiServer bool) *server.MCPServer {
    name := appName
    if isMultiServer {
        name = fmt.Sprintf("%s-%d", appName, serverID)
    }

    s := server.NewMCPServer(
        name,
        appVersion,
        server.WithToolCapabilities(false),           // No progress reporting needed
        server.WithResourceCapabilities(false, true), // Enable resource capabilities
        server.WithPromptCapabilities(true),          // Enable prompt capabilities
        server.WithLogging(),                         // Enable MCP protocol logging
        server.WithRecovery(),                        // Recover from panics in handlers
    )

    // Register tools
    logAt(logInfo, "[%s] registering %d tools...", name, cfg.toolCount)
    for i := 0; i < cfg.toolCount; i++ {
        toolName := fmt.Sprintf("benchmark_tool_%d", i)
        tool := mcp.NewTool(toolName,
            mcp.WithDescription(fmt.Sprintf("Benchmark tool #%d - returns test data", i)),
            mcp.WithTitleAnnotation(fmt.Sprintf("Benchmark Tool %d", i)),
            mcp.WithReadOnlyHintAnnotation(true),
            mcp.WithString("param1",
                mcp.Description("Optional parameter 1"),
            ),
            mcp.WithString("param2",
                mcp.Description("Optional parameter 2"),
            ),
        )
        s.AddTool(tool, createToolHandler(toolName, cfg.toolSize))
    }
    logAt(logInfo, "[%s] registered %d tools", name, cfg.toolCount)

    // Register resources
    logAt(logInfo, "[%s] registering %d resources...", name, cfg.resourceCnt)
    for i := 0; i < cfg.resourceCnt; i++ {
        var resourceURI, resourceName string
        if isMultiServer {
            // Multi-server mode: include server ID in URI for uniqueness
            resourceName = fmt.Sprintf("resource_%d", i)
            resourceURI = fmt.Sprintf("benchmark://server%d/resource_%d", serverID, i)
        } else {
            // Single server mode: original naming
            resourceName = fmt.Sprintf("benchmark_resource_%d", i)
            resourceURI = fmt.Sprintf("benchmark://%s", resourceName)
        }

        resource := mcp.NewResource(
            resourceURI,
            fmt.Sprintf("Benchmark Resource %d", i),
            mcp.WithResourceDescription(fmt.Sprintf("Benchmark resource #%d - returns test data", i)),
            mcp.WithMIMEType("application/json"),
        )
        s.AddResource(resource, createResourceHandler(resourceName, cfg.resourceSize))
    }
    logAt(logInfo, "[%s] registered %d resources", name, cfg.resourceCnt)

    // Register prompts
    logAt(logInfo, "[%s] registering %d prompts...", name, cfg.promptCount)
    for i := 0; i < cfg.promptCount; i++ {
        promptName := fmt.Sprintf("benchmark_prompt_%d", i)
        prompt := mcp.NewPrompt(promptName,
            mcp.WithPromptDescription(fmt.Sprintf("Benchmark prompt #%d - returns test prompt", i)),
            mcp.WithArgument("arg1",
                mcp.ArgumentDescription("Optional argument 1"),
            ),
            mcp.WithArgument("arg2",
                mcp.ArgumentDescription("Optional argument 2"),
            ),
        )
        s.AddPrompt(prompt, createPromptHandler(promptName, cfg.promptSize))
    }
    logAt(logInfo, "[%s] registered %d prompts", name, cfg.promptCount)

    return s
}

/* ------------------------------------------------------------------ */
/*                     HTTP server runner with shutdown               */
/* ------------------------------------------------------------------ */

// runHTTPServer starts an HTTP server and handles graceful shutdown
func runHTTPServer(ctx context.Context, wg *sync.WaitGroup, addr string, handler http.Handler, serverName string) {
    defer wg.Done()

    srv := &http.Server{
        Addr:    addr,
        Handler: handler,
    }

    // Start server in a goroutine
    go func() {
        logAt(logInfo, "[%s] listening on http://%s", serverName, addr)
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            logAt(logError, "[%s] server error: %v", serverName, err)
        }
    }()

    // Wait for context cancellation (shutdown signal)
    <-ctx.Done()

    // Create shutdown context with timeout
    shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
    defer cancel()

    logAt(logInfo, "[%s] shutting down gracefully...", serverName)
    if err := srv.Shutdown(shutdownCtx); err != nil {
        logAt(logError, "[%s] shutdown error: %v", serverName, err)
    } else {
        logAt(logInfo, "[%s] shutdown complete", serverName)
    }
}

/* ------------------------------------------------------------------ */
/*                              main                                  */
/* ------------------------------------------------------------------ */

func main() {
    /* ---------------------------- flags --------------------------- */
    var (
        transport     = flag.String("transport", "stdio", "Transport: stdio | sse | http")
        addrFlag      = flag.String("addr", "", "Full listen address (host:port) - overrides -listen/-port")
        listenHost    = flag.String("listen", defaultListen, "Listen interface for sse/http")
        port          = flag.Int("port", defaultPort, "TCP port for sse/http")
        serverCount   = flag.Int("server-count", defaultServerCount, "Number of servers to spawn (for multi-server testing)")
        startPort     = flag.Int("start-port", defaultPort, "Starting port for multi-server mode")
        publicURL     = flag.String("public-url", "", "External base URL advertised to SSE clients")
        authToken     = flag.String("auth-token", "", "Bearer token for authentication (SSE/HTTP only)")
        logLevel      = flag.String("log-level", defaultLogLevel, "Logging level: debug|info|warn|error|none")
        toolCount     = flag.Int("tools", defaultToolCount, "Number of tools to generate")
        resourceCnt   = flag.Int("resources", defaultResourceCnt, "Number of resources to generate")
        promptCount   = flag.Int("prompts", defaultPromptCount, "Number of prompts to generate")
        toolSize      = flag.Int("tool-size", defaultToolSize, "Size of tool response payload in bytes")
        resourceSize  = flag.Int("resource-size", defaultResourceSize, "Size of resource response payload in bytes")
        promptSize    = flag.Int("prompt-size", defaultPromptSize, "Size of prompt response payload in bytes")
        showHelp      = flag.Bool("help", false, "Show help message")
    )

    // Custom usage function
    flag.Usage = func() {
        const ind = "  "
        fmt.Fprintf(flag.CommandLine.Output(),
            "%s %s - configurable MCP server for benchmarking\n\n",
            appName, appVersion)
        fmt.Fprintln(flag.CommandLine.Output(), "Options:")
        flag.VisitAll(func(fl *flag.Flag) {
            fmt.Fprintf(flag.CommandLine.Output(), ind+"-%s\n", fl.Name)
            fmt.Fprintf(flag.CommandLine.Output(), ind+ind+"%s (default %q)\n\n",
                fl.Usage, fl.DefValue)
        })
        fmt.Fprintf(flag.CommandLine.Output(),
            "Examples:\n"+
                ind+"%s -tools=1000 -resources=500 -prompts=200\n"+
                ind+"%s -transport=sse -port=8080 -tools=500\n"+
                ind+"%s -tools=100 -tool-size=5000 -resource-size=10000 -prompt-size=2000\n"+
                ind+"%s -tools=10000 -resources=0 -prompts=0 -tool-size=500\n"+
                ind+"%s -transport=sse -server-count=10 -start-port=8080 -tools=100\n"+
                ind+"%s -transport=http -server-count=5 -start-port=9000\n\n"+
                "Environment Variables:\n"+
                ind+"AUTH_TOKEN - Bearer token for authentication (overrides -auth-token flag)\n",
            os.Args[0], os.Args[0], os.Args[0], os.Args[0], os.Args[0], os.Args[0])
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

    logAt(logInfo, "starting %s %s", appName, appVersion)
    logAt(logInfo, "configuration: tools=%d (size=%d) resources=%d (size=%d) prompts=%d (size=%d)",
        *toolCount, *toolSize, *resourceCnt, *resourceSize, *promptCount, *promptSize)

    if *authToken != "" && *transport != "stdio" {
        logAt(logInfo, "authentication enabled with Bearer token")
    }

    // Validate server count for multi-server mode
    if *serverCount < 1 {
        logger.Fatalf("server-count must be at least 1, got %d", *serverCount)
    }

    // stdio transport doesn't support multi-server
    if strings.ToLower(*transport) == "stdio" && *serverCount > 1 {
        logAt(logWarn, "stdio transport does not support multi-server mode, ignoring server-count")
        *serverCount = 1
    }

    if *serverCount > 1 {
        logAt(logInfo, "multi-server mode: spawning %d servers starting at port %d", *serverCount, *startPort)
    }

    /* ----------------------- build server config ------------------ */
    cfg := serverConfig{
        toolCount:    *toolCount,
        toolSize:     *toolSize,
        resourceCnt:  *resourceCnt,
        resourceSize: *resourceSize,
        promptCount:  *promptCount,
        promptSize:   *promptSize,
    }

    /* -------------------- choose transport & serve ---------------- */
    switch strings.ToLower(*transport) {

    /* ---------------------------- stdio -------------------------- */
    case "stdio":
        if *authToken != "" {
            logAt(logWarn, "auth-token is ignored for stdio transport")
        }
        logAt(logInfo, "serving via stdio transport")
        s := buildMCPServer(cfg, 0, false)
        if err := server.ServeStdio(s); err != nil {
            logger.Fatalf("stdio server error: %v", err)
        }

    /* ----------------------------- sse --------------------------- */
    case "sse":
        // Setup signal handling for graceful shutdown
        ctx, cancel := context.WithCancel(context.Background())
        sigChan := make(chan os.Signal, 1)
        signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

        var wg sync.WaitGroup

        // Spawn servers
        for i := 0; i < *serverCount; i++ {
            serverID := i
            currentPort := *startPort + i

            // Override addr for multi-server mode
            var addr string
            if *serverCount > 1 {
                addr = fmt.Sprintf("%s:%d", *listenHost, currentPort)
            } else {
                addr = effectiveAddr(*addrFlag, *listenHost, *port)
            }

            // Build MCP server instance
            s := buildMCPServer(cfg, serverID, *serverCount > 1)

            // Create mux and register handlers
            mux := http.NewServeMux()

            // Configure SSE options
            opts := []server.SSEOption{}
            if *publicURL != "" {
                // Append port to public URL for multi-server
                if *serverCount > 1 {
                    opts = append(opts, server.WithBaseURL(fmt.Sprintf("%s:%d", strings.TrimRight(*publicURL, "/"), currentPort)))
                } else {
                    opts = append(opts, server.WithBaseURL(strings.TrimRight(*publicURL, "/")))
                }
            }

            // Register SSE handler
            sseHandler := server.NewSSEServer(s, opts...)
            mux.Handle("/", sseHandler)

            // Register health and version endpoints
            registerHealthAndVersion(mux)

            // Create handler chain
            var handler http.Handler = mux
            handler = loggingHTTPMiddleware(handler)
            if *authToken != "" {
                handler = authMiddleware(*authToken, handler)
            }

            // Log server info
            serverName := fmt.Sprintf("%s-%d", appName, serverID)
            if *serverCount == 1 {
                serverName = appName
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
            }

            // Start server
            wg.Add(1)
            go runHTTPServer(ctx, &wg, addr, handler, serverName)
        }

        // Wait for interrupt signal
        <-sigChan
        logAt(logInfo, "received shutdown signal, shutting down %d server(s)...", *serverCount)

        // Cancel context to trigger graceful shutdown
        cancel()

        // Wait for all servers to finish shutting down
        wg.Wait()
        logAt(logInfo, "all servers stopped")

    /* ----------------------- streamable http --------------------- */
    case "http":
        // Setup signal handling for graceful shutdown
        ctx, cancel := context.WithCancel(context.Background())
        sigChan := make(chan os.Signal, 1)
        signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

        var wg sync.WaitGroup

        // Spawn servers
        for i := 0; i < *serverCount; i++ {
            serverID := i
            currentPort := *startPort + i

            // Override addr for multi-server mode
            var addr string
            if *serverCount > 1 {
                addr = fmt.Sprintf("%s:%d", *listenHost, currentPort)
            } else {
                addr = effectiveAddr(*addrFlag, *listenHost, *port)
            }

            // Build MCP server instance
            s := buildMCPServer(cfg, serverID, *serverCount > 1)

            // Create mux and register handlers
            mux := http.NewServeMux()

            // Register HTTP handler
            httpHandler := server.NewStreamableHTTPServer(s)
            mux.Handle("/", httpHandler)

            // Register health and version endpoints
            registerHealthAndVersion(mux)

            // Create handler chain
            var handler http.Handler = mux
            handler = loggingHTTPMiddleware(handler)
            if *authToken != "" {
                handler = authMiddleware(*authToken, handler)
            }

            // Log server info
            serverName := fmt.Sprintf("%s-%d", appName, serverID)
            if *serverCount == 1 {
                serverName = appName
                logAt(logInfo, "HTTP server ready on http://%s", addr)
                logAt(logInfo, "  MCP endpoint:     / (POST with JSON-RPC)")
                logAt(logInfo, "  Health check:     /health")
                logAt(logInfo, "  Version info:     /version")
                if *authToken != "" {
                    logAt(logInfo, "  Authentication:   Bearer token required")
                }
            }

            // Start server
            wg.Add(1)
            go runHTTPServer(ctx, &wg, addr, handler, serverName)
        }

        // Wait for interrupt signal
        <-sigChan
        logAt(logInfo, "received shutdown signal, shutting down %d server(s)...", *serverCount)

        // Cancel context to trigger graceful shutdown
        cancel()

        // Wait for all servers to finish shutting down
        wg.Wait()
        logAt(logInfo, "all servers stopped")

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

        // Log the request
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

// statusWriter wraps http.ResponseWriter to capture status code
type statusWriter struct {
    http.ResponseWriter
    status  int
    written bool
}

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

// Flush lets the underlying handler stream (needed for SSE)
func (sw *statusWriter) Flush() {
    if f, ok := sw.ResponseWriter.(http.Flusher); ok {
        if !sw.written {
            sw.WriteHeader(http.StatusOK)
        }
        f.Flush()
    }
}
