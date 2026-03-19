// main_test.go
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
package main

import (
    "context"
    "encoding/json"
    "math"
    "math/rand"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
)

/* ------------------------------------------------------------------
   helper utilities for the tests
------------------------------------------------------------------ */

func testRequest(tool string, args map[string]any) mcp.CallToolRequest {
    return mcp.CallToolRequest{
        Params: mcp.CallToolParams{
            Name:      tool,
            Arguments: args,
        },
    }
}

func extractText(t *testing.T, res *mcp.CallToolResult) string {
    t.Helper()
    if res == nil {
        t.Fatalf("nil result")
    }
    if res.IsError {
        t.Fatalf("expected success result, got error: %+v", res)
    }
    if len(res.Content) == 0 {
        t.Fatalf("no content in result")
    }
    tc, ok := mcp.AsTextContent(res.Content[0])
    if !ok {
        t.Fatalf("content is not text: %+v", res.Content[0])
    }
    return tc.Text
}

func extractErrorText(t *testing.T, res *mcp.CallToolResult) string {
    t.Helper()
    if res == nil {
        t.Fatalf("nil result")
    }
    if !res.IsError {
        t.Fatalf("expected error result, got success")
    }
    if len(res.Content) == 0 {
        t.Fatalf("no content in error result")
    }
    tc, ok := mcp.AsTextContent(res.Content[0])
    if !ok {
        t.Fatalf("content is not text: %+v", res.Content[0])
    }
    return tc.Text
}

// setupTestConfig initializes lcfg for tests.
func setupTestConfig() {
    lcfg = &latencyConfig{
        defaultLatency: 100 * time.Millisecond,
        distribution:   "fixed",
        minLatency:     50 * time.Millisecond,
        maxLatency:     200 * time.Millisecond,
        meanLatency:    100 * time.Millisecond,
        stddevDelay:    50 * time.Millisecond,
        failureRate:    0.0,
        failureMode:    "error",
        rng:            rand.New(rand.NewSource(42)),
    }
}

/* ------------------------------------------------------------------
   parseLvl & effectiveAddr
------------------------------------------------------------------ */

func TestParseLvl(t *testing.T) {
    cases := map[string]logLvl{
        "debug": logDebug,
        "info":  logInfo,
        "warn":  logWarn,
        "error": logError,
        "none":  logNone,
        "bogus": logInfo,
    }
    for in, want := range cases {
        if got := parseLvl(in); got != want {
            t.Errorf("parseLvl(%q) = %v, want %v", in, got, want)
        }
    }
}

func TestEffectiveAddr(t *testing.T) {
    got := effectiveAddr("1.2.3.4:9999", "ignored", 1234)
    if got != "1.2.3.4:9999" {
        t.Errorf("addr flag should win: got %q", got)
    }
    got = effectiveAddr("", "0.0.0.0", 8081)
    if got != "0.0.0.0:8081" {
        t.Errorf("constructed addr wrong: got %q", got)
    }
}

/* ------------------------------------------------------------------
   version / health helpers
------------------------------------------------------------------ */

func TestVersionAndHealthJSON(t *testing.T) {
    var v struct {
        Name       string `json:"name"`
        Version    string `json:"version"`
        MCPVersion string `json:"mcp_version"`
    }
    if err := json.Unmarshal([]byte(versionJSON()), &v); err != nil {
        t.Fatalf("version JSON malformed: %v", err)
    }
    if v.Name != appName || v.Version != appVersion || v.MCPVersion == "" {
        t.Errorf("version JSON unexpected: %+v", v)
    }

    var h struct {
        Status string `json:"status"`
    }
    if err := json.Unmarshal([]byte(healthJSON()), &h); err != nil {
        t.Fatalf("health JSON malformed: %v", err)
    }
    if h.Status != "healthy" {
        t.Errorf("health status wrong: %+v", h)
    }
}

/* ------------------------------------------------------------------
   loadLocation cache
------------------------------------------------------------------ */

