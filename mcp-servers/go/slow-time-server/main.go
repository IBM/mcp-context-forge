// -*- coding: utf-8 -*-
// slow-time-server - configurable-latency MCP server for timeout, resilience, and load testing
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// This file implements an MCP (Model Context Protocol) server written in Go
// that provides time-related tools with configurable artificial latency.
// It serves as a first-class testing target for validating gateway timeout
// enforcement, circuit breaker behaviour, session pool resilience, and
// load testing under realistic slow-tool conditions.
//
// Build:
//
//  go build -o slow-time-server .
//
// Available Tools:
//   - get_slow_time:    Get current time with configurable delay
//   - convert_slow_time: Convert time between timezones with delay
//   - get_instant_time: Get current time with zero delay (baseline)
//   - get_timeout_time: Get current time with 10-minute delay (guaranteed timeout)
//   - get_flaky_time:   Get current time with random failures
//
// Transport Modes:
//   - stdio: For desktop clients like Claude Desktop (default)
//   - sse:   Server-Sent Events for web-based MCP clients
//   - http:  HTTP streaming for REST-like interactions
//   - dual:  Both SSE and HTTP on the same port
//   - rest:  REST API endpoints for direct HTTP access
//
// Usage Examples:
//
//  # Basic: 5-second latency for timeout testing
//  ./slow-time-server -transport=dual -port=8081 -latency=5s
//
//  # Circuit breaker testing: 30% failure rate
//  ./slow-time-server -transport=dual -port=8081 \
//    -latency=2s -failure-rate=0.3 -failure-mode=error -seed=42
//
//  # Realistic distribution: normal with occasional outliers
//  ./slow-time-server -transport=dual -port=8081 \
//    -latency-distribution=normal -latency-mean=5s -latency-stddev=3s
//
// Environment Variables:
//
//  DEFAULT_LATENCY   - Override -latency (e.g., "5s", "30s", "2m")
//  FAILURE_RATE      - Override -failure-rate
//  AUTH_TOKEN        - Override -auth-token
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
    "math/rand"
    "net"
    "net/http"
    "os"
    "strings"
    "sync"
    "sync/atomic"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

/* ------------------------------------------------------------------ */
/*                             constants                              */
/* ------------------------------------------------------------------ */

const (
    appName    = "slow-time-server"
    appVersion = "1.0.0"

    defaultPort     = 8081
    defaultListen   = "0.0.0.0"
    defaultLogLevel = "info"

    envAuthToken      = "AUTH_TOKEN"
    envDefaultLatency = "DEFAULT_LATENCY"
    envFailureRate    = "FAILURE_RATE"
)

/* ------------------------------------------------------------------ */
/*                             logging                                */
/* ------------------------------------------------------------------ */

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

func logAt(l logLvl, f string, v ...any) {
    if curLvl >= l {
        logger.Printf(f, v...)
    }
}

/* ------------------------------------------------------------------ */
/*                    version / health helpers                        */
/* ------------------------------------------------------------------ */

func versionJSON() string {
    return fmt.Sprintf(`{"name":%q,"version":%q,"mcp_version":"1.0"}`, appName, appVersion)
}

func healthJSON() string {
    return fmt.Sprintf(`{"status":"healthy","uptime_seconds":%d}`, int(time.Since(startTime).Seconds()))
}

// runHealthCheck performs an HTTP health check against a running server instance.
// Used as a Docker HEALTHCHECK via: /slow-time-server -health [-port=8081]
func runHealthCheck(addr string) int {
    // Prefer localhost over 0.0.0.0 for the health check client
    host, port, _ := net.SplitHostPort(addr)
    if host == "" || host == "0.0.0.0" {
        host = "127.0.0.1"
    }
    url := fmt.Sprintf("http://%s/health", net.JoinHostPort(host, port))

    client := &http.Client{Timeout: 3 * time.Second}
    resp, err := client.Get(url)
    if err != nil {
        fmt.Fprintf(os.Stderr, "health check failed: %v\n", err)
        return 1
    }
    defer resp.Body.Close()
    if resp.StatusCode == http.StatusOK {
        fmt.Println("healthy")
        return 0
    }
    fmt.Fprintf(os.Stderr, "health check returned %d\n", resp.StatusCode)
    return 1
}

var startTime = time.Now()

/* ------------------------------------------------------------------ */
/*                         timezone cache                             */
/* ------------------------------------------------------------------ */

var tzCache sync.Map

func loadLocation(name string) (*time.Location, error) {
    if loc, ok := tzCache.Load(name); ok {
        return loc.(*time.Location), nil
    }
    loc, err := time.LoadLocation(name)
    if err != nil {
        return nil, fmt.Errorf("invalid timezone %q: %w", name, err)
    }
    tzCache.Store(name, loc)
    return loc, nil
}

