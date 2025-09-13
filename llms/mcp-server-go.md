Go MCP Servers: Create, Build, and Run

- Scope: Practical guide to author, build, and containerize Go MCP servers.
- References: See working example `mcp-servers/go/fast-time-server` and the Copier template in `mcp-servers/templates/go`.

**Project Layout**
- Recommended structure for a new server `fast_time_lite`:

```
fast_time_lite/
  go.mod
  main.go
  Makefile
  Dockerfile
  README.md
```

**Minimal Server (stdio)**
- Implements a basic MCP server with one tool `get_system_time` using `mcp-go`.

```go
// main.go
package main

import (
    "encoding/json"
    "log"
    "os"
    "time"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

const (
    appName    = "fast-time-lite"
    appVersion = "0.1.0"
)

func handleGetSystemTime(_ mcp.CallToolRequest) (mcp.ToolResult, error) {
    payload := map[string]string{"time": time.Now().UTC().Format(time.RFC3339), "timezone": "UTC"}
    b, _ := json.Marshal(payload)
    return mcp.StringResult(string(b)), nil
}

func main() {
    logger := log.New(os.Stderr, "", log.LstdFlags)
    logger.Printf("starting %s %s (stdio)", appName, appVersion)

    s := server.NewMCPServer(
        appName,
        appVersion,
        server.WithToolCapabilities(false),
        server.WithLogging(),
        server.WithRecovery(),
    )

    tool := mcp.NewTool("get_system_time",
        mcp.WithDescription("Get current time in UTC (RFC3339)"),
        mcp.WithTitleAnnotation("Get System Time"),
        mcp.WithReadOnlyHintAnnotation(true),
    )
    s.AddTool(tool, handleGetSystemTime)

    if err := server.ServeStdio(s); err != nil { logger.Fatalf("stdio error: %v", err) }
}
```

**go.mod (template)**

```go
module github.com/yourorg/fast-time-lite

go 1.23
toolchain go1.23.10

require github.com/mark3labs/mcp-go v0.32.0
```

**Makefile (template)**

```makefile
.PHONY: tidy fmt test build run clean

BIN ?= fast-time-lite
GO  ?= go

tidy:  ; $(GO) mod tidy && $(GO) mod verify
fmt:   ; $(GO) fmt ./... && go run golang.org/x/tools/cmd/goimports@latest -w .
test:  ; $(GO) test -race -timeout=90s ./...
build: ; CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w" -o dist/$(BIN) .
run: build ; ./dist/$(BIN)
clean: ; rm -rf dist
```

**Dockerfile (template)**

```dockerfile
FROM --platform=$TARGETPLATFORM golang:1.23 AS builder
WORKDIR /src
COPY go.mod .
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/fast-time-lite .

FROM scratch
COPY --from=builder /usr/local/bin/fast-time-lite /fast-time-lite
ENTRYPOINT ["/fast-time-lite"]
```

**Run Locally**
- Build and run over stdio:
  - `make run`
- Quick JSON-RPC check (stdin → stdout):
  - `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | ./dist/fast-time-lite`

**Scaffold With Copier**
- Generate a new Go MCP server from the template:
  - `mcp-servers/scaffold-go-server.sh fast_time_lite` (defaults to `mcp-servers/go/fast_time_lite`)
  - Then: `cd mcp-servers/go/fast_time_lite && go mod tidy && make run`

**Tips & Patterns**
- Log to stderr to avoid protocol noise on stdio.
- Keep business logic in separate functions; keep MCP wiring minimal in `main.go`.
- Start with stdio; add HTTP/SSE later following `go/fast-time-server` if needed.
