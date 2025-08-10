// -*- coding: utf-8 -*-
// openapi.go - OpenAPI specification for fast-time-server REST API
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package main

// getOpenAPISpec returns the OpenAPI specification for the REST API
func getOpenAPISpec() map[string]interface{} {
	return map[string]interface{}{
		"openapi": "3.0.0",
		"info": map[string]interface{}{
			"title":       "Fast Time Server API",
			"description": "REST API for time-related operations, complementing the MCP protocol",
			"version":     "1.0.0",
			"contact": map[string]interface{}{
				"name": "Fast Time Server Team",
			},
		},
		"servers": []map[string]interface{}{
			{
				"url":         "http://localhost:8080",
				"description": "Local development server",
			},
		},
		"paths": map[string]interface{}{
			"/api/v1/time": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get current system time",
					"description": "Returns the current time in the specified timezone",
					"parameters": []map[string]interface{}{
						{
							"name":        "timezone",
							"in":          "query",
							"description": "IANA timezone (default: UTC)",
							"required":    false,
							"schema": map[string]interface{}{
								"type":    "string",
								"default": "UTC",
								"example": "America/New_York",
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Current time information",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/TimeResponse",
									},
								},
							},
						},
						"400": map[string]interface{}{
							"description": "Invalid timezone",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/ErrorResponse",
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/time/{timezone}": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get current time for specific timezone",
					"description": "Returns the current time in the specified timezone",
					"parameters": []map[string]interface{}{
						{
							"name":        "timezone",
							"in":          "path",
							"description": "IANA timezone",
							"required":    true,
							"schema": map[string]interface{}{
								"type":    "string",
								"example": "Europe/London",
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Current time information",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/TimeResponse",
									},
								},
							},
						},
						"400": map[string]interface{}{
							"description": "Invalid timezone",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/ErrorResponse",
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/convert": map[string]interface{}{
				"post": map[string]interface{}{
					"summary":     "Convert time between timezones",
					"description": "Converts a given time from one timezone to another",
					"requestBody": map[string]interface{}{
						"required": true,
						"content": map[string]interface{}{
							"application/json": map[string]interface{}{
								"schema": map[string]interface{}{
									"$ref": "#/components/schemas/ConvertRequest",
								},
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Converted time information",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/ConvertResponse",
									},
								},
							},
						},
						"400": map[string]interface{}{
							"description": "Invalid request",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/ErrorResponse",
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/convert/batch": map[string]interface{}{
				"post": map[string]interface{}{
					"summary":     "Batch convert times",
					"description": "Convert multiple times between timezones in a single request",
					"requestBody": map[string]interface{}{
						"required": true,
						"content": map[string]interface{}{
							"application/json": map[string]interface{}{
								"schema": map[string]interface{}{
									"$ref": "#/components/schemas/BatchConvertRequest",
								},
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Batch conversion results",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/BatchConvertResponse",
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/timezones": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "List available timezones",
					"description": "Returns a list of available IANA timezones",
					"parameters": []map[string]interface{}{
						{
							"name":        "filter",
							"in":          "query",
							"description": "Filter timezones by name",
							"required":    false,
							"schema": map[string]interface{}{
								"type":    "string",
								"example": "America",
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "List of timezones",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"type": "object",
										"properties": map[string]interface{}{
											"timezones": map[string]interface{}{
												"type": "array",
												"items": map[string]interface{}{
													"type": "string",
												},
											},
											"count": map[string]interface{}{
												"type": "integer",
											},
										},
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/timezones/{timezone}/info": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Get timezone information",
					"description": "Returns detailed information about a specific timezone",
					"parameters": []map[string]interface{}{
						{
							"name":        "timezone",
							"in":          "path",
							"description": "IANA timezone",
							"required":    true,
							"schema": map[string]interface{}{
								"type":    "string",
								"example": "Asia/Tokyo",
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Timezone information",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/TimezoneInfo",
									},
								},
							},
						},
						"400": map[string]interface{}{
							"description": "Invalid timezone",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"$ref": "#/components/schemas/ErrorResponse",
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/test/echo": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Echo test endpoint",
					"description": "Simple echo endpoint for testing",
					"parameters": []map[string]interface{}{
						{
							"name":        "message",
							"in":          "query",
							"description": "Message to echo",
							"required":    false,
							"schema": map[string]interface{}{
								"type":    "string",
								"default": "Hello from fast-time-server!",
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Echo response",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"type": "object",
										"properties": map[string]interface{}{
											"echo": map[string]interface{}{
												"type": "string",
											},
											"timestamp": map[string]interface{}{
												"type": "string",
											},
											"server": map[string]interface{}{
												"type": "string",
											},
										},
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/test/validate": map[string]interface{}{
				"post": map[string]interface{}{
					"summary":     "Validate JSON endpoint",
					"description": "Validates and echoes JSON input",
					"requestBody": map[string]interface{}{
						"required": true,
						"content": map[string]interface{}{
							"application/json": map[string]interface{}{
								"schema": map[string]interface{}{
									"type": "object",
								},
							},
						},
					},
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Validation response",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"type": "object",
										"properties": map[string]interface{}{
											"valid": map[string]interface{}{
												"type": "boolean",
											},
											"received": map[string]interface{}{
												"type": "object",
											},
											"timestamp": map[string]interface{}{
												"type": "string",
											},
										},
									},
								},
							},
						},
					},
				},
			},
			"/api/v1/test/performance": map[string]interface{}{
				"get": map[string]interface{}{
					"summary":     "Performance test endpoint",
					"description": "Returns performance metrics",
					"responses": map[string]interface{}{
						"200": map[string]interface{}{
							"description": "Performance metrics",
							"content": map[string]interface{}{
								"application/json": map[string]interface{}{
									"schema": map[string]interface{}{
										"type": "object",
										"properties": map[string]interface{}{
											"operations": map[string]interface{}{
												"type": "integer",
											},
											"duration_ms": map[string]interface{}{
												"type": "integer",
											},
											"duration_ns": map[string]interface{}{
												"type": "integer",
											},
											"ops_per_second": map[string]interface{}{
												"type": "number",
											},
											"server_time": map[string]interface{}{
												"type": "string",
											},
										},
									},
								},
							},
						},
					},
				},
			},
		},
		"components": map[string]interface{}{
			"schemas": map[string]interface{}{
				"TimeResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"time": map[string]interface{}{
							"type":        "string",
							"description": "Current time in RFC3339 format",
							"example":     "2025-01-10T14:30:00Z",
						},
						"timezone": map[string]interface{}{
							"type":        "string",
							"description": "Timezone name",
							"example":     "UTC",
						},
						"unix": map[string]interface{}{
							"type":        "integer",
							"description": "Unix timestamp",
							"example":     1736517000,
						},
						"utc": map[string]interface{}{
							"type":        "string",
							"description": "Time in UTC",
							"example":     "2025-01-10T14:30:00Z",
						},
					},
				},
				"ConvertRequest": map[string]interface{}{
					"type":     "object",
					"required": []string{"time", "from_timezone", "to_timezone"},
					"properties": map[string]interface{}{
						"time": map[string]interface{}{
							"type":        "string",
							"description": "Time to convert",
							"example":     "2025-01-10T14:30:00Z",
						},
						"from_timezone": map[string]interface{}{
							"type":        "string",
							"description": "Source timezone",
							"example":     "UTC",
						},
						"to_timezone": map[string]interface{}{
							"type":        "string",
							"description": "Target timezone",
							"example":     "America/New_York",
						},
					},
				},
				"ConvertResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"original_time": map[string]interface{}{
							"type":        "string",
							"description": "Original time",
						},
						"from_timezone": map[string]interface{}{
							"type":        "string",
							"description": "Source timezone",
						},
						"converted_time": map[string]interface{}{
							"type":        "string",
							"description": "Converted time",
						},
						"to_timezone": map[string]interface{}{
							"type":        "string",
							"description": "Target timezone",
						},
						"unix": map[string]interface{}{
							"type":        "integer",
							"description": "Unix timestamp",
						},
					},
				},
				"BatchConvertRequest": map[string]interface{}{
					"type":     "object",
					"required": []string{"conversions"},
					"properties": map[string]interface{}{
						"conversions": map[string]interface{}{
							"type": "array",
							"items": map[string]interface{}{
								"$ref": "#/components/schemas/ConvertRequest",
							},
						},
					},
				},
				"BatchConvertResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"results": map[string]interface{}{
							"type": "array",
							"items": map[string]interface{}{
								"$ref": "#/components/schemas/ConvertResponse",
							},
						},
					},
				},
				"TimezoneInfo": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"name": map[string]interface{}{
							"type":        "string",
							"description": "Timezone name",
						},
						"offset": map[string]interface{}{
							"type":        "string",
							"description": "UTC offset",
							"example":     "+09:00",
						},
						"current_time": map[string]interface{}{
							"type":        "string",
							"description": "Current time in this timezone",
						},
						"is_dst": map[string]interface{}{
							"type":        "boolean",
							"description": "Is daylight saving time active",
						},
						"abbreviation": map[string]interface{}{
							"type":        "string",
							"description": "Timezone abbreviation",
							"example":     "JST",
						},
					},
				},
				"ErrorResponse": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"error": map[string]interface{}{
							"type":        "string",
							"description": "Error type",
						},
						"message": map[string]interface{}{
							"type":        "string",
							"description": "Error message",
						},
						"code": map[string]interface{}{
							"type":        "integer",
							"description": "HTTP status code",
						},
					},
				},
			},
		},
	}
}