/* ------------------------------------------------------------------ */
/*                      latency configuration                        */
/* ------------------------------------------------------------------ */

// latencyConfig holds all latency-related settings. Fields accessed
// concurrently use atomic or are protected by a mutex.
type latencyConfig struct {
    mu sync.RWMutex

    // Default latency applied to tools that respect it
    defaultLatency time.Duration

    // Distribution settings
    distribution string // fixed, uniform, normal, exponential
    minLatency   time.Duration
    maxLatency   time.Duration
    meanLatency  time.Duration
    stddevDelay  time.Duration

    // Failure simulation
    failureRate float64
    failureMode string // timeout, error, panic
    rng         *rand.Rand
}

func (lc *latencyConfig) computeDelay() time.Duration {
    lc.mu.RLock()
    defer lc.mu.RUnlock()

    switch lc.distribution {
    case "uniform":
        minNs := float64(lc.minLatency.Nanoseconds())
        maxNs := float64(lc.maxLatency.Nanoseconds())
        ns := lc.rng.Float64()*(maxNs-minNs) + minNs
        return time.Duration(ns)
    case "normal":
        meanNs := float64(lc.meanLatency.Nanoseconds())
        stdNs := float64(lc.stddevDelay.Nanoseconds())
        ns := lc.rng.NormFloat64()*stdNs + meanNs
        if ns < 0 {
            ns = 0
        }
        return time.Duration(ns)
    case "exponential":
        meanNs := float64(lc.meanLatency.Nanoseconds())
        if meanNs <= 0 {
            meanNs = float64(lc.defaultLatency.Nanoseconds())
        }
        ns := lc.rng.ExpFloat64() * meanNs
        return time.Duration(ns)
    default: // "fixed"
        return lc.defaultLatency
    }
}

func (lc *latencyConfig) shouldFail() bool {
    lc.mu.RLock()
    defer lc.mu.RUnlock()
    if lc.failureRate <= 0 {
        return false
    }
    return lc.rng.Float64() < lc.failureRate
}

func (lc *latencyConfig) getFailureMode() string {
    lc.mu.RLock()
    defer lc.mu.RUnlock()
    return lc.failureMode
}

func (lc *latencyConfig) snapshot() map[string]interface{} {
    lc.mu.RLock()
    defer lc.mu.RUnlock()
    return lc.snapshotLocked()
}

// snapshotLocked returns the config map. Caller must hold at least a read lock.
func (lc *latencyConfig) snapshotLocked() map[string]interface{} {
    cfg := map[string]interface{}{
        "default_latency": lc.defaultLatency.String(),
        "distribution":    lc.distribution,
        "failure_rate":    lc.failureRate,
        "failure_mode":    lc.failureMode,
    }
    switch lc.distribution {
    case "uniform":
        cfg["min_latency"] = lc.minLatency.String()
        cfg["max_latency"] = lc.maxLatency.String()
    case "normal":
        cfg["mean_latency"] = lc.meanLatency.String()
        cfg["stddev_latency"] = lc.stddevDelay.String()
    case "exponential":
        cfg["mean_latency"] = lc.meanLatency.String()
    }
    return cfg
}

var lcfg *latencyConfig

/* ------------------------------------------------------------------ */
/*                       invocation statistics                       */
/* ------------------------------------------------------------------ */

type invocationStats struct {
    mu          sync.Mutex
    totalCalls  int64
    totalErrors int64
    latencies   []float64 // seconds
}

var stats = &invocationStats{}

func (s *invocationStats) record(dur time.Duration, isError bool) {
    s.mu.Lock()
    defer s.mu.Unlock()
    atomic.AddInt64(&s.totalCalls, 1)
    if isError {
        atomic.AddInt64(&s.totalErrors, 1)
    }
    s.latencies = append(s.latencies, dur.Seconds())
    // Keep only last 10000 entries
    if len(s.latencies) > 10000 {
        s.latencies = s.latencies[len(s.latencies)-10000:]
    }
}

func (s *invocationStats) snapshot() map[string]interface{} {
    s.mu.Lock()
    defer s.mu.Unlock()

    result := map[string]interface{}{
        "total_calls":  s.totalCalls,
        "total_errors": s.totalErrors,
        "sample_count": len(s.latencies),
    }
    if len(s.latencies) == 0 {
        return result
    }

    // Compute stats from sorted copy
    sorted := make([]float64, len(s.latencies))
    copy(sorted, s.latencies)
    sortFloat64s(sorted)

    var sum float64
    for _, v := range sorted {
        sum += v
    }
    result["avg_latency_seconds"] = math.Round(sum/float64(len(sorted))*1000) / 1000
    result["p50_latency_seconds"] = math.Round(percentile(sorted, 0.50)*1000) / 1000
    result["p95_latency_seconds"] = math.Round(percentile(sorted, 0.95)*1000) / 1000
    result["p99_latency_seconds"] = math.Round(percentile(sorted, 0.99)*1000) / 1000
    return result
}