func TestLoadLocationCaching(t *testing.T) {
    loc1, err := loadLocation("Europe/London")
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    loc2, err := loadLocation("Europe/London")
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if loc1 != loc2 {
        t.Errorf("locations not cached: %p vs %p", loc1, loc2)
    }
    if _, err := loadLocation("Not/AZone"); err == nil {
        t.Errorf("expected error for invalid zone")
    }
}

/* ------------------------------------------------------------------
   context-aware sleep
------------------------------------------------------------------ */

func TestContextSleep(t *testing.T) {
    // Normal sleep
    start := time.Now()
    err := contextSleep(context.Background(), 50*time.Millisecond)
    elapsed := time.Since(start)
    if err != nil {
        t.Errorf("unexpected error: %v", err)
    }
    if elapsed < 40*time.Millisecond {
        t.Errorf("sleep too short: %v", elapsed)
    }

    // Zero duration
    err = contextSleep(context.Background(), 0)
    if err != nil {
        t.Errorf("zero duration should not error: %v", err)
    }

    // Cancelled context
    ctx, cancel := context.WithCancel(context.Background())
    cancel()
    err = contextSleep(ctx, 10*time.Second)
    if err == nil {
        t.Errorf("expected error from cancelled context")
    }
}

func TestContextSleepCancellation(t *testing.T) {
    ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
    defer cancel()

    start := time.Now()
    err := contextSleep(ctx, 10*time.Second)
    elapsed := time.Since(start)

    if err == nil {
        t.Error("expected context cancellation error")
    }
    if elapsed > 200*time.Millisecond {
        t.Errorf("cancellation took too long: %v", elapsed)
    }
}

/* ------------------------------------------------------------------
   latency distributions
------------------------------------------------------------------ */

func TestLatencyFixedDistribution(t *testing.T) {
    cfg := &latencyConfig{
        defaultLatency: 500 * time.Millisecond,
        distribution:   "fixed",
        rng:            rand.New(rand.NewSource(42)),
    }
    for i := 0; i < 10; i++ {
        d := cfg.computeDelay()
        if d != 500*time.Millisecond {
            t.Errorf("fixed distribution should return exact duration, got %v", d)
        }
    }
}

func TestLatencyUniformDistribution(t *testing.T) {
    cfg := &latencyConfig{
        distribution: "uniform",
        minLatency:   100 * time.Millisecond,
        maxLatency:   200 * time.Millisecond,
        rng:          rand.New(rand.NewSource(42)),
    }

    for i := 0; i < 100; i++ {
        d := cfg.computeDelay()
        if d < 100*time.Millisecond || d > 200*time.Millisecond {
            t.Errorf("uniform distribution out of range: %v", d)
        }
    }
}

func TestLatencyNormalDistribution(t *testing.T) {
    cfg := &latencyConfig{
        distribution: "normal",
        meanLatency:  500 * time.Millisecond,
        stddevDelay:  100 * time.Millisecond,
        rng:          rand.New(rand.NewSource(42)),
    }

    var sum float64
    n := 1000
    for i := 0; i < n; i++ {
        d := cfg.computeDelay()
        if d < 0 {
            t.Errorf("normal distribution should not go negative, got %v", d)
        }
        sum += d.Seconds()
    }
    avg := sum / float64(n)
    // Mean should be approximately 0.5s (+/- 0.05s with 1000 samples)
    if math.Abs(avg-0.5) > 0.05 {
        t.Errorf("normal distribution mean too far from expected: got %.3f, want ~0.500", avg)
    }
}

func TestLatencyExponentialDistribution(t *testing.T) {
    cfg := &latencyConfig{
        distribution: "exponential",
        meanLatency:  500 * time.Millisecond,
        rng:          rand.New(rand.NewSource(42)),
    }

    var sum float64
    n := 1000
    for i := 0; i < n; i++ {
        d := cfg.computeDelay()
        if d < 0 {
            t.Errorf("exponential distribution should not go negative, got %v", d)
        }
        sum += d.Seconds()
    }
    avg := sum / float64(n)
    // Exponential mean should be approximately 0.5s
    if math.Abs(avg-0.5) > 0.1 {
        t.Errorf("exponential distribution mean too far: got %.3f, want ~0.500", avg)
    }
}

