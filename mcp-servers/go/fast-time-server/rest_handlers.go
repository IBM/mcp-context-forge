// -*- coding: utf-8 -*-
// rest_handlers.go - REST API handlers for fast-time-server
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// This file implements REST API endpoints that complement the MCP protocol,
// providing direct HTTP access to time-related operations.

package main

import (
    "encoding/json"
    "fmt"
    "net/http"
    "strings"
    "time"
)

// TimeResponse represents the response for time operations
type TimeResponse struct {
    Time     string `json:"time"`
    Timezone string `json:"timezone"`
    Unix     int64  `json:"unix"`
    UTC      string `json:"utc"`
}

// ConvertRequest represents a time conversion request
type ConvertRequest struct {
    Time         string `json:"time"`
    FromTimezone string `json:"from_timezone"`
    ToTimezone   string `json:"to_timezone"`
}

// ConvertResponse represents a time conversion response
type ConvertResponse struct {
    OriginalTime  string `json:"original_time"`
    FromTimezone  string `json:"from_timezone"`
    ConvertedTime string `json:"converted_time"`
    ToTimezone    string `json:"to_timezone"`
    Unix          int64  `json:"unix"`
}

// BatchConvertRequest represents a batch conversion request
type BatchConvertRequest struct {
    Conversions []ConvertRequest `json:"conversions"`
}

// BatchConvertResponse represents a batch conversion response
type BatchConvertResponse struct {
    Results []ConvertResponse `json:"results"`
}

// TimezoneInfo represents timezone information
type TimezoneInfo struct {
    Name         string `json:"name"`
    Offset       string `json:"offset"`
    CurrentTime  string `json:"current_time"`
    IsDST        bool   `json:"is_dst"`
    Abbreviation string `json:"abbreviation"`
}

// ErrorResponse represents an API error response
type ErrorResponse struct {
    Error   string `json:"error"`
    Message string `json:"message"`
    Code    int    `json:"code"`
}

// writeJSONError writes a JSON error response
func writeJSONError(w http.ResponseWriter, code int, message string) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    _ = json.NewEncoder(w).Encode(ErrorResponse{
        Error:   http.StatusText(code),
        Message: message,
        Code:    code,
    })
}

// writeJSON writes a JSON response
func writeJSON(w http.ResponseWriter, code int, data interface{}) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    if err := json.NewEncoder(w).Encode(data); err != nil {
        logAt(logError, "Failed to encode JSON response: %v", err)
    }
}

// handleRESTGetTime handles GET /api/v1/time and /api/v1/time/{timezone}
func handleRESTGetTime(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    // Extract timezone from path or query parameter
    path := strings.TrimPrefix(r.URL.Path, "/api/v1/time")
    path = strings.TrimPrefix(path, "/")

    timezone := path
    if timezone == "" {
        timezone = r.URL.Query().Get("timezone")
    }
    if timezone == "" {
        timezone = "UTC"
    }

    // Load timezone location
    loc, err := time.LoadLocation(timezone)
    if err != nil {
        writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid timezone: %s", timezone))
        return
    }

    // Get current time in the specified timezone
    now := time.Now().In(loc)

    response := TimeResponse{
        Time:     now.Format(time.RFC3339),
        Timezone: timezone,
        Unix:     now.Unix(),
        UTC:      now.UTC().Format(time.RFC3339),
    }

    writeJSON(w, http.StatusOK, response)
}

// handleRESTConvertTime handles POST /api/v1/convert
func handleRESTConvertTime(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    var req ConvertRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        writeJSONError(w, http.StatusBadRequest, "Invalid request body")
        return
    }

    // Parse the input time
    t, err := time.Parse(time.RFC3339, req.Time)
    if err != nil {
        // Try parsing without timezone
        t, err = time.Parse("2006-01-02 15:04:05", req.Time)
        if err != nil {
            writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid time format: %s", req.Time))
            return
        }
    }

    // Load source timezone
    fromLoc, err := time.LoadLocation(req.FromTimezone)
    if err != nil {
        writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid source timezone: %s", req.FromTimezone))
        return
    }

    // Load target timezone
    toLoc, err := time.LoadLocation(req.ToTimezone)
    if err != nil {
        writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid target timezone: %s", req.ToTimezone))
        return
    }

    // Convert time
    sourceTime := t.In(fromLoc)
    convertedTime := sourceTime.In(toLoc)

    response := ConvertResponse{
        OriginalTime:  sourceTime.Format(time.RFC3339),
        FromTimezone:  req.FromTimezone,
        ConvertedTime: convertedTime.Format(time.RFC3339),
        ToTimezone:    req.ToTimezone,
        Unix:          convertedTime.Unix(),
    }

    writeJSON(w, http.StatusOK, response)
}