func percentile(sorted []float64, p float64) float64 {
    if len(sorted) == 0 {
        return 0
    }
    idx := p * float64(len(sorted)-1)
    lower := int(math.Floor(idx))
    upper := int(math.Ceil(idx))
    if lower == upper || upper >= len(sorted) {
        return sorted[lower]
    }
    frac := idx - float64(lower)
    return sorted[lower]*(1-frac) + sorted[upper]*frac
}

// sortFloat64s sorts a slice of float64s (insertion sort is fine for our small slices)
func sortFloat64s(a []float64) {
    for i := 1; i < len(a); i++ {
        key := a[i]
        j := i - 1
        for j >= 0 && a[j] > key {
            a[j+1] = a[j]
            j--
        }
        a[j+1] = key
    }
}

/* ------------------------------------------------------------------ */
/*                    context-aware sleep                             */
/* ------------------------------------------------------------------ */

// contextSleep sleeps for the given duration, returning early if ctx is cancelled.
func contextSleep(ctx context.Context, d time.Duration) error {
    if d <= 0 {
        return nil
    }
    select {
    case <-ctx.Done():
        return ctx.Err()
    case <-time.After(d):
        return nil
    }
}

/* ------------------------------------------------------------------ */
/*                       resource handlers                            */
/* ------------------------------------------------------------------ */

func handleLatencyConfig(_ context.Context, _ mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
    data := lcfg.snapshot()
    jsonData, err := json.Marshal(data)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal latency config: %w", err)
    }
    logAt(logInfo, "resource: latency config requested")
    return []mcp.ResourceContents{
        mcp.TextResourceContents{
            URI:      "latency://config",
            MIMEType: "application/json",
            Text:     string(jsonData),
        },
    }, nil
}

func handleLatencyStats(_ context.Context, _ mcp.ReadResourceRequest) ([]mcp.ResourceContents, error) {
    data := stats.snapshot()
    jsonData, err := json.Marshal(data)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal latency stats: %w", err)
    }
    logAt(logInfo, "resource: latency stats requested")
    return []mcp.ResourceContents{
        mcp.TextResourceContents{
            URI:      "latency://stats",
            MIMEType: "application/json",
            Text:     string(jsonData),
        },
    }, nil
}

/* ------------------------------------------------------------------ */
/*                        prompt handlers                             */
/* ------------------------------------------------------------------ */

func handleTestTimeoutPrompt(_ context.Context, req mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
    delayStr := req.Params.Arguments["delay_seconds"]
    if delayStr == "" {
        delayStr = "30"
    }
    timeoutStr := req.Params.Arguments["timeout_seconds"]
    if timeoutStr == "" {
        timeoutStr = "10"
    }

    var promptText strings.Builder
    promptText.WriteString("Test timeout behaviour by invoking the slow-time-server tools:\n\n")
    promptText.WriteString(fmt.Sprintf("1. Call get_slow_time with delay_seconds=%s to simulate a slow tool\n", delayStr))
    promptText.WriteString(fmt.Sprintf("2. The gateway timeout should be configured to %s seconds\n", timeoutStr))
    promptText.WriteString("3. Observe whether the gateway returns a ToolTimeoutError\n")
    promptText.WriteString("4. Check the error message includes the timeout value\n\n")
    promptText.WriteString("Additional test scenarios:\n")
    promptText.WriteString("- Call get_instant_time as a control (should always succeed)\n")
    promptText.WriteString("- Call get_timeout_time to guarantee a timeout (10-minute delay)\n")
    promptText.WriteString("- Call get_flaky_time multiple times to test circuit breaker behaviour\n")

    logAt(logInfo, "prompt: test_timeout delay=%s timeout=%s", delayStr, timeoutStr)
    return &mcp.GetPromptResult{
        Description: "Timeout and resilience testing prompt",
        Messages: []mcp.PromptMessage{
            {
                Role:    mcp.RoleUser,
                Content: mcp.TextContent{Type: "text", Text: promptText.String()},
            },
        },
    }, nil
}

/* ------------------------------------------------------------------ */
/*                         tool handlers                              */
/* ------------------------------------------------------------------ */

