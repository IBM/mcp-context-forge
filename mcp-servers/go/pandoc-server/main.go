// main.go
package main

import (
    "context"
    "log"
    "os"
    "os/exec"
    "strings"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
)

const (
    appName    = "pandoc-server"
    appVersion = "0.2.0"
)

func handlePandoc(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    from, err := req.RequireString("from")
    if err != nil {
        return mcp.NewToolResultError("from parameter is required"), nil
    }

    to, err := req.RequireString("to")
    if err != nil {
        return mcp.NewToolResultError("to parameter is required"), nil
    }

    input, err := req.RequireString("input")
    if err != nil {
        return mcp.NewToolResultError("input parameter is required"), nil
    }

    // Optional parameters
    standalone := req.GetBool("standalone", false)
    title := req.GetString("title", "")
    metadata := req.GetString("metadata", "")
    toc := req.GetBool("toc", false)

    // Build pandoc command
    args := []string{"-f", from, "-t", to}

    if standalone {
        args = append(args, "--standalone")
    }

    if title != "" {
        args = append(args, "--metadata", "title="+title)
    }

    if metadata != "" {
        args = append(args, "--metadata", metadata)
    }

    if toc {
        args = append(args, "--toc")
    }

    cmd := exec.CommandContext(ctx, "pandoc", args...) // #nosec G204 -- Arguments are passed without a shell and are intended user-controlled conversion options.
    cmd.Stdin = strings.NewReader(input)
    var out strings.Builder
    cmd.Stdout = &out
    var stderr strings.Builder
    cmd.Stderr = &stderr

    if err := cmd.Run(); err != nil {
        errMsg := stderr.String()
        if errMsg == "" {
            errMsg = err.Error()
        }
        return mcp.NewToolResultError("Pandoc conversion failed: " + errMsg), nil
    }

    return mcp.NewToolResultText(out.String()), nil
}

func handleHealth(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    cmd := exec.Command("pandoc", "--version")
    out, err := cmd.CombinedOutput()
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }
    return mcp.NewToolResultText(string(out)), nil
}

func handleListFormats(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
    formatType := req.GetString("type", "all")

    var cmd *exec.Cmd
    switch formatType {
    case "input":
        cmd = exec.Command("pandoc", "--list-input-formats")
    case "output":
        cmd = exec.Command("pandoc", "--list-output-formats")
    case "all":
        inputCmd := exec.Command("pandoc", "--list-input-formats")
        inputOut, err := inputCmd.CombinedOutput()
        if err != nil {
            return mcp.NewToolResultError("Failed to get input formats: " + err.Error()), nil
        }

        outputCmd := exec.Command("pandoc", "--list-output-formats")
        outputOut, err := outputCmd.CombinedOutput()
        if err != nil {
            return mcp.NewToolResultError("Failed to get output formats: " + err.Error()), nil
        }

        result := "Input Formats:\n" + string(inputOut) + "\nOutput Formats:\n" + string(outputOut)
        return mcp.NewToolResultText(result), nil
    default:
        return mcp.NewToolResultError("Invalid type parameter. Use 'input', 'output', or 'all'"), nil
    }

    out, err := cmd.CombinedOutput()
    if err != nil {
        return mcp.NewToolResultError(err.Error()), nil
    }
    return mcp.NewToolResultText(string(out)), nil
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

    pandocTool := mcp.NewTool("pandoc",
        mcp.WithDescription("Convert text from one format to another using pandoc."),
        mcp.WithTitleAnnotation("Pandoc"),
        mcp.WithString("from",
            mcp.Required(),
            mcp.Description("The input format (e.g., markdown, html, latex, rst, docx, epub)"),
        ),
        mcp.WithString("to",
            mcp.Required(),
            mcp.Description("The output format (e.g., html, markdown, latex, pdf, docx, plain)"),
        ),
        mcp.WithString("input",
            mcp.Required(),
            mcp.Description("The text to convert"),
        ),
        mcp.WithBoolean("standalone",
            mcp.Description("Produce a standalone document (default: false)"),
        ),
        mcp.WithString("title",
            mcp.Description("Document title for standalone documents"),
        ),
        mcp.WithString("metadata",
            mcp.Description("Additional metadata in key=value format"),
        ),
        mcp.WithBoolean("toc",
            mcp.Description("Include table of contents (default: false)"),
        ),
    )
    s.AddTool(pandocTool, handlePandoc)

    healthTool := mcp.NewTool("health",
        mcp.WithDescription("Check if pandoc is installed and return the version."),
        mcp.WithTitleAnnotation("Health Check"),
        mcp.WithReadOnlyHintAnnotation(true),
    )
    s.AddTool(healthTool, handleHealth)

    listFormatsTool := mcp.NewTool("list-formats",
        mcp.WithDescription("List available pandoc input and output formats."),
        mcp.WithTitleAnnotation("List Formats"),
        mcp.WithString("type",
            mcp.Description("Format type to list: 'input', 'output', or 'all' (default: 'all')"),
        ),
        mcp.WithReadOnlyHintAnnotation(true),
    )
    s.AddTool(listFormatsTool, handleListFormats)

    if err := server.ServeStdio(s); err != nil {
        logger.Fatalf("stdio error: %v", err)
    }
}