// handleRESTBatchConvert handles POST /api/v1/convert/batch
func handleRESTBatchConvert(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    var req BatchConvertRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        writeJSONError(w, http.StatusBadRequest, "Invalid request body")
        return
    }

    var results []ConvertResponse
    for _, conv := range req.Conversions {
        // Parse the input time
        t, err := time.Parse(time.RFC3339, conv.Time)
        if err != nil {
            // Try parsing without timezone
            t, err = time.Parse("2006-01-02 15:04:05", conv.Time)
            if err != nil {
                continue // Skip invalid entries
            }
        }

        // Load timezones
        fromLoc, err := time.LoadLocation(conv.FromTimezone)
        if err != nil {
            continue
        }
        toLoc, err := time.LoadLocation(conv.ToTimezone)
        if err != nil {
            continue
        }

        // Convert time
        sourceTime := t.In(fromLoc)
        convertedTime := sourceTime.In(toLoc)

        results = append(results, ConvertResponse{
            OriginalTime:  sourceTime.Format(time.RFC3339),
            FromTimezone:  conv.FromTimezone,
            ConvertedTime: convertedTime.Format(time.RFC3339),
            ToTimezone:    conv.ToTimezone,
            Unix:          convertedTime.Unix(),
        })
    }

    response := BatchConvertResponse{
        Results: results,
    }

    writeJSON(w, http.StatusOK, response)
}

// handleRESTListTimezones handles GET /api/v1/timezones
func handleRESTListTimezones(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    filter := r.URL.Query().Get("filter")

    // Get all known timezones
    var timezones []string
    for _, tz := range []string{
        "UTC", "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "America/Toronto", "America/Vancouver",
        "America/Mexico_City", "America/Sao_Paulo", "America/Buenos_Aires",
        "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Rome",
        "Europe/Madrid", "Europe/Amsterdam", "Europe/Brussels", "Europe/Zurich",
        "Europe/Stockholm", "Europe/Oslo", "Europe/Copenhagen", "Europe/Helsinki",
        "Europe/Moscow", "Europe/Istanbul", "Europe/Athens", "Europe/Warsaw",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore",
        "Asia/Seoul", "Asia/Taipei", "Asia/Bangkok", "Asia/Jakarta",
        "Asia/Kolkata", "Asia/Dubai", "Asia/Tel_Aviv", "Asia/Riyadh",
        "Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane",
        "Australia/Perth", "Pacific/Auckland", "Pacific/Fiji",
        "Africa/Cairo", "Africa/Lagos", "Africa/Johannesburg", "Africa/Nairobi",
    } {
        if filter == "" || strings.Contains(strings.ToLower(tz), strings.ToLower(filter)) {
            timezones = append(timezones, tz)
        }
    }

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "timezones": timezones,
        "count":     len(timezones),
    })
}

// handleRESTTimezoneInfo handles GET /api/v1/timezones/{timezone}/info
func handleRESTTimezoneInfo(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    // Extract timezone from path
    path := strings.TrimPrefix(r.URL.Path, "/api/v1/timezones/")
    path = strings.TrimSuffix(path, "/info")
    timezone := path

    if timezone == "" {
        writeJSONError(w, http.StatusBadRequest, "Timezone not specified")
        return
    }

    // Load timezone location
    loc, err := time.LoadLocation(timezone)
    if err != nil {
        writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid timezone: %s", timezone))
        return
    }

    // Get current time in the timezone
    now := time.Now().In(loc)
    _, offset := now.Zone()

    info := TimezoneInfo{
        Name:         timezone,
        Offset:       fmt.Sprintf("%+d:%02d", offset/3600, (offset%3600)/60),
        CurrentTime:  now.Format(time.RFC3339),
        IsDST:        now.IsDST(),
        Abbreviation: now.Format("MST"),
    }

    writeJSON(w, http.StatusOK, info)
}