func handleGetSlowTime(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    tz := req.GetString("timezone", "UTC")
    loc, err := loadLocation(tz)
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }

    // Determine delay: per-call override or server default
    delay := lcfg.computeDelay()
    if dsf := req.GetFloat("delay_seconds", -1); dsf >= 0 {
        delay = time.Duration(dsf * float64(time.Second))
    }

    start := time.Now()
    if err := contextSleep(ctx, delay); err != nil {
        stats.record(time.Since(start), true)
        return mcp.NewToolResultError(fmt.Sprintf("cancelled after %s: %v", time.Since(start).Round(time.Millisecond), err)), nil
    }
    elapsed := time.Since(start)
    stats.record(elapsed, false)

    now := time.Now().In(loc).Format(time.RFC3339)
    result := map[string]interface{}{
        "time":                   now,
        "timezone":               tz,
        "delayed_by":             delay.String(),
        "actual_delay":           elapsed.Round(time.Millisecond).String(),
        "server_default_latency": lcfg.defaultLatency.String(),
        "distribution":           lcfg.distribution,
    }
    b, _ := json.Marshal(result)

    logAt(logInfo, "get_slow_time: tz=%s delay=%s actual=%s", tz, delay, elapsed.Round(time.Millisecond))
    return mcp.NewToolResultText(string(b)), nil
}

func handleConvertSlowTime(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
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

    sourceLoc, err := loadLocation(sourceTimezone)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("invalid source timezone: %v", err)), nil
    }
    targetLoc, err := loadLocation(targetTimezone)
    if err != nil {
        return mcp.NewToolResultError(fmt.Sprintf("invalid target timezone: %v", err)), nil
    }

    parsedTime, err := time.ParseInLocation(time.RFC3339, timeStr, sourceLoc)
    if err != nil {
        for _, format := range []string{"2006-01-02 15:04:05", "2006-01-02T15:04:05", "2006-01-02"} {
            if parsedTime, err = time.ParseInLocation(format, timeStr, sourceLoc); err == nil {
                break
            }
        }
        if err != nil {
            return mcp.NewToolResultError(fmt.Sprintf("invalid time format: %v", err)), nil
        }
    }

    // Apply delay
    delay := lcfg.computeDelay()
    if dsf := req.GetFloat("delay_seconds", -1); dsf >= 0 {
        delay = time.Duration(dsf * float64(time.Second))
    }

    start := time.Now()
    if err := contextSleep(ctx, delay); err != nil {
        stats.record(time.Since(start), true)
        return mcp.NewToolResultError(fmt.Sprintf("cancelled after %s: %v", time.Since(start).Round(time.Millisecond), err)), nil
    }
    elapsed := time.Since(start)
    stats.record(elapsed, false)

    convertedTime := parsedTime.In(targetLoc).Format(time.RFC3339)
    result := map[string]interface{}{
        "original_time":  timeStr,
        "from_timezone":  sourceTimezone,
        "converted_time": convertedTime,
        "to_timezone":    targetTimezone,
        "delayed_by":     delay.String(),
        "actual_delay":   elapsed.Round(time.Millisecond).String(),
    }
    b, _ := json.Marshal(result)

    logAt(logInfo, "convert_slow_time: %s from %s to %s delay=%s", timeStr, sourceTimezone, targetTimezone, delay)
    return mcp.NewToolResultText(string(b)), nil
}

func handleGetInstantTime(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    tz := req.GetString("timezone", "UTC")
    loc, err := loadLocation(tz)
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }

    now := time.Now().In(loc).Format(time.RFC3339)
    stats.record(0, false)

    logAt(logInfo, "get_instant_time: tz=%s result=%s", tz, now)
    return mcp.NewToolResultText(now), nil
}

func handleGetTimeoutTime(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    tz := req.GetString("timezone", "UTC")
    loc, err := loadLocation(tz)
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }

    delay := 10 * time.Minute
    start := time.Now()
    if err := contextSleep(ctx, delay); err != nil {
        stats.record(time.Since(start), true)
        return mcp.NewToolResultError(fmt.Sprintf("cancelled after %s: %v", time.Since(start).Round(time.Millisecond), err)), nil
    }
    elapsed := time.Since(start)
    stats.record(elapsed, false)

    now := time.Now().In(loc).Format(time.RFC3339)
    result := map[string]interface{}{
        "time":         now,
        "timezone":     tz,
        "delayed_by":   delay.String(),
        "actual_delay": elapsed.Round(time.Millisecond).String(),
    }
    b, _ := json.Marshal(result)

    logAt(logInfo, "get_timeout_time: tz=%s delay=%s", tz, delay)
    return mcp.NewToolResultText(string(b)), nil
}

