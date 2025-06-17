// -*- coding: utf-8 -*-
// fast-time-server – ultra‑fast MCP server exposing get_system_time
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti
//
// This file implements an MCP server written in Go that provides a single
// tool `get_system_time(timezone)` returning the current wall‑clock time
// for a given IANA timezone in RFC3339 format.
//
// It uses the `mcp-go` library for MCP protocol handling and provides
// a simple, efficient implementation that avoids unnecessary parsing of
// timezone data by caching loaded locations.
package main

import (
    "context"
    "fmt"
    "log"
    "sync"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

// --- ultra-light tz cache (avoids parsing zoneinfo repeatedly)
var tzCache sync.Map

func loadLocation(name string) (*time.Location, error) {
    if loc, ok := tzCache.Load(name); ok {
        return loc.(*time.Location), nil
    }
    loc, err := time.LoadLocation(name)
    if err != nil {
        return nil, err
    }
    tzCache.Store(name, loc)
    return loc, nil
}

func main() {
    // Create the core MCP server – no custom logger needed
    s := server.NewMCPServer(
        "fast-time-server",
        "1.0.0",
        server.WithToolCapabilities(false), // expose only tools
        server.WithLogging(),               // use built-in logging
        server.WithRecovery(),              // panic-safe handlers
    )

    // Declare the tool schema
    timeTool := mcp.NewTool("get_system_time",
        mcp.WithDescription("Return current time in RFC3339 for an IANA timezone"),
        mcp.WithString("timezone", mcp.Description("IANA zone, default UTC")),
    )

    // Attach the handler
    s.AddTool(timeTool, func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
        tz := req.GetString("timezone", "UTC") // modern accessor

        loc, err := loadLocation(tz)
        if err != nil {
            return mcp.NewToolResultError(fmt.Sprintf("unknown timezone %q", tz)), nil
        }
        now := time.Now().In(loc).Format(time.RFC3339)
        return mcp.NewToolResultText(now), nil
    })

    // Serve over stdio (fastest transport)
    if err := server.ServeStdio(s); err != nil {
        log.Fatalf("server error: %v", err)
    }
}