// handleRESTTestEcho handles GET /api/v1/test/echo
func handleRESTTestEcho(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    message := r.URL.Query().Get("message")
    if message == "" {
        message = "Hello from fast-time-server!"
    }

    writeJSON(w, http.StatusOK, map[string]string{
        "echo":      message,
        "timestamp": time.Now().Format(time.RFC3339),
        "server":    "fast-time-server",
    })
}

// handleRESTTestValidate handles POST /api/v1/test/validate
func handleRESTTestValidate(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    var body map[string]interface{}
    if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
        writeJSONError(w, http.StatusBadRequest, "Invalid JSON body")
        return
    }

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "valid":     true,
        "received":  body,
        "timestamp": time.Now().Format(time.RFC3339),
    })
}

// handleRESTTestPerformance handles GET /api/v1/test/performance
func handleRESTTestPerformance(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    start := time.Now()

    // Perform some operations to measure
    testOps := 1000
    for i := 0; i < testOps; i++ {
        _ = time.Now().Format(time.RFC3339)
    }

    duration := time.Since(start)

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "operations":     testOps,
        "duration_ms":    duration.Milliseconds(),
        "duration_ns":    duration.Nanoseconds(),
        "ops_per_second": float64(testOps) / duration.Seconds(),
        "server_time":    time.Now().Format(time.RFC3339),
    })
}

// handleOpenAPISpec handles GET /api/v1/openapi.json
func handleOpenAPISpec(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    spec := getOpenAPISpec()
    writeJSON(w, http.StatusOK, spec)
}

// handleAPIDocs handles GET /api/v1/docs
func handleAPIDocs(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    // Serve a simple HTML page with Swagger UI
    html := `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Fast Time Server API Documentation</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {
            SwaggerUIBundle({
                url: "/api/v1/openapi.json",
                dom_id: '#swagger-ui',
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout"
            });
        }
    </script>
</body>
</html>`

    w.Header().Set("Content-Type", "text/html; charset=utf-8")
    w.WriteHeader(http.StatusOK)
    _, _ = w.Write([]byte(html))
}

// registerRESTHandlers registers all REST API handlers
func registerRESTHandlers(mux *http.ServeMux) {
    // Time operations
    mux.HandleFunc("/api/v1/time", handleRESTGetTime)
    mux.HandleFunc("/api/v1/time/", handleRESTGetTime) // With timezone in path
    mux.HandleFunc("/api/v1/convert", handleRESTConvertTime)
    mux.HandleFunc("/api/v1/convert/batch", handleRESTBatchConvert)

    // Timezone operations
    mux.HandleFunc("/api/v1/timezones", handleRESTListTimezones)
    mux.HandleFunc("/api/v1/timezones/", handleRESTTimezoneInfo) // With timezone in path

    // Test endpoints
    mux.HandleFunc("/api/v1/test/echo", handleRESTTestEcho)
    mux.HandleFunc("/api/v1/test/validate", handleRESTTestValidate)
    mux.HandleFunc("/api/v1/test/performance", handleRESTTestPerformance)

    // Documentation
    mux.HandleFunc("/api/v1/openapi.json", handleOpenAPISpec)
    mux.HandleFunc("/api/v1/docs", handleAPIDocs)
}

// corsMiddleware adds CORS headers to responses
func corsMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // Set CORS headers
        w.Header().Set("Access-Control-Allow-Origin", "*")
        w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
        w.Header().Set("Access-Control-Max-Age", "3600")

        // Handle preflight requests
        if r.Method == http.MethodOptions {
            w.WriteHeader(http.StatusNoContent)
            return
        }

        next.ServeHTTP(w, r)
    })
}