func handleGetFlakyTime(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    tz := req.GetString("timezone", "UTC")
    loc, err := loadLocation(tz)
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }

    // Check if this call should fail
    if lcfg.shouldFail() {
        mode := lcfg.getFailureMode()
        start := time.Now()

        switch mode {
        case "timeout":
            // Sleep for 10x the configured latency to exceed any reasonable timeout
            delay := lcfg.defaultLatency * 10
            if delay < 5*time.Minute {
                delay = 5 * time.Minute
            }
            if err := contextSleep(ctx, delay); err != nil {
                stats.record(time.Since(start), true)
                return mcp.NewToolResultError(fmt.Sprintf("simulated timeout (cancelled after %s): %v",
                    time.Since(start).Round(time.Millisecond), err)), nil
            }
            stats.record(time.Since(start), true)
            result := map[string]interface{}{
                "failure_simulated": true,
                "failure_mode":      mode,
                "delayed_by":        delay.String(),
            }
            b, _ := json.Marshal(result)
            return mcp.NewToolResultText(string(b)), nil

        case "panic":
            stats.record(time.Since(start), true)
            panic("simulated crash from get_flaky_time")

        default: // "error"
            stats.record(time.Since(start), true)
            return mcp.NewToolResultError("simulated failure from get_flaky_time (failure_mode=error)"), nil
        }
    }

    // Normal path: apply configured delay
    delay := lcfg.computeDelay()
    start := time.Now()
    if err := contextSleep(ctx, delay); err != nil {
        stats.record(time.Since(start), true)
        return mcp.NewToolResultError(fmt.Sprintf("cancelled after %s: %v", time.Since(start).Round(time.Millisecond), err)), nil
    }
    elapsed := time.Since(start)
    stats.record(elapsed, false)

    now := time.Now().In(loc).Format(time.RFC3339)
    result := map[string]interface{}{
        "time":              now,
        "timezone":          tz,
        "delayed_by":        delay.String(),
        "actual_delay":      elapsed.Round(time.Millisecond).String(),
        "failure_simulated": false,
        "failure_rate":      lcfg.failureRate,
    }
    b, _ := json.Marshal(result)

    logAt(logInfo, "get_flaky_time: tz=%s delay=%s failure_simulated=false", tz, delay)
    return mcp.NewToolResultText(string(b)), nil
}

/* ------------------------------------------------------------------ */
/*                       authentication middleware                    */
/* ------------------------------------------------------------------ */

