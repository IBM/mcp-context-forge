// main_test.go
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti
package main

import (
	"context"
	"encoding/json"
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

// testRequest creates a minimal CallToolRequest with the supplied
// arguments. Only the Arguments map is required by the handler code.
func testRequest(tool string, args map[string]any) mcp.CallToolRequest {
	return mcp.CallToolRequest{
		Params: mcp.CallToolParams{
			Name:      tool,
			Arguments: args,
		},
	}
}

// extractText is a tiny helper that pulls the first text content out
// of a CallToolResult and returns it as a string.
func extractText(t *testing.T, res *mcp.CallToolResult) string {
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
		"bogus": logInfo, // default path
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
	got = effectiveAddr("", "0.0.0.0", 8080)
	if got != "0.0.0.0:8080" {
		t.Errorf("constructed addr wrong: got %q", got)
	}
}

/* ------------------------------------------------------------------
   version / health helpers
------------------------------------------------------------------ */

func TestVersionAndHealthJSON(t *testing.T) {
	// version
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

	// health - only check stable fields
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
   tool handler: get_system_time
------------------------------------------------------------------ */

func TestHandleGetSystemTime(t *testing.T) {
	ctx := context.Background()

	// default (UTC)
	req := testRequest("get_system_time", nil)
	res, err := handleGetSystemTime(ctx, req)
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	txt := extractText(t, res)
	tm, err := time.Parse(time.RFC3339, txt)
	if err != nil {
		t.Fatalf("result not RFC3339: %v", err)
	}
	if _, off := tm.Zone(); off != 0 {
		t.Errorf("expected UTC (offset 0), got %q", txt)
	}

	// custom tz
	req = testRequest("get_system_time", map[string]any{"timezone": "America/New_York"})
	res, err = handleGetSystemTime(ctx, req)
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	txt = extractText(t, res)
	tm, err = time.Parse(time.RFC3339, txt)
	if err != nil {
		t.Fatalf("result not RFC3339: %v", err)
	}
	locNY, _ := loadLocation("America/New_York") // let the TZ DB decide
	_, wantOff := tm.In(locNY).Zone()            // offset valid for that date
	_, gotOff := tm.Zone()
	if wantOff != gotOff {
		t.Errorf("offset mismatch: want %d got %d", wantOff, gotOff)
	}
}

/* ------------------------------------------------------------------
   tool handler: convert_time
------------------------------------------------------------------ */

func TestHandleConvertTime(t *testing.T) {
	ctx := context.Background()

	// 16:00 UTC -> 12:00 America/New_York (EDT offset -4h on June 21)
	src := "2025-06-21T16:00:00Z"
	args := map[string]any{
		"time":            src,
		"source_timezone": "UTC",
		"target_timezone": "America/New_York",
	}
	req := testRequest("convert_time", args)
	res, err := handleConvertTime(ctx, req)
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	txt := extractText(t, res)
	want := "2025-06-21T12:00:00-04:00"
	if txt != want {
		t.Errorf("convert_time wrong: got %q want %q", txt, want)
	}

	// missing arg -> error
	req = testRequest("convert_time", map[string]any{})
	res, err = handleConvertTime(ctx, req)
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	if !res.IsError {
		t.Fatalf("expected error result")
	}
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
}

/* ------------------------------------------------------------------
   loggingHTTPMiddleware - smoke test (no assertions on log output)
------------------------------------------------------------------ */

func TestLoggingHTTPMiddleware(t *testing.T) {
	curLvl = logDebug // ensure middleware logs
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
