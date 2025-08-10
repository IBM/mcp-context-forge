// -*- coding: utf-8 -*-
// rest_handlers_test.go - Tests for REST API handlers
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package main

import (
    "bytes"
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"
)

func TestHandleRESTGetTime(t *testing.T) {
    tests := []struct {
        name       string
        url        string
        wantStatus int
        checkBody  func(t *testing.T, body TimeResponse)
    }{
        {
            name:       "Default UTC timezone",
            url:        "/api/v1/time",
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body TimeResponse) {
                if body.Timezone != "UTC" {
                    t.Errorf("want timezone UTC, got %s", body.Timezone)
                }
                if body.Time == "" {
                    t.Error("time field should not be empty")
                }
            },
        },
        {
            name:       "Query parameter timezone",
            url:        "/api/v1/time?timezone=America/New_York",
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body TimeResponse) {
                if body.Timezone != "America/New_York" {
                    t.Errorf("want timezone America/New_York, got %s", body.Timezone)
                }
            },
        },
        {
            name:       "Path parameter timezone",
            url:        "/api/v1/time/Europe/London",
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body TimeResponse) {
                if body.Timezone != "Europe/London" {
                    t.Errorf("want timezone Europe/London, got %s", body.Timezone)
                }
            },
        },
        {
            name:       "Invalid timezone",
            url:        "/api/v1/time?timezone=Invalid/Zone",
            wantStatus: http.StatusBadRequest,
            checkBody:  nil,
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            req := httptest.NewRequest(http.MethodGet, tt.url, nil)
            w := httptest.NewRecorder()

            handleRESTGetTime(w, req)

            if w.Code != tt.wantStatus {
                t.Errorf("want status %d, got %d", tt.wantStatus, w.Code)
            }

            if tt.checkBody != nil && w.Code == http.StatusOK {
                var body TimeResponse
                if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
                    t.Fatalf("failed to decode response: %v", err)
                }
                tt.checkBody(t, body)
            }
        })
    }
}

func TestHandleRESTConvertTime(t *testing.T) {
    tests := []struct {
        name       string
        request    ConvertRequest
        wantStatus int
        checkBody  func(t *testing.T, body ConvertResponse)
    }{
        {
            name: "Valid conversion",
            request: ConvertRequest{
                Time:         "2025-01-10T10:00:00Z",
                FromTimezone: "UTC",
                ToTimezone:   "Asia/Tokyo",
            },
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body ConvertResponse) {
                if body.FromTimezone != "UTC" {
                    t.Errorf("want from_timezone UTC, got %s", body.FromTimezone)
                }
                if body.ToTimezone != "Asia/Tokyo" {
                    t.Errorf("want to_timezone Asia/Tokyo, got %s", body.ToTimezone)
                }
                if !strings.Contains(body.ConvertedTime, "+09:00") {
                    t.Errorf("converted time should contain Tokyo offset +09:00, got %s", body.ConvertedTime)
                }
            },
        },
        {
            name: "Invalid source timezone",
            request: ConvertRequest{
                Time:         "2025-01-10T10:00:00Z",
                FromTimezone: "Invalid/Zone",
                ToTimezone:   "UTC",
            },
            wantStatus: http.StatusBadRequest,
            checkBody:  nil,
        },
        {
            name: "Invalid time format",
            request: ConvertRequest{
                Time:         "not-a-time",
                FromTimezone: "UTC",
                ToTimezone:   "UTC",
            },
            wantStatus: http.StatusBadRequest,
            checkBody:  nil,
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            body, _ := json.Marshal(tt.request)
            req := httptest.NewRequest(http.MethodPost, "/api/v1/convert", bytes.NewReader(body))
            req.Header.Set("Content-Type", "application/json")
            w := httptest.NewRecorder()

            handleRESTConvertTime(w, req)

            if w.Code != tt.wantStatus {
                t.Errorf("want status %d, got %d", tt.wantStatus, w.Code)
            }

            if tt.checkBody != nil && w.Code == http.StatusOK {
                var respBody ConvertResponse
                if err := json.NewDecoder(w.Body).Decode(&respBody); err != nil {
                    t.Fatalf("failed to decode response: %v", err)
                }
                tt.checkBody(t, respBody)
            }
        })
    }
}

func TestHandleRESTListTimezones(t *testing.T) {
    tests := []struct {
        name       string
        url        string
        wantStatus int
        checkBody  func(t *testing.T, body map[string]interface{})
    }{
        {
            name:       "List all timezones",
            url:        "/api/v1/timezones",
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body map[string]interface{}) {
                timezones, ok := body["timezones"].([]interface{})
                if !ok {
                    t.Fatal("timezones field should be an array")
                }
                if len(timezones) == 0 {
                    t.Error("timezones should not be empty")
                }
            },
        },
        {
            name:       "Filter timezones",
            url:        "/api/v1/timezones?filter=Europe",
            wantStatus: http.StatusOK,
            checkBody: func(t *testing.T, body map[string]interface{}) {
                timezones, ok := body["timezones"].([]interface{})
                if !ok {
                    t.Fatal("timezones field should be an array")
                }
                for _, tz := range timezones {
                    tzStr, _ := tz.(string)
                    if !strings.Contains(tzStr, "Europe") {
                        t.Errorf("filtered timezone should contain 'Europe', got %s", tzStr)
                    }
                }
            },
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            req := httptest.NewRequest(http.MethodGet, tt.url, nil)
            w := httptest.NewRecorder()

            handleRESTListTimezones(w, req)

            if w.Code != tt.wantStatus {
                t.Errorf("want status %d, got %d", tt.wantStatus, w.Code)
            }

            if tt.checkBody != nil && w.Code == http.StatusOK {
                var body map[string]interface{}
                if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
                    t.Fatalf("failed to decode response: %v", err)
                }
                tt.checkBody(t, body)
            }
        })
    }
}