func authMiddleware(token string, next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.URL.Path == "/health" || r.URL.Path == "/version" {
            next.ServeHTTP(w, r)
            return
        }

        authHeader := r.Header.Get("Authorization")
        if authHeader == "" {
            logAt(logWarn, "missing authorization header from %s for %s", r.RemoteAddr, r.URL.Path)
            w.Header().Set("WWW-Authenticate", `Bearer realm="MCP Server"`)
            http.Error(w, "Authorization required", http.StatusUnauthorized)
            return
        }

        const bearerPrefix = "Bearer "
        if !strings.HasPrefix(authHeader, bearerPrefix) {
            logAt(logWarn, "invalid authorization format from %s", r.RemoteAddr)
            http.Error(w, "Invalid authorization format", http.StatusUnauthorized)
            return
        }

        providedToken := strings.TrimPrefix(authHeader, bearerPrefix)
        if providedToken != token {
            logAt(logWarn, "invalid token from %s", r.RemoteAddr)
            http.Error(w, "Invalid token", http.StatusUnauthorized)
            return
        }

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
        showHelp      = flag.Bool("help", false, "Show help message")
        healthCheck   = flag.Bool("health", false, "Run health check against running server and exit")

        // Latency configuration
        latency      = flag.Duration("latency", 5*time.Second, "Default tool latency")
        latencyDist  = flag.String("latency-distribution", "fixed", "Distribution: fixed, uniform, normal, exponential")
        latencyMin   = flag.Duration("latency-min", 1*time.Second, "Min latency for uniform distribution")
        latencyMax   = flag.Duration("latency-max", 10*time.Second, "Max latency for uniform distribution")
        latencyMean  = flag.Duration("latency-mean", 5*time.Second, "Mean for normal/exponential distribution")
        latencyStd   = flag.Duration("latency-stddev", 2*time.Second, "Stddev for normal distribution")
        failureRate  = flag.Float64("failure-rate", 0.0, "Probability of failure for flaky tool (0.0-1.0)")
        failureMode  = flag.String("failure-mode", "timeout", "Failure type: timeout, error, panic")
        seed         = flag.Int64("seed", 0, "Random seed for reproducibility (default: time-based)")
    )

    flag.Usage = func() {
        const ind = "  "
        fmt.Fprintf(flag.CommandLine.Output(),
            "%s %s - configurable-latency MCP server for timeout and resilience testing\n\n",
            appName, appVersion)
        fmt.Fprintln(flag.CommandLine.Output(), "Options:")
        flag.VisitAll(func(fl *flag.Flag) {
            fmt.Fprintf(flag.CommandLine.Output(), ind+"-%s\n", fl.Name)
            fmt.Fprintf(flag.CommandLine.Output(), ind+ind+"%s (default %q)\n\n",
                fl.Usage, fl.DefValue)
        })
        fmt.Fprintf(flag.CommandLine.Output(),
            "Examples:\n"+
                ind+"%s -transport=dual -port=8081 -latency=5s\n"+
                ind+"%s -transport=dual -port=8081 -latency=2s -failure-rate=0.3 -failure-mode=error -seed=42\n"+
                ind+"%s -transport=dual -port=8081 -latency-distribution=normal -latency-mean=5s -latency-stddev=3s\n\n"+
                "Environment Variables:\n"+
                ind+"DEFAULT_LATENCY  - Override -latency (e.g., \"5s\", \"30s\", \"2m\")\n"+
                ind+"FAILURE_RATE     - Override -failure-rate\n"+
                ind+"AUTH_TOKEN       - Bearer token for authentication (overrides -auth-token flag)\n",
            os.Args[0], os.Args[0], os.Args[0])
    }

    flag.Parse()
    if *showHelp {
        flag.Usage()
        os.Exit(0)
    }
    if *healthCheck {
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        os.Exit(runHealthCheck(addr))
    }

    /* ----------------------- env overrides ----------------------- */
    if envToken := os.Getenv(envAuthToken); envToken != "" {
        *authToken = envToken
    }
    if envLat := os.Getenv(envDefaultLatency); envLat != "" {
        if d, err := time.ParseDuration(envLat); err == nil {
            *latency = d
        }
    }
    if envFR := os.Getenv(envFailureRate); envFR != "" {
        if _, err := fmt.Sscanf(envFR, "%f", failureRate); err != nil {
            logAt(logWarn, "invalid FAILURE_RATE env var: %s", envFR)
        }
    }

    /* ----------------------- logging setup ----------------------- */
    curLvl = parseLvl(*logLevel)
    if curLvl == logNone {
        logger.SetOutput(io.Discard)
    }

    /* ----------------------- latency config ---------------------- */
    rngSeed := *seed
    if rngSeed == 0 {
        rngSeed = time.Now().UnixNano()
    }
    lcfg = &latencyConfig{
        defaultLatency: *latency,
        distribution:   *latencyDist,
        minLatency:     *latencyMin,
        maxLatency:     *latencyMax,
        meanLatency:    *latencyMean,
        stddevDelay:    *latencyStd,
        failureRate:    *failureRate,
        failureMode:    *failureMode,
        rng:            rand.New(rand.NewSource(rngSeed)),
    }

    logAt(logDebug, "starting %s %s", appName, appVersion)
    logAt(logInfo, "latency config: default=%s distribution=%s failure_rate=%.2f failure_mode=%s seed=%d",
        lcfg.defaultLatency, lcfg.distribution, lcfg.failureRate, lcfg.failureMode, rngSeed)

    if *authToken != "" && *transport != "stdio" {
        logAt(logInfo, "authentication enabled with Bearer token")
    }

    /* ----------------------- build MCP server --------------------- */
    s := server.NewMCPServer(
        appName,
        appVersion,
        server.WithToolCapabilities(false),
        server.WithResourceCapabilities(false, true),
        server.WithPromptCapabilities(true),
        server.WithLogging(),
        server.WithRecovery(),
    )

    /* ----------------------- register tools ----------------------- */
    getSlowTimeTool := mcp.NewTool("get_slow_time",
        mcp.WithDescription("Get current system time with configurable artificial delay. Use delay_seconds to control response latency for timeout testing."),
        mcp.WithTitleAnnotation("Get Slow Time"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("timezone",
            mcp.Description("IANA timezone name (default: UTC)"),
        ),
        mcp.WithNumber("delay_seconds",
            mcp.Description("Override delay in seconds. If omitted, uses server default latency."),
        ),
    )
    s.AddTool(getSlowTimeTool, handleGetSlowTime)

    convertSlowTimeTool := mcp.NewTool("convert_slow_time",
        mcp.WithDescription("Convert time between different timezones with configurable artificial delay."),
        mcp.WithTitleAnnotation("Convert Slow Time"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithIdempotentHintAnnotation(true),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("time",
            mcp.Required(),
            mcp.Description("Time to convert in RFC3339 format or common formats"),
        ),
        mcp.WithString("source_timezone",
            mcp.Required(),
            mcp.Description("Source IANA timezone name"),
        ),
        mcp.WithString("target_timezone",
            mcp.Required(),
            mcp.Description("Target IANA timezone name"),
        ),
        mcp.WithNumber("delay_seconds",
            mcp.Description("Override delay in seconds. If omitted, uses server default latency."),
        ),
    )
    s.AddTool(convertSlowTimeTool, handleConvertSlowTime)

    getInstantTimeTool := mcp.NewTool("get_instant_time",
        mcp.WithDescription("Get current system time with zero delay. Control/baseline tool for comparison."),
        mcp.WithTitleAnnotation("Get Instant Time"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("timezone",
            mcp.Description("IANA timezone name (default: UTC)"),
        ),
    )
    s.AddTool(getInstantTimeTool, handleGetInstantTime)

    getTimeoutTimeTool := mcp.NewTool("get_timeout_time",
        mcp.WithDescription("Get current system time with extreme 10-minute delay. Guaranteed to exceed any reasonable gateway timeout."),
        mcp.WithTitleAnnotation("Get Timeout Time"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("timezone",
            mcp.Description("IANA timezone name (default: UTC)"),
        ),
    )
    s.AddTool(getTimeoutTimeTool, handleGetTimeoutTime)

    getFlakyTimeTool := mcp.NewTool("get_flaky_time",
        mcp.WithDescription("Get current system time with random failures based on configured failure_rate. Use for circuit breaker testing."),
        mcp.WithTitleAnnotation("Get Flaky Time"),
        mcp.WithReadOnlyHintAnnotation(true),
        mcp.WithDestructiveHintAnnotation(false),
        mcp.WithOpenWorldHintAnnotation(false),
        mcp.WithString("timezone",
            mcp.Description("IANA timezone name (default: UTC)"),
        ),
    )
    s.AddTool(getFlakyTimeTool, handleGetFlakyTime)

    /* ----------------------- register resources ---------------------- */
    s.AddResource(mcp.NewResource("latency://config", "Latency Configuration",
        mcp.WithResourceDescription("Current server latency configuration (default latency, distribution, failure rate)"),
        mcp.WithMIMEType("application/json"),
    ), handleLatencyConfig)

    s.AddResource(mcp.NewResource("latency://stats", "Invocation Statistics",
        mcp.WithResourceDescription("Tool invocation statistics: count, avg/p50/p95/p99 latency, failure count"),
        mcp.WithMIMEType("application/json"),
    ), handleLatencyStats)

    /* ----------------------- register prompts ----------------------- */
    s.AddPrompt(mcp.NewPrompt("test_timeout",
        mcp.WithPromptDescription("Generate a prompt for testing timeout behaviour with slow tools"),
        mcp.WithArgument("delay_seconds",
            mcp.ArgumentDescription("Delay in seconds for the slow tool (default: 30)"),
        ),
        mcp.WithArgument("timeout_seconds",
            mcp.ArgumentDescription("Expected gateway timeout in seconds (default: 10)"),
        ),
    ), handleTestTimeoutPrompt)

    /* -------------------- choose transport & serve ---------------- */
    switch strings.ToLower(*transport) {

    case "stdio":
        if *authToken != "" {
            logAt(logWarn, "auth-token is ignored for stdio transport")
        }
        logAt(logInfo, "serving via stdio transport")
        if err := server.ServeStdio(s); err != nil {
            logger.Fatalf("stdio server error: %v", err)
        }

    case "sse":
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        mux := http.NewServeMux()

        opts := []server.SSEOption{}
        if *publicURL != "" {
            opts = append(opts, server.WithBaseURL(strings.TrimRight(*publicURL, "/")))
        }

        sseHandler := server.NewSSEServer(s, opts...)
        mux.Handle("/", sseHandler)
        registerHealthAndVersion(mux)

        logAt(logInfo, "SSE server ready on http://%s", addr)
        logAt(logInfo, "  MCP SSE events:   /sse")
        logAt(logInfo, "  MCP SSE messages: /messages")
        logAt(logInfo, "  Health check:     /health")
        logAt(logInfo, "  Version info:     /version")

        var handler http.Handler = mux
        handler = loggingHTTPMiddleware(handler)
        if *authToken != "" {
            handler = authMiddleware(*authToken, handler)
        }

        if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
            logger.Fatalf("SSE server error: %v", err)
        }

    case "http":
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        mux := http.NewServeMux()

        httpHandler := server.NewStreamableHTTPServer(s)
        mux.Handle("/", httpHandler)
        registerHealthAndVersion(mux)

        mux.HandleFunc("/info", func(w http.ResponseWriter, _ *http.Request) {
            w.Header().Set("Content-Type", "application/json")
            fmt.Fprintf(w, `{"message":"MCP HTTP server ready (slow-time-server)","instructions":"Use POST requests with JSON-RPC 2.0 payloads"}`)
        })

        logAt(logInfo, "HTTP server ready on http://%s", addr)
        logAt(logInfo, "  MCP endpoint:     / (POST with JSON-RPC)")
        logAt(logInfo, "  Health check:     /health")
        logAt(logInfo, "  Version info:     /version")

        var handler http.Handler = mux
        handler = loggingHTTPMiddleware(handler)
        if *authToken != "" {
            handler = authMiddleware(*authToken, handler)
        }

        if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
            logger.Fatalf("HTTP server error: %v", err)
        }

    case "dual":
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        mux := http.NewServeMux()

        sseOpts := []server.SSEOption{}
        if *publicURL != "" {
            sseOpts = append(sseOpts, server.WithBaseURL(strings.TrimRight(*publicURL, "/")))
        }
        sseHandler := server.NewSSEServer(s, sseOpts...)

        httpHandler := server.NewStreamableHTTPServer(s, server.WithEndpointPath("/http"))

        mux.Handle("/sse", sseHandler)
        mux.Handle("/messages", sseHandler)
        mux.Handle("/message", sseHandler)
        mux.Handle("/http", httpHandler)

        registerRESTHandlers(mux)
        registerHealthAndVersion(mux)

        logAt(logInfo, "DUAL server ready on http://%s", addr)
        logAt(logInfo, "  SSE events:       /sse")
        logAt(logInfo, "  SSE messages:     /messages (plural) and /message (singular)")
        logAt(logInfo, "  HTTP endpoint:    /http")
        logAt(logInfo, "  REST API:         /api/v1/*")
        logAt(logInfo, "  API Docs:         /api/v1/docs")
        logAt(logInfo, "  Health check:     /health")
        logAt(logInfo, "  Version info:     /version")

        var handler http.Handler = mux
        handler = corsMiddleware(handler)
        handler = loggingHTTPMiddleware(handler)
        if *authToken != "" {
            handler = authMiddleware(*authToken, handler)
        }

        if err := http.ListenAndServe(addr, handler); err != nil && err != http.ErrServerClosed {
            logger.Fatalf("DUAL server error: %v", err)
        }

    case "rest":
        addr := effectiveAddr(*addrFlag, *listenHost, *port)
        mux := http.NewServeMux()

        registerRESTHandlers(mux)
        registerHealthAndVersion(mux)

        logAt(logInfo, "REST API server ready on http://%s", addr)
        logAt(logInfo, "  API Base:         /api/v1")
        logAt(logInfo, "  API Docs:         /api/v1/docs")
        logAt(logInfo, "  OpenAPI Spec:     /api/v1/openapi.json")
        logAt(logInfo, "  Health check:     /health")
        logAt(logInfo, "  Version info:     /version")

        var handler http.Handler = mux
        handler = corsMiddleware(handler)
        handler = loggingHTTPMiddleware(handler)
        if *authToken != "" {
            handler = authMiddleware(*authToken, handler)
        }

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

func effectiveAddr(addrFlag, listen string, port int) string {
    if addrFlag != "" {
        return addrFlag
    }
    return fmt.Sprintf("%s:%d", listen, port)
}

func registerHealthAndVersion(mux *http.ServeMux) {
    mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte(healthJSON()))
    })
    mux.HandleFunc("/version", func(w http.ResponseWriter, _ *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte(versionJSON()))
    })
}

/* -------------------- HTTP middleware ----------------------------- */

func loggingHTTPMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if curLvl < logInfo {
            next.ServeHTTP(w, r)
            return
        }

        start := time.Now()
        rw := &statusWriter{ResponseWriter: w, status: http.StatusOK, written: false}
        next.ServeHTTP(rw, r)

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

func (sw *statusWriter) Flush() {
    if f, ok := sw.ResponseWriter.(http.Flusher); ok {
        if !sw.written {
            sw.WriteHeader(http.StatusOK)
        }
        f.Flush()
    }
}

func (sw *statusWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
    if h, ok := sw.ResponseWriter.(http.Hijacker); ok {
        return h.Hijack()
    }
    return nil, nil, fmt.Errorf("hijacking not supported")
}

// CloseNotify keeps SSE clients informed if the peer goes away.
// Deprecated: Use Request.Context() instead. Kept for compatibility.
func (sw *statusWriter) CloseNotify() <-chan bool {
    // nolint:staticcheck // SA1019: http.CloseNotifier is deprecated but required for SSE compatibility
    if cn, ok := sw.ResponseWriter.(http.CloseNotifier); ok {
        return cn.CloseNotify()
    }
    done := make(chan bool, 1)
    return done
}
