// -*- coding: utf-8 -*-
// rest_handlers.go - REST API handlers for slow-time-server
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// This file implements REST API endpoints that complement the MCP protocol,
// providing direct HTTP access to time operations with configurable latency.

package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"time"
)

// SlowTimeResponse represents the response for slow time operations.
type SlowTimeResponse struct {
	Time        string `json:"time"`
	Timezone    string `json:"timezone"`
	Unix        int64  `json:"unix"`
	UTC         string `json:"utc"`
	DelayedBy   string `json:"delayed_by"`
	ActualDelay string `json:"actual_delay"`
}

// ErrorResponse represents an API error response.
type ErrorResponse struct {
	Error   string `json:"error"`
	Message string `json:"message"`
	Code    int    `json:"code"`
}

func writeJSONError(w http.ResponseWriter, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(ErrorResponse{
		Error:   http.StatusText(code),
		Message: message,
		Code:    code,
	})
}

func writeJSON(w http.ResponseWriter, code int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	if err := json.NewEncoder(w).Encode(data); err != nil {
		logAt(logError, "Failed to encode JSON response: %v", err)
	}
}

// handleRESTGetTime handles GET /api/v1/time?timezone=X&delay=Y
func handleRESTGetTime(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	timezone := r.URL.Query().Get("timezone")
	if timezone == "" {
		timezone = "UTC"
	}

	loc, err := time.LoadLocation(timezone)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, fmt.Sprintf("Invalid timezone: %s", timezone))
		return
	}

	// Parse delay from query or use server default
	delay := lcfg.computeDelay()
	if delayStr := r.URL.Query().Get("delay"); delayStr != "" {
		if d, err := strconv.ParseFloat(delayStr, 64); err == nil {
			delay = time.Duration(d * float64(time.Second))
		}
	}

	start := time.Now()
	if err := contextSleep(r.Context(), delay); err != nil {
		stats.record(time.Since(start), true)
		writeJSONError(w, http.StatusGatewayTimeout, fmt.Sprintf("Request cancelled after %s", time.Since(start).Round(time.Millisecond)))
		return
	}
	elapsed := time.Since(start)
	stats.record(elapsed, false)

	now := time.Now().In(loc)
	response := SlowTimeResponse{
		Time:        now.Format(time.RFC3339),
		Timezone:    timezone,
		Unix:        now.Unix(),
		UTC:         now.UTC().Format(time.RFC3339),
		DelayedBy:   delay.String(),
		ActualDelay: elapsed.Round(time.Millisecond).String(),
	}
	writeJSON(w, http.StatusOK, response)
}

// handleRESTGetConfig handles GET /api/v1/config
func handleRESTGetConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}
	writeJSON(w, http.StatusOK, lcfg.snapshot())
}

// handleRESTUpdateConfig handles POST /api/v1/config for runtime reconfiguration.
func handleRESTUpdateConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	var body struct {
		DefaultLatency string  `json:"default_latency"`
		Distribution   string  `json:"distribution"`
		FailureRate    float64 `json:"failure_rate"`
		FailureMode    string  `json:"failure_mode"`
		MinLatency     string  `json:"min_latency"`
		MaxLatency     string  `json:"max_latency"`
		MeanLatency    string  `json:"mean_latency"`
		StddevLatency  string  `json:"stddev_latency"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSONError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	lcfg.mu.Lock()
	defer lcfg.mu.Unlock()

	if body.DefaultLatency != "" {
		if d, err := time.ParseDuration(body.DefaultLatency); err == nil {
			lcfg.defaultLatency = d
		}
	}
	if body.Distribution != "" {
		lcfg.distribution = body.Distribution
	}
	if body.FailureRate >= 0 && body.FailureRate <= 1 {
		lcfg.failureRate = body.FailureRate
	}
	if body.FailureMode != "" {
		lcfg.failureMode = body.FailureMode
	}
	if body.MinLatency != "" {
		if d, err := time.ParseDuration(body.MinLatency); err == nil {
			lcfg.minLatency = d
		}
	}
	if body.MaxLatency != "" {
		if d, err := time.ParseDuration(body.MaxLatency); err == nil {
			lcfg.maxLatency = d
		}
	}
	if body.MeanLatency != "" {
		if d, err := time.ParseDuration(body.MeanLatency); err == nil {
			lcfg.meanLatency = d
		}
	}
	if body.StddevLatency != "" {
		if d, err := time.ParseDuration(body.StddevLatency); err == nil {
			lcfg.stddevDelay = d
		}
	}

	logAt(logInfo, "config updated: default_latency=%s distribution=%s failure_rate=%.2f failure_mode=%s",
		lcfg.defaultLatency, lcfg.distribution, lcfg.failureRate, lcfg.failureMode)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"status":  "updated",
		"config":  lcfg.snapshotLocked(),
	})
}

// handleRESTGetStats handles GET /api/v1/stats
func handleRESTGetStats(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}
	writeJSON(w, http.StatusOK, stats.snapshot())
}

// handleRESTTestEcho handles GET /api/v1/test/echo
func handleRESTTestEcho(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	message := r.URL.Query().Get("message")
	if message == "" {
		message = "Hello from slow-time-server!"
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"echo":      message,
		"timestamp": time.Now().Format(time.RFC3339),
		"server":    appName,
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

	html := `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Slow Time Server API Documentation</title>
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

// handleRESTConfigRoute dispatches GET/POST to the correct handler.
func handleRESTConfigRoute(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		handleRESTGetConfig(w, r)
	case http.MethodPost:
		handleRESTUpdateConfig(w, r)
	default:
		writeJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
	}
}

// registerRESTHandlers registers all REST API handlers.
func registerRESTHandlers(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/time", handleRESTGetTime)
	mux.HandleFunc("/api/v1/config", handleRESTConfigRoute)
	mux.HandleFunc("/api/v1/stats", handleRESTGetStats)
	mux.HandleFunc("/api/v1/test/echo", handleRESTTestEcho)
	mux.HandleFunc("/api/v1/openapi.json", handleOpenAPISpec)
	mux.HandleFunc("/api/v1/docs", handleAPIDocs)
}

// corsMiddleware adds CORS headers to responses.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		w.Header().Set("Access-Control-Max-Age", "3600")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

