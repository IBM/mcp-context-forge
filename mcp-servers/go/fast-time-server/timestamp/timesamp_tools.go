package timestamp

import (
    "context"

    "time"

    "github.com/mark3labs/mcp-go/mcp"
    "github.com/mark3labs/mcp-go/server"
    "github.com/maypok86/otter"
)

type TimestampManager struct {
    cache otter.Cache[string, string]
}

// adds session var functionality to the test server
func NewTimestampManager(s *server.MCPServer) *TimestampManager {
    cache, err := otter.MustBuilder[string, string](1_000_000).
        WithTTL(time.Duration(5 * time.Minute)).
        Build()
    if err != nil {
        panic(err)
    }
    manager := &TimestampManager{cache: cache}
    manager.AddTimestampTools(s)
    return manager
}

func (m *TimestampManager) setTimestamp( //
    ctx context.Context, request mcp.CallToolRequest, //
) (*mcp.CallToolResult, error) {
    note := request.GetString("note", "")
    now := time.Now().Format(time.RFC3339)
    session := server.ClientSessionFromContext(ctx)
    if session == nil {
        return mcp.NewToolResultError("Session not found"), nil
    }
    txt := now + " - " + note
    m.cache.Set(session.SessionID(), txt)

    return mcp.NewToolResultText(txt), nil
}

func (m *TimestampManager) getTimestamp( //
    ctx context.Context, request mcp.CallToolRequest, //
) (*mcp.CallToolResult, error) {

    session := server.ClientSessionFromContext(ctx)
    if session == nil {
        return mcp.NewToolResultError("Session not found"), nil
    }
    now, ok := m.cache.Get(session.SessionID())
    if !ok {
        now = "No timestamp set"
    }

    return mcp.NewToolResultText(now), nil
}

func (m *TimestampManager) clearTimestamp( //
    ctx context.Context, request mcp.CallToolRequest, //
) (*mcp.CallToolResult, error) {

    session := server.ClientSessionFromContext(ctx)
    if session == nil {
        return mcp.NewToolResultError("Session not found"), nil
    }
    m.cache.Delete(session.SessionID())

    return mcp.NewToolResultText("Timestamp cleared"), nil
}

func (m *TimestampManager) AddTimestampTools(s *server.MCPServer) {
    setTimestamp := mcp.NewTool( //
        "set_timestamp", //
        mcp.WithDescription("Sets session timestamp with a note"),
        mcp.WithString("note",
            mcp.Required(),
            mcp.Description("Note to attach to timestamp"),
        ),
    )
    getTimestamp := mcp.NewTool( //
        "get_timestamp", mcp.WithDescription("Gets session timestamp"),
    )
    clearTimestamp := mcp.NewTool( //
        "clear_timestamp", mcp.WithDescription("Clears session timestamp"),
    )
    s.AddTool(setTimestamp, m.setTimestamp)
    s.AddTool(getTimestamp, m.getTimestamp)
    s.AddTool(clearTimestamp, m.clearTimestamp)
}
