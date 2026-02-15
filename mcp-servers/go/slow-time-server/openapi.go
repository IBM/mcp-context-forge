// -*- coding: utf-8 -*-
// openapi.go - OpenAPI specification for slow-time-server REST API
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package main

func getOpenAPISpec() map[string]interface{} {
	return map[string]interface{}{
		"openapi": "3.0.0",
		"info": map[string]interface{}{
			"title":       "Slow Time Server API",
			"description": "REST API for configurable-latency time operations, designed for timeout, resilience, and load testing",
			"version":     appVersion,
		},
		"servers": []map[string]interface{}{
			{
				"url":         "http://localhost:8081",
				"description": "Local development server",
			},
		},
		"paths": map[string]interface{}{
			"/api/v1/time": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get current time with configurable delay",
					"description": "Returns the current time after an artificial delay. Use the delay parameter to control latency.",
					"parameters": []map[string]interface{}{
						{
							"name":        "timezone",
							"in":          "query",
							"description": "IANA timezone (default: UTC)",
							"required":    false,
							"schema":      map[string]interface{}{"type": "string", "default": "UTC"},
						},
						{
							"name":        "delay",
							"in":          "query",
							"description": "Delay in seconds (overrides server default)",
							"required":    false,
							"schema":      map[string]interface{}{"type": "number", "minimum": 0, "maximum": 600},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Time with latency metadata",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{"$ref": "#/components/schemas/SlowTimeResponse"},
								},
							},
						},
					},
				},
			},
			"/api/v1/config": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get current latency configuration",
					"description": "Returns the current server latency settings",
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Current latency configuration",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{"$ref": "#/components/schemas/LatencyConfig"},
								},
							},
						},
					},
				},
				"post": map[string]interface{}{
					"summary":     "Update latency configuration at runtime",
					"description": "Hot-reload latency parameters without restarting the server",
					"requestBody": map[string]interface{}{
						"required": true,
						"content": map[string]interface{}{
							"application/json": map[string]interface{}{
								"schema": map[string]interface{}{"$ref": "#/components/schemas/LatencyConfigUpdate"},
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Updated configuration",
						},
					},
				},
			},
			"/api/v1/stats": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get invocation statistics",
					"description": "Returns tool invocation count, latency percentiles, and failure count",
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Invocation statistics",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{"$ref": "#/components/schemas/InvocationStats"},
								},
							},
						},
					},
				},
			},
			"/api/v1/test/echo": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Echo test endpoint (no delay)",
					"description": "Simple echo endpoint for connectivity testing",
					"parameters": []map[string]interface{}{
						{
							"name":        "message",
							"in":          "query",
							"description": "Message to echo",
							"required":    false,
							"schema":      map[string]interface{}{"type": "string"},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Echo response",
						},
					},
				},
			},
			"/health": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Health check (always instant)",
					"description": "Returns server health status with no artificial delay",
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Server is healthy",
						},
					},
				},
			},
			"/version": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Version information",
					"description": "Returns server name and version",
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Version info",
						},
					},
				},
			},
		},
		"components": map[string]interface{}{
			"schemas": map[string]interface{}{
				"SlowTimeResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"time":         map[string]interface{}{"type": "string", "description": "Current time in RFC3339 format"},
						"timezone":     map[string]interface{}{"type": "string", "description": "Timezone name"},
						"unix":         map[string]interface{}{"type": "integer", "description": "Unix timestamp"},
						"utc":          map[string]interface{}{"type": "string", "description": "Time in UTC"},
						"delayed_by":   map[string]interface{}{"type": "string", "description": "Configured delay duration"},
						"actual_delay": map[string]interface{}{"type": "string", "description": "Actual observed delay"},
					},
				},
				"LatencyConfig": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"default_latency": map[string]interface{}{"type": "string", "description": "Default tool latency"},
						"distribution":    map[string]interface{}{"type": "string", "enum": []string{"fixed", "uniform", "normal", "exponential"}},
						"failure_rate":    map[string]interface{}{"type": "number", "minimum": 0, "maximum": 1},
						"failure_mode":    map[string]interface{}{"type": "string", "enum": []string{"timeout", "error", "panic"}},
					},
				},
				"LatencyConfigUpdate": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"default_latency": map[string]interface{}{"type": "string", "description": "Default latency (e.g., '5s', '30s')"},
						"distribution":    map[string]interface{}{"type": "string", "enum": []string{"fixed", "uniform", "normal", "exponential"}},
						"failure_rate":    map[string]interface{}{"type": "number", "minimum": 0, "maximum": 1},
						"failure_mode":    map[string]interface{}{"type": "string", "enum": []string{"timeout", "error", "panic"}},
						"min_latency":     map[string]interface{}{"type": "string"},
						"max_latency":     map[string]interface{}{"type": "string"},
						"mean_latency":    map[string]interface{}{"type": "string"},
						"stddev_latency":  map[string]interface{}{"type": "string"},
					},
				},
				"InvocationStats": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"total_calls":          map[string]interface{}{"type": "integer"},
						"total_errors":         map[string]interface{}{"type": "integer"},
						"sample_count":         map[string]interface{}{"type": "integer"},
						"avg_latency_seconds":  map[string]interface{}{"type": "number"},
						"p50_latency_seconds":  map[string]interface{}{"type": "number"},
						"p95_latency_seconds":  map[string]interface{}{"type": "number"},
						"p99_latency_seconds":  map[string]interface{}{"type": "number"},
					},
				},
				"ErrorResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"error":   map[string]interface{}{"type": "string"},
						"message": map[string]interface{}{"type": "string"},
						"code":    map[string]interface{}{"type": "integer"},
					},
				},
			},
		},
	}
}