func TestHandleRESTTestEcho(t *testing.T) {
    tests := []struct {
        name        string
        url         string
        wantStatus  int
        wantMessage string
    }{
        {
            name:        "Default message",
            url:         "/api/v1/test/echo",
            wantStatus:  http.StatusOK,
            wantMessage: "Hello from fast-time-server!",
        },
        {
            name:        "Custom message",
            url:         "/api/v1/test/echo?message=TestMessage",
            wantStatus:  http.StatusOK,
            wantMessage: "TestMessage",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            req := httptest.NewRequest(http.MethodGet, tt.url, nil)
            w := httptest.NewRecorder()

            handleRESTTestEcho(w, req)

            if w.Code != tt.wantStatus {
                t.Errorf("want status %d, got %d", tt.wantStatus, w.Code)
            }

            var body map[string]interface{}
            if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
                t.Fatalf("failed to decode response: %v", err)
            }

            if echo, ok := body["echo"].(string); !ok || echo != tt.wantMessage {
                t.Errorf("want echo %s, got %s", tt.wantMessage, echo)
            }
        })
    }
}

func TestHandleRESTBatchConvert(t *testing.T) {
    req := BatchConvertRequest{
        Conversions: []ConvertRequest{
            {
                Time:         "2025-01-10T10:00:00Z",
                FromTimezone: "UTC",
                ToTimezone:   "Asia/Tokyo",
            },
            {
                Time:         "2025-01-10T10:00:00Z",
                FromTimezone: "UTC",
                ToTimezone:   "America/New_York",
            },
        },
    }

    body, _ := json.Marshal(req)
    httpReq := httptest.NewRequest(http.MethodPost, "/api/v1/convert/batch", bytes.NewReader(body))
    httpReq.Header.Set("Content-Type", "application/json")
    w := httptest.NewRecorder()

    handleRESTBatchConvert(w, httpReq)

    if w.Code != http.StatusOK {
        t.Errorf("want status %d, got %d", http.StatusOK, w.Code)
    }

    var response BatchConvertResponse
    if err := json.NewDecoder(w.Body).Decode(&response); err != nil {
        t.Fatalf("failed to decode response: %v", err)
    }

    if len(response.Results) != 2 {
        t.Errorf("want 2 results, got %d", len(response.Results))
    }

    if response.Results[0].ToTimezone != "Asia/Tokyo" {
        t.Errorf("first result should be Tokyo, got %s", response.Results[0].ToTimezone)
    }

    if response.Results[1].ToTimezone != "America/New_York" {
        t.Errorf("second result should be New York, got %s", response.Results[1].ToTimezone)
    }
}

func TestHandleOpenAPISpec(t *testing.T) {
    req := httptest.NewRequest(http.MethodGet, "/api/v1/openapi.json", nil)
    w := httptest.NewRecorder()

    handleOpenAPISpec(w, req)

    if w.Code != http.StatusOK {
        t.Errorf("want status %d, got %d", http.StatusOK, w.Code)
    }

    var spec map[string]interface{}
    if err := json.NewDecoder(w.Body).Decode(&spec); err != nil {
        t.Fatalf("failed to decode OpenAPI spec: %v", err)
    }

    if spec["openapi"] != "3.0.0" {
        t.Errorf("want OpenAPI version 3.0.0, got %v", spec["openapi"])
    }

    if info, ok := spec["info"].(map[string]interface{}); ok {
        if info["title"] != "Fast Time Server API" {
            t.Errorf("want title 'Fast Time Server API', got %v", info["title"])
        }
    } else {
        t.Error("OpenAPI spec should have info field")
    }
}

func TestCORSMiddleware(t *testing.T) {
    handler := corsMiddleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
        w.WriteHeader(http.StatusOK)
    }))

    // Test OPTIONS request
    req := httptest.NewRequest(http.MethodOptions, "/api/v1/time", nil)
    w := httptest.NewRecorder()

    handler.ServeHTTP(w, req)

    if w.Code != http.StatusNoContent {
        t.Errorf("OPTIONS request should return 204, got %d", w.Code)
    }

    // Check CORS headers
    if h := w.Header().Get("Access-Control-Allow-Origin"); h != "*" {
        t.Errorf("want CORS origin *, got %s", h)
    }

    if h := w.Header().Get("Access-Control-Allow-Methods"); !strings.Contains(h, "GET") {
        t.Errorf("CORS methods should include GET, got %s", h)
    }
}