/* ------------------------------------------------------------------
   failure simulation
------------------------------------------------------------------ */

func TestShouldFail(t *testing.T) {
    cfg := &latencyConfig{
        failureRate: 0.0,
        rng:         rand.New(rand.NewSource(42)),
    }
    for i := 0; i < 100; i++ {
        if cfg.shouldFail() {
            t.Error("failure_rate=0 should never fail")
        }
    }

    cfg.failureRate = 1.0
    for i := 0; i < 100; i++ {
        if !cfg.shouldFail() {
            t.Error("failure_rate=1 should always fail")
        }
    }
}

func TestShouldFailDeterministic(t *testing.T) {
    makeConfig := func() *latencyConfig {
        return &latencyConfig{
            failureRate: 0.5,
            rng:         rand.New(rand.NewSource(42)),
        }
    }

    cfg1 := makeConfig()
    cfg2 := makeConfig()

    for i := 0; i < 100; i++ {
        r1 := cfg1.shouldFail()
        r2 := cfg2.shouldFail()
        if r1 != r2 {
            t.Errorf("deterministic seed should produce same results at iteration %d: %v != %v", i, r1, r2)
        }
    }
}

/* ------------------------------------------------------------------
   invocation statistics
------------------------------------------------------------------ */

func TestInvocationStats(t *testing.T) {
    s := &invocationStats{}
    s.record(100*time.Millisecond, false)
    s.record(200*time.Millisecond, false)
    s.record(300*time.Millisecond, true)

    snap := s.snapshot()
    if snap["total_calls"].(int64) != 3 {
        t.Errorf("total_calls: got %v, want 3", snap["total_calls"])
    }
    if snap["total_errors"].(int64) != 1 {
        t.Errorf("total_errors: got %v, want 1", snap["total_errors"])
    }
    if snap["sample_count"].(int) != 3 {
        t.Errorf("sample_count: got %v, want 3", snap["sample_count"])
    }
}

func TestInvocationStatsPercentiles(t *testing.T) {
    s := &invocationStats{}
    // Record 100 latencies from 10ms to 1000ms
    for i := 1; i <= 100; i++ {
        s.record(time.Duration(i*10)*time.Millisecond, false)
    }

    snap := s.snapshot()
    p50 := snap["p50_latency_seconds"].(float64)
    p95 := snap["p95_latency_seconds"].(float64)
    p99 := snap["p99_latency_seconds"].(float64)

    // p50 should be around 0.5s
    if p50 < 0.4 || p50 > 0.6 {
        t.Errorf("p50 out of expected range: %v", p50)
    }
    // p95 should be around 0.95s
    if p95 < 0.85 || p95 > 1.05 {
        t.Errorf("p95 out of expected range: %v", p95)
    }
    // p99 should be around 0.99s
    if p99 < 0.90 || p99 > 1.05 {
        t.Errorf("p99 out of expected range: %v", p99)
    }
}

/* ------------------------------------------------------------------
   sortFloat64s
------------------------------------------------------------------ */

func TestSortFloat64s(t *testing.T) {
    a := []float64{5, 3, 1, 4, 2}
    sortFloat64s(a)
    for i := 0; i < len(a)-1; i++ {
        if a[i] > a[i+1] {
            t.Errorf("not sorted at index %d: %v", i, a)
        }
    }
}

/* ------------------------------------------------------------------
   tool handler: get_slow_time
------------------------------------------------------------------ */

func TestHandleGetSlowTime(t *testing.T) {
    setupTestConfig()
    lcfg.defaultLatency = 50 * time.Millisecond // Short delay for tests
    ctx := context.Background()

    req := testRequest("get_slow_time", map[string]any{"timezone": "UTC", "delay_seconds": 0.05})
    start := time.Now()
    res, err := handleGetSlowTime(ctx, req)
    elapsed := time.Since(start)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }

    txt := extractText(t, res)
    var result map[string]interface{}
    if err := json.Unmarshal([]byte(txt), &result); err != nil {
        t.Fatalf("result not valid JSON: %v", err)
    }

    if _, ok := result["time"]; !ok {
        t.Error("missing 'time' field in result")
    }
    if _, ok := result["delayed_by"]; !ok {
        t.Error("missing 'delayed_by' field in result")
    }
    if elapsed < 40*time.Millisecond {
        t.Errorf("delay too short: %v", elapsed)
    }
}

