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

// handleRESTListResources handles GET /api/v1/resources
func handleRESTListResources(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    resources := []map[string]string{
        {
            "uri":         "timezone://info",
            "name":        "Timezone Information",
            "description": "Comprehensive timezone information including offsets, DST, and major cities",
            "mime_type":   "application/json",
        },
        {
            "uri":         "time://current/world",
            "name":        "Current World Times",
            "description": "Current time in major cities around the world",
            "mime_type":   "application/json",
        },
        {
            "uri":         "time://formats",
            "name":        "Time Formats",
            "description": "Examples of supported time formats for parsing and display",
            "mime_type":   "application/json",
        },
        {
            "uri":         "time://business-hours",
            "name":        "Business Hours",
            "description": "Standard business hours across different regions",
            "mime_type":   "application/json",
        },
    }

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "resources": resources,
        "count":     len(resources),
    })
}

// handleRESTGetResource handles GET /api/v1/resources/{uri}
func handleRESTGetResource(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    // Extract resource URI from path
    path := strings.TrimPrefix(r.URL.Path, "/api/v1/resources/")
    resourceURI := path

    if resourceURI == "" {
        handleRESTListResources(w, r)
        return
    }

    // Handle different resources based on URI
    switch resourceURI {
    case "timezone-info":
        // Return timezone information
        data := getTimezoneInfoData()
        writeJSON(w, http.StatusOK, data)

    case "current-world":
        // Return current world times
        data := getCurrentWorldTimesData()
        writeJSON(w, http.StatusOK, data)

    case "time-formats":
        // Return time format examples
        data := getTimeFormatsData()
        writeJSON(w, http.StatusOK, data)

    case "business-hours":
        // Return business hours
        data := getBusinessHoursData()
        writeJSON(w, http.StatusOK, data)

    default:
        writeJSONError(w, http.StatusNotFound, fmt.Sprintf("Resource not found: %s", resourceURI))
    }
}

// handleRESTListPrompts handles GET /api/v1/prompts
func handleRESTListPrompts(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    prompts := []map[string]interface{}{
        {
            "name":        "compare_timezones",
            "description": "Compare current times across multiple time zones",
            "arguments": []map[string]interface{}{
                {
                    "name":        "timezones",
                    "description": "Comma-separated list of timezone IDs to compare",
                    "required":    true,
                },
                {
                    "name":        "reference_time",
                    "description": "Optional reference time (defaults to now)",
                    "required":    false,
                },
            },
        },
        {
            "name":        "schedule_meeting",
            "description": "Find optimal meeting time across multiple time zones",
            "arguments": []map[string]interface{}{
                {
                    "name":        "participants",
                    "description": "Comma-separated list of participant locations/timezones",
                    "required":    true,
                },
                {
                    "name":        "duration",
                    "description": "Meeting duration in minutes",
                    "required":    true,
                },
                {
                    "name":        "preferred_hours",
                    "description": "Preferred time range (e.g., '9 AM - 5 PM')",
                    "required":    false,
                },
                {
                    "name":        "date_range",
                    "description": "Date range to consider (e.g., 'next 7 days')",
                    "required":    false,
                },
            },
        },
        {
            "name":        "convert_time_detailed",
            "description": "Convert time with detailed context",
            "arguments": []map[string]interface{}{
                {
                    "name":        "time",
                    "description": "Time to convert",
                    "required":    true,
                },
                {
                    "name":        "from_timezone",
                    "description": "Source timezone",
                    "required":    true,
                },
                {
                    "name":        "to_timezones",
                    "description": "Comma-separated list of target timezones",
                    "required":    true,
                },
                {
                    "name":        "include_context",
                    "description": "Whether to include contextual information (true/false)",
                    "required":    false,
                },
            },
        },
    }

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "prompts": prompts,
        "count":   len(prompts),
    })
}

// handleRESTExecutePrompt handles POST /api/v1/prompts/{name}/execute
func handleRESTExecutePrompt(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
        return
    }

    // Extract prompt name from path
    path := strings.TrimPrefix(r.URL.Path, "/api/v1/prompts/")
    path = strings.TrimSuffix(path, "/execute")
    promptName := path

    if promptName == "" {
        writeJSONError(w, http.StatusBadRequest, "Prompt name not specified")
        return
    }

    // Parse request body for arguments
    var args map[string]string
    if err := json.NewDecoder(r.Body).Decode(&args); err != nil {
        writeJSONError(w, http.StatusBadRequest, "Invalid request body")
        return
    }

    // Generate prompt text based on the prompt name
    var promptText string
    switch promptName {
    case "compare_timezones":
        promptText = generateCompareTimezonesPrompt(args)
    case "schedule_meeting":
        promptText = generateScheduleMeetingPrompt(args)
    case "convert_time_detailed":
        promptText = generateConvertTimeDetailedPrompt(args)
    default:
        writeJSONError(w, http.StatusNotFound, fmt.Sprintf("Unknown prompt: %s", promptName))
        return
    }

    writeJSON(w, http.StatusOK, map[string]interface{}{
        "prompt":    promptName,
        "arguments": args,
        "text":      promptText,
    })
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

    // Resource operations
    mux.HandleFunc("/api/v1/resources", handleRESTListResources)
    mux.HandleFunc("/api/v1/resources/", handleRESTGetResource) // With resource URI in path

    // Prompt operations
    mux.HandleFunc("/api/v1/prompts", handleRESTListPrompts)
    mux.HandleFunc("/api/v1/prompts/", handleRESTExecutePrompt) // With prompt name in path

    // Test endpoints
    mux.HandleFunc("/api/v1/test/echo", handleRESTTestEcho)
    mux.HandleFunc("/api/v1/test/validate", handleRESTTestValidate)
    mux.HandleFunc("/api/v1/test/performance", handleRESTTestPerformance)

    // Documentation
    mux.HandleFunc("/api/v1/openapi.json", handleOpenAPISpec)
    mux.HandleFunc("/api/v1/docs", handleAPIDocs)
}

