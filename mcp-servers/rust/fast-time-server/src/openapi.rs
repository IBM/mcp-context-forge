// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! OpenAPI 3.0 spec and Swagger UI page for the `/api/v1` REST surface, ported
//! from the Go fast-time-server.

use serde_json::{Value, json};

/// Swagger UI page served at `/api/v1/docs`.
pub(crate) const DOCS_HTML: &str = r#"<!DOCTYPE html>
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
</html>"#;

/// OpenAPI 3.0 document describing the `/api/v1` endpoints.
pub(crate) fn spec() -> Value {
    json!({
        "openapi": "3.0.0",
        "info": {
            "title": "Fast Time Server API",
            "description": "REST API for time-related operations, complementing the MCP protocol",
            "version": "1.0.0",
            "contact": { "name": "Fast Time Server Team" }
        },
        "servers": [
            { "url": "http://localhost:8080", "description": "Local development server" }
        ],
        "paths": {
            "/api/v1/time": {
                "get": {
                    "summary": "Get current time",
                    "tags": ["Time"],
                    "parameters": [tz_query()],
                    "responses": ok("Current time in the requested timezone")
                }
            },
            "/api/v1/time/{timezone}": {
                "get": {
                    "summary": "Get current time for a timezone in the path",
                    "tags": ["Time"],
                    "parameters": [tz_path()],
                    "responses": ok("Current time in the requested timezone")
                }
            },
            "/api/v1/convert": {
                "post": {
                    "summary": "Convert a time between timezones",
                    "tags": ["Time"],
                    "requestBody": json_body(),
                    "responses": ok("Converted time")
                }
            },
            "/api/v1/convert/batch": {
                "post": {
                    "summary": "Convert multiple times between timezones",
                    "tags": ["Time"],
                    "requestBody": json_body(),
                    "responses": ok("Batch conversion results")
                }
            },
            "/api/v1/timezones": {
                "get": {
                    "summary": "List known timezones",
                    "tags": ["Timezones"],
                    "parameters": [{ "name": "filter", "in": "query", "required": false, "schema": { "type": "string" } }],
                    "responses": ok("List of timezones")
                }
            },
            "/api/v1/timezones/{timezone}/info": {
                "get": {
                    "summary": "Get information about a timezone",
                    "tags": ["Timezones"],
                    "parameters": [tz_path()],
                    "responses": ok("Timezone information")
                }
            },
            "/api/v1/resources": {
                "get": { "summary": "List available resources", "tags": ["Resources"], "responses": ok("List of resources") }
            },
            "/api/v1/resources/{uri}": {
                "get": {
                    "summary": "Read a resource by slug",
                    "tags": ["Resources"],
                    "parameters": [{ "name": "uri", "in": "path", "required": true, "schema": { "type": "string" } }],
                    "responses": ok("Resource contents")
                }
            },
            "/api/v1/prompts": {
                "get": { "summary": "List available prompts", "tags": ["Prompts"], "responses": ok("List of prompts") }
            },
            "/api/v1/prompts/{name}/execute": {
                "post": {
                    "summary": "Render a prompt with arguments",
                    "tags": ["Prompts"],
                    "parameters": [{ "name": "name", "in": "path", "required": true, "schema": { "type": "string" } }],
                    "requestBody": json_body(),
                    "responses": ok("Rendered prompt text")
                }
            },
            "/api/v1/test/echo": {
                "get": {
                    "summary": "Echo a message",
                    "tags": ["Test"],
                    "parameters": [{ "name": "message", "in": "query", "required": false, "schema": { "type": "string" } }],
                    "responses": ok("Echoed message")
                }
            },
            "/api/v1/test/validate": {
                "post": { "summary": "Validate a JSON body", "tags": ["Test"], "requestBody": json_body(), "responses": ok("Validation result") }
            },
            "/api/v1/test/performance": {
                "get": { "summary": "Run a small performance probe", "tags": ["Test"], "responses": ok("Performance metrics") }
            }
        }
    })
}

fn ok(description: &str) -> Value {
    json!({
        "200": {
            "description": description,
            "content": { "application/json": { "schema": { "type": "object" } } }
        }
    })
}

fn json_body() -> Value {
    json!({
        "required": true,
        "content": { "application/json": { "schema": { "type": "object" } } }
    })
}

fn tz_query() -> Value {
    json!({ "name": "timezone", "in": "query", "required": false, "schema": { "type": "string" } })
}

fn tz_path() -> Value {
    json!({ "name": "timezone", "in": "path", "required": true, "schema": { "type": "string" } })
}
