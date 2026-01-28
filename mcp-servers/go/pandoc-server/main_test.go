package main

import (
    "context"
    "os/exec"
    "strings"
    "testing"

    "github.com/mark3labs/mcp-go/mcp"
)

func TestPandocInstalled(t *testing.T) {
    cmd := exec.Command("pandoc", "--version")
    out, err := cmd.CombinedOutput()
    if err != nil {
        t.Fatalf("pandoc not installed: %v", err)
    }
    t.Logf("Pandoc version: %s", string(out))
}

func TestPandocConversion(t *testing.T) {
    tests := []struct {
        name  string
        from  string
        to    string
        input string
        want  string
    }{
        {
            name:  "markdown to html",
            from:  "markdown",
            to:    "html",
            input: "# Hello World\n\nThis is **bold** text.",
            want:  "<h1",
        },
        {
            name:  "html to markdown",
            from:  "html",
            to:    "markdown",
            input: "<h1>Hello</h1><p>This is <strong>bold</strong> text.</p>",
            want:  "Hello",
        },
        {
            name:  "markdown to plain",
            from:  "markdown",
            to:    "plain",
            input: "# Hello\n\nThis is **bold** text.",
            want:  "Hello",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            cmd := exec.Command("pandoc", "-f", tt.from, "-t", tt.to)
            cmd.Stdin = strings.NewReader(tt.input)
            var out strings.Builder
            cmd.Stdout = &out
            var stderr strings.Builder
            cmd.Stderr = &stderr

            if err := cmd.Run(); err != nil {
                t.Fatalf("pandoc failed: %v, stderr: %s", err, stderr.String())
            }

            result := out.String()
            if !strings.Contains(result, tt.want) {
                t.Errorf("got %q, want substring %q", result, tt.want)
            }
        })
    }
}

func TestHandlers(t *testing.T) {
    ctx := context.Background()

    t.Run("health handler", func(t *testing.T) {
        req := mcp.CallToolRequest{
            Params: mcp.CallToolParams{
                Name:      "health",
                Arguments: map[string]interface{}{},
            },
        }
        result, err := handleHealth(ctx, req)
        if err != nil {
            t.Fatalf("handleHealth failed: %v", err)
        }
        if result == nil {
            t.Fatal("handleHealth returned nil")
        }
    })

    t.Run("pandoc handler with valid params", func(t *testing.T) {
        req := mcp.CallToolRequest{
            Params: mcp.CallToolParams{
                Name: "pandoc",
                Arguments: map[string]interface{}{
                    "from":  "markdown",
                    "to":    "html",
                    "input": "# Hello World",
                },
            },
        }
        result, err := handlePandoc(ctx, req)
        if err != nil {
            t.Fatalf("handlePandoc failed: %v", err)
        }
        if result == nil {
            t.Fatal("handlePandoc returned nil")
        }
    })

    t.Run("pandoc handler missing from param", func(t *testing.T) {
        req := mcp.CallToolRequest{
            Params: mcp.CallToolParams{
                Name: "pandoc",
                Arguments: map[string]interface{}{
                    "to":    "html",
                    "input": "# Hello World",
                },
            },
        }
        result, err := handlePandoc(ctx, req)
        if err != nil {
            t.Fatalf("unexpected error: %v", err)
        }
        if result == nil {
            t.Fatal("expected error result, got nil")
        }
    })
}