func TestHandleGetSlowTimeDefaultTimezone(t *testing.T) {
    setupTestConfig()
    lcfg.defaultLatency = 10 * time.Millisecond
    ctx := context.Background()

    req := testRequest("get_slow_time", nil)
    res, err := handleGetSlowTime(ctx, req)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }

    txt := extractText(t, res)
    var result map[string]interface{}
    if err := json.Unmarshal([]byte(txt), &result); err != nil {
        t.Fatalf("result not valid JSON: %v", err)
    }
    if result["timezone"] != "UTC" {
        t.Errorf("expected UTC default timezone, got %v", result["timezone"])
    }
}

/* ------------------------------------------------------------------
   tool handler: convert_slow_time
------------------------------------------------------------------ */

func TestHandleConvertSlowTime(t *testing.T) {
    setupTestConfig()
    lcfg.defaultLatency = 10 * time.Millisecond
    ctx := context.Background()

    args := map[string]any{
        "time":            "2025-06-21T16:00:00Z",
        "source_timezone": "UTC",
        "target_timezone": "America/New_York",
        "delay_seconds":   0.01,
    }
    req := testRequest("convert_slow_time", args)
    res, err := handleConvertSlowTime(ctx, req)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }

    txt := extractText(t, res)
    var result map[string]interface{}
    if err := json.Unmarshal([]byte(txt), &result); err != nil {
        t.Fatalf("result not valid JSON: %v", err)
    }

    if result["converted_time"] != "2025-06-21T12:00:00-04:00" {
        t.Errorf("conversion wrong: got %q", result["converted_time"])
    }
}

func TestHandleConvertSlowTimeMissingArgs(t *testing.T) {
    setupTestConfig()
    ctx := context.Background()

    req := testRequest("convert_slow_time", map[string]any{})
    res, err := handleConvertSlowTime(ctx, req)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }
    if !res.IsError {
        t.Error("expected error result for missing args")
    }
}

/* ------------------------------------------------------------------
   tool handler: get_instant_time
------------------------------------------------------------------ */

func TestHandleGetInstantTime(t *testing.T) {
    setupTestConfig()
    ctx := context.Background()

    start := time.Now()
    req := testRequest("get_instant_time", map[string]any{"timezone": "America/New_York"})
    res, err := handleGetInstantTime(ctx, req)
    elapsed := time.Since(start)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }

    txt := extractText(t, res)
    if _, err := time.Parse(time.RFC3339, txt); err != nil {
        t.Fatalf("result not RFC3339: %v", err)
    }

    // Should be essentially instant
    if elapsed > 50*time.Millisecond {
        t.Errorf("instant time should be fast, took %v", elapsed)
    }
}

/* ------------------------------------------------------------------
   tool handler: get_timeout_time (with cancellation)
------------------------------------------------------------------ */

func TestHandleGetTimeoutTimeCancellation(t *testing.T) {
    setupTestConfig()

    ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
    defer cancel()

    req := testRequest("get_timeout_time", map[string]any{"timezone": "UTC"})
    start := time.Now()
    res, err := handleGetTimeoutTime(ctx, req)
    elapsed := time.Since(start)

    if err != nil {
        t.Fatalf("handler error: %v", err)
    }
    if !res.IsError {
        t.Error("expected error result from timeout")
    }
    errText := extractErrorText(t, res)
    if !strings.Contains(errText, "cancelled") {
        t.Errorf("error should mention cancellation: %s", errText)
    }
    if elapsed > 200*time.Millisecond {
        t.Errorf("cancellation took too long: %v", elapsed)
    }
}

/* ------------------------------------------------------------------
   tool handler: get_flaky_time
------------------------------------------------------------------ */