// Helper functions for resource data
func getTimezoneInfoData() map[string]interface{} {
    return map[string]interface{}{
        "timezones": []map[string]interface{}{
            {
                "id":           "America/New_York",
                "name":         "Eastern Time",
                "offset":       "-05:00",
                "dst":          true,
                "abbreviation": "EST/EDT",
                "major_cities": []string{"New York", "Toronto", "Montreal"},
                "population":   141000000,
            },
            {
                "id":           "Europe/London",
                "name":         "Greenwich Mean Time",
                "offset":       "+00:00",
                "dst":          true,
                "abbreviation": "GMT/BST",
                "major_cities": []string{"London", "Dublin", "Lisbon"},
                "population":   67000000,
            },
            {
                "id":           "Asia/Tokyo",
                "name":         "Japan Standard Time",
                "offset":       "+09:00",
                "dst":          false,
                "abbreviation": "JST",
                "major_cities": []string{"Tokyo", "Osaka", "Yokohama"},
                "population":   127000000,
            },
        },
        "timezone_groups": map[string][]string{
            "us_timezones":     []string{"America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"},
            "europe_timezones": []string{"Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow"},
            "asia_timezones":   []string{"Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai"},
        },
    }
}

func getCurrentWorldTimesData() map[string]interface{} {
    cities := map[string]string{
        "New York":    "America/New_York",
        "Los Angeles": "America/Los_Angeles",
        "London":      "Europe/London",
        "Paris":       "Europe/Paris",
        "Tokyo":       "Asia/Tokyo",
        "Sydney":      "Australia/Sydney",
        "Dubai":       "Asia/Dubai",
    }

    times := make(map[string]string)
    now := time.Now()

    for city, tz := range cities {
        if loc, err := time.LoadLocation(tz); err == nil {
            localTime := now.In(loc)
            times[city] = localTime.Format("2006-01-02 15:04:05 MST")
        }
    }

    return map[string]interface{}{
        "last_updated": now.UTC().Format(time.RFC3339),
        "times":        times,
    }
}

func getTimeFormatsData() map[string]interface{} {
    return map[string]interface{}{
        "input_formats": []string{
            "2006-01-02 15:04:05",
            "2006-01-02T15:04:05Z",
            "2006-01-02T15:04:05-07:00",
            "Jan 2, 2006 3:04 PM",
        },
        "output_formats": map[string]string{
            "iso8601": "2006-01-02T15:04:05Z07:00",
            "rfc3339": "2006-01-02T15:04:05Z",
            "rfc822":  "Mon, 02 Jan 2006 15:04:05 MST",
        },
    }
}

func getBusinessHoursData() map[string]interface{} {
    return map[string]interface{}{
        "regions": map[string]interface{}{
            "north_america": map[string]interface{}{
                "standard_hours": "9:00 AM - 5:00 PM",
                "lunch_break":    "12:00 PM - 1:00 PM",
                "working_days":   []string{"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"},
            },
            "europe": map[string]interface{}{
                "standard_hours": "9:00 AM - 6:00 PM",
                "lunch_break":    "1:00 PM - 2:00 PM",
                "working_days":   []string{"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"},
            },
        },
    }
}

// Helper functions for generating prompts
func generateCompareTimezonesPrompt(args map[string]string) string {
    timezones := args["timezones"]
    referenceTime := args["reference_time"]

    prompt := fmt.Sprintf("Compare the current time across these time zones: %s\n", timezones)
    if referenceTime != "" {
        prompt += fmt.Sprintf("Reference time: %s\n", referenceTime)
    }
    prompt += "\nShow:\n"
    prompt += "1. The current time in each timezone\n"
    prompt += "2. The time difference from the first timezone\n"
    prompt += "3. Whether it's business hours (9 AM - 5 PM)\n"
    prompt += "4. The day of the week\n"

    return prompt
}

func generateScheduleMeetingPrompt(args map[string]string) string {
    participants := args["participants"]
    duration := args["duration"]
    preferredHours := args["preferred_hours"]
    if preferredHours == "" {
        preferredHours = "9 AM - 5 PM"
    }
    dateRange := args["date_range"]
    if dateRange == "" {
        dateRange = "next 7 days"
    }

    prompt := fmt.Sprintf("Find the best meeting time for participants in: %s\n", participants)
    prompt += fmt.Sprintf("\nMeeting details:\n")
    prompt += fmt.Sprintf("- Duration: %s minutes\n", duration)
    prompt += fmt.Sprintf("- Preferred hours: %s local time\n", preferredHours)
    prompt += fmt.Sprintf("- Date range: %s\n", dateRange)

    return prompt
}

func generateConvertTimeDetailedPrompt(args map[string]string) string {
    timeStr := args["time"]
    fromTz := args["from_timezone"]
    toTzs := args["to_timezones"]
    includeContext := args["include_context"]

    prompt := fmt.Sprintf("Convert %s from %s to: %s\n", timeStr, fromTz, toTzs)

    if includeContext == "true" {
        prompt += "\nAlso provide:\n"
        prompt += "1. Day of week in each timezone\n"
        prompt += "2. Whether it's a business day\n"
        prompt += "3. Time until/since this moment\n"
    }

    return prompt
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