func TestHandleGetFlakyTimeNoFailure(t *testing.T) {
    setupTestConfig()
    lcfg.failureRate = 0.0
    lcfg.defaultLatency = 10 * time.Millisecond
    ctx := context.Background()

    req := testRequest("get_flaky_time", map[string]any{"timezone": "UTC"})
    res, err := handleGetFlakyTime(ctx, req)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }

    txt := extractText(t, res)
    var result map[string]interface{}
    if err := json.Unmarshal([]byte(txt), &result); err != nil {
        t.Fatalf("result not valid JSON: %v", err)
    }
    if result["failure_simulated"] != false {
        t.Error("expected no failure simulation")
    }
}

func TestHandleGetFlakyTimeWithErrorFailure(t *testing.T) {
    setupTestConfig()
    lcfg.failureRate = 1.0
    lcfg.failureMode = "error"
    lcfg.defaultLatency = 10 * time.Millisecond
    ctx := context.Background()

    req := testRequest("get_flaky_time", map[string]any{"timezone": "UTC"})
    res, err := handleGetFlakyTime(ctx, req)
    if err != nil {
        t.Fatalf("handler error: %v", err)
    }
    if !res.IsError {
        t.Error("expected error result from flaky tool with failure_rate=1.0")
    }
}

func TestHandleGetFlakyTimeWithPanicFailure(t *testing.T) {
    setupTestConfig()
    lcfg.failureRate = 1.0
    lcfg.failureMode = "panic"
    lcfg.defaultLatency = 10 * time.Millisecond
    ctx := context.Background()

    req := testRequest("get_flaky_time", map[string]any{"timezone": "UTC"})

    // Should panic
    defer func() {
        if r := recover(); r == nil {
            t.Error("expected panic from flaky tool with failure_mode=panic")
        }
    }()
    _, _ = handleGetFlakyTime(ctx, req)
}

/* ------------------------------------------------------------------
   auth middleware
------------------------------------------------------------------ */

func TestAuthMiddleware(t *testing.T) {
    const token = "secret123"
    okHandler := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
        w.WriteHeader(http.StatusOK)
    })
    mw := authMiddleware(token, okHandler)

    // no header
    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodGet, "/other", nil)
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusUnauthorized {
        t.Errorf("want 401, got %d", rec.Code)
    }

    // wrong bearer
    rec = httptest.NewRecorder()
    req = httptest.NewRequest(http.MethodGet, "/other", nil)
    req.Header.Set("Authorization", "Bearer nope")
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusUnauthorized {
        t.Errorf("want 401, got %d", rec.Code)
    }

    // correct bearer
    rec = httptest.NewRecorder()
    req = httptest.NewRequest(http.MethodGet, "/other", nil)
    req.Header.Set("Authorization", "Bearer "+token)
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusOK {
        t.Errorf("expected success, got %d", rec.Code)
    }

    // health endpoint bypasses auth
    rec = httptest.NewRecorder()
    req = httptest.NewRequest(http.MethodGet, "/health", nil)
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusOK {
        t.Errorf("/health should bypass auth; got %d", rec.Code)
    }

    // version endpoint bypasses auth
    rec = httptest.NewRecorder()
    req = httptest.NewRequest(http.MethodGet, "/version", nil)
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusOK {
        t.Errorf("/version should bypass auth; got %d", rec.Code)
    }
}

/* ------------------------------------------------------------------
   loggingHTTPMiddleware
------------------------------------------------------------------ */

func TestLoggingHTTPMiddleware(t *testing.T) {
    curLvl = logDebug
    inner := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
        w.WriteHeader(http.StatusTeapot)
    })
    mw := loggingHTTPMiddleware(inner)

    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodPost, "/foo", strings.NewReader(`{}`))
    mw.ServeHTTP(rec, req)
    if rec.Code != http.StatusTeapot {
        t.Errorf("unexpected status %d", rec.Code)
    }
}

/* ------------------------------------------------------------------
   REST handler: GET /api/v1/config
------------------------------------------------------------------ */

func TestRESTGetConfig(t *testing.T) {
    setupTestConfig()

    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodGet, "/api/v1/config", nil)
    handleRESTGetConfig(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("expected 200, got %d", rec.Code)
    }

    var result map[string]interface{}
    if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
        t.Fatalf("response not valid JSON: %v", err)
    }
    if result["distribution"] != "fixed" {
        t.Errorf("expected fixed distribution, got %v", result["distribution"])
    }
}

/* ------------------------------------------------------------------
   REST handler: POST /api/v1/config
------------------------------------------------------------------ */

func TestRESTUpdateConfig(t *testing.T) {
    setupTestConfig()

    body := `{"default_latency":"10s","distribution":"normal","failure_rate":0.5}`
    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodPost, "/api/v1/config", strings.NewReader(body))
    handleRESTUpdateConfig(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("expected 200, got %d", rec.Code)
    }

    if lcfg.defaultLatency != 10*time.Second {
        t.Errorf("latency not updated: %v", lcfg.defaultLatency)
    }
    if lcfg.distribution != "normal" {
        t.Errorf("distribution not updated: %s", lcfg.distribution)
    }
    if lcfg.failureRate != 0.5 {
        t.Errorf("failure rate not updated: %f", lcfg.failureRate)
    }
}

/* ------------------------------------------------------------------
   REST handler: GET /api/v1/stats
------------------------------------------------------------------ */

func TestRESTGetStats(t *testing.T) {
    setupTestConfig()
    // Reset stats
    stats = &invocationStats{}
    stats.record(100*time.Millisecond, false)
    stats.record(200*time.Millisecond, true)

    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodGet, "/api/v1/stats", nil)
    handleRESTGetStats(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("expected 200, got %d", rec.Code)
    }

    var result map[string]interface{}
    if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
        t.Fatalf("response not valid JSON: %v", err)
    }
    if result["total_calls"].(float64) != 2 {
        t.Errorf("expected 2 total calls, got %v", result["total_calls"])
    }
}

/* ------------------------------------------------------------------
   REST handler: GET /api/v1/test/echo
------------------------------------------------------------------ */

func TestRESTTestEcho(t *testing.T) {
    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodGet, "/api/v1/test/echo?message=hello", nil)
    handleRESTTestEcho(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("expected 200, got %d", rec.Code)
    }

    var result map[string]string
    if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
        t.Fatalf("response not valid JSON: %v", err)
    }
    if result["echo"] != "hello" {
        t.Errorf("echo mismatch: %v", result["echo"])
    }
    if result["server"] != appName {
        t.Errorf("server mismatch: %v", result["server"])
    }
}

/* ------------------------------------------------------------------
   latency config snapshot
------------------------------------------------------------------ */

func TestLatencyConfigSnapshot(t *testing.T) {
    cfg := &latencyConfig{
        defaultLatency: 5 * time.Second,
        distribution:   "uniform",
        minLatency:     1 * time.Second,
        maxLatency:     10 * time.Second,
        failureRate:    0.3,
        failureMode:    "error",
        rng:            rand.New(rand.NewSource(42)),
    }

    snap := cfg.snapshot()
    if snap["distribution"] != "uniform" {
        t.Errorf("distribution mismatch: %v", snap["distribution"])
    }
    if snap["min_latency"] != "1s" {
        t.Errorf("min_latency mismatch: %v", snap["min_latency"])
    }
    if snap["max_latency"] != "10s" {
        t.Errorf("max_latency mismatch: %v", snap["max_latency"])
    }
}

/* ------------------------------------------------------------------
   percentile helper
------------------------------------------------------------------ */

func TestPercentile(t *testing.T) {
    // Empty slice
    if p := percentile(nil, 0.5); p != 0 {
        t.Errorf("empty slice should return 0, got %v", p)
    }

    // Single element
    if p := percentile([]float64{42}, 0.5); p != 42 {
        t.Errorf("single element p50 should be 42, got %v", p)
    }

    // Known values
    data := []float64{1, 2, 3, 4, 5}
    p50 := percentile(data, 0.5)
    if p50 != 3 {
        t.Errorf("p50 of [1,2,3,4,5] should be 3, got %v", p50)
    }
}
