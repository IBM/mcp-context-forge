// Package mcp implements the Model Context Protocol (MCP) server functionality
// This file contains the MCP-compliant streamable HTTP transport implementation
// according to the MCP specification: https://modelcontextprotocol.io/specification/
package mcp

import (
    "context"
    "crypto/rand"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "net/http"
    "strings"
    "sync"
    "time"

    "calculator-server/internal/types"
)

// StreamableHTTPTransport implements MCP-compliant streamable HTTP transport
// This transport provides:
// - Single /mcp endpoint (per MCP specification)
// - Server-Sent Events (SSE) streaming support
// - Session management with cryptographically secure session IDs
// - CORS support with origin validation
// - Graceful shutdown capabilities
type StreamableHTTPTransport struct {
    server      *http.Server              // HTTP server instance
    mcpServer   *Server                   // Reference to the MCP server
    config      *StreamableHTTPConfig     // Transport configuration
    sessions    map[string]*types.Session // Active session storage
    sessionsMux sync.RWMutex              // Mutex for thread-safe session access
    connections int32                     // Current connection count (unused but reserved for future use)
}

// StreamableHTTPConfig contains MCP-compliant HTTP transport configuration
// All settings follow MCP specification requirements for streamable HTTP transport
type StreamableHTTPConfig struct {
    Host           string        // Server host (defaults to 127.0.0.1 for security)
    Port           int           // Server port (e.g., 8080)
    SessionTimeout time.Duration // How long sessions remain active without activity
    MaxConnections int           // Maximum concurrent connections allowed
    CORSEnabled    bool          // Whether to enable CORS headers
    CORSOrigins    []string      // Allowed origins for CORS requests
}

// NewStreamableHTTPTransport creates a new MCP-compliant HTTP transport instance
// This constructor sets up the HTTP server with MCP protocol compliance:
// - Defaults to localhost binding for security per MCP specification
// - Configures session management and CORS as needed
// - Starts background session cleanup routine
func NewStreamableHTTPTransport(mcpServer *Server, config *StreamableHTTPConfig) *StreamableHTTPTransport {
    // Apply secure defaults if no config provided
    if config == nil {
        config = &StreamableHTTPConfig{
            Host:           "127.0.0.1",                                                // Localhost for security (MCP recommendation)
            Port:           8080,                                                       // Default HTTP port
            SessionTimeout: 5 * time.Minute,                                            // 5 minute session timeout
            MaxConnections: 100,                                                        // Reasonable connection limit
            CORSEnabled:    true,                                                       // Enable CORS for web clients
            CORSOrigins:    []string{"http://localhost:3000", "http://127.0.0.1:3000"}, // Restrictive defaults for development
        }
    }

    // Apply additional secure defaults for CORS if not explicitly set
    if config.CORSEnabled && len(config.CORSOrigins) == 0 {
        config.CORSOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}
    }

    // Initialize the transport with thread-safe session storage
    transport := &StreamableHTTPTransport{
        mcpServer: mcpServer,
        config:    config,
        sessions:  make(map[string]*types.Session), // Thread-safe session map
    }

    // Setup HTTP routing with MCP-compliant endpoints
    mux := http.NewServeMux()
    transport.setupRoutes(mux)

    // Create HTTP server with CORS middleware
    transport.server = &http.Server{
        Addr:              fmt.Sprintf("%s:%d", config.Host, config.Port),
        Handler:           transport.corsMiddleware(mux), // Wrap with CORS support
        ReadHeaderTimeout: 10 * time.Second,
    }

    // Start background session cleanup goroutine to prevent memory leaks
    go transport.cleanupExpiredSessions()

    return transport
}

// setupRoutes configures MCP-compliant HTTP routes
// Per MCP specification, only a single endpoint is allowed for streamable HTTP transport
func (t *StreamableHTTPTransport) setupRoutes(mux *http.ServeMux) {
    // Single MCP endpoint as per specification - handles both POST (JSON-RPC) and GET (SSE)
    mux.HandleFunc("/mcp", t.handleMCP)
}

// corsMiddleware adds CORS headers if enabled
// This middleware handles CORS preflight requests and adds appropriate headers
// for cross-origin requests from web browsers
func (t *StreamableHTTPTransport) corsMiddleware(handler http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // Apply CORS headers if enabled in configuration
        if t.config.CORSEnabled {
            origin := r.Header.Get("Origin")
            // Only allow configured origins for security
            if t.isOriginAllowed(origin) {
                w.Header().Set("Access-Control-Allow-Origin", origin)
            }
            // Set required CORS headers for MCP protocol
            w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Accept, MCP-Protocol-Version, Mcp-Session-Id")
            w.Header().Set("Access-Control-Max-Age", "86400") // Cache preflight for 24 hours

            // Handle CORS preflight requests
            if r.Method == "OPTIONS" {
                w.WriteHeader(http.StatusOK)
                return
            }
        }
        // Continue to the actual handler
        handler.ServeHTTP(w, r)
    })
}

// isOriginAllowed checks if the origin is allowed for CORS
// This implements security by validating the Origin header against the configured allowed origins
func (t *StreamableHTTPTransport) isOriginAllowed(origin string) bool {
    // Check if the request origin matches any configured allowed origins
    for _, allowed := range t.config.CORSOrigins {
        if allowed == "*" || allowed == origin {
            return true
        }
    }
    // Origin not found in allowed list
    return false
}

// handleMCP handles MCP requests according to the streamable HTTP specification
// This is the main entry point for all MCP protocol interactions
// Supports both POST (JSON-RPC) and GET (SSE stream establishment) methods
func (t *StreamableHTTPTransport) handleMCP(w http.ResponseWriter, r *http.Request) {
    // Step 1: Validate required MCP Protocol Version header
    // This is mandatory per MCP specification
    protocolVersion := r.Header.Get("MCP-Protocol-Version")
    if protocolVersion == "" {
        http.Error(w, "MCP-Protocol-Version header required", http.StatusBadRequest)
        return
    }

    // Step 2: Handle optional session management
    // Sessions provide state continuity across multiple requests
    sessionID := r.Header.Get("Mcp-Session-Id")
    if sessionID != "" {
        // Validate session exists and hasn't expired
        if !t.isValidSession(sessionID) {
            http.Error(w, "Invalid or expired session", http.StatusUnauthorized)
            return
        }
        // Update session activity to prevent timeout
        t.updateSessionActivity(sessionID)
    }

    // Step 3: Route based on HTTP method
    switch r.Method {
    case http.MethodPost:
        // Handle JSON-RPC requests (with optional SSE streaming)
        t.handlePOST(w, r, sessionID)
    case http.MethodGet:
        // Handle SSE stream establishment
        t.handleGET(w, r, sessionID)
    default:
        // Only POST and GET are supported per MCP specification
        http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
    }
}

// handlePOST handles POST requests with JSON-RPC
// This method processes standard MCP JSON-RPC requests and can optionally
// stream responses via Server-Sent Events if the client accepts it
func (t *StreamableHTTPTransport) handlePOST(w http.ResponseWriter, r *http.Request, sessionID string) {
    // Step 1: Validate Accept header per MCP specification
    // Client must accept either JSON responses or SSE streaming
    accept := r.Header.Get("Accept")
    if !strings.Contains(accept, "application/json") && !strings.Contains(accept, "text/event-stream") {
        http.Error(w, "Accept header must include application/json or text/event-stream", http.StatusBadRequest)
        return
    }

    // Step 2: Read the JSON-RPC request from request body
    body, err := io.ReadAll(r.Body)
    if err != nil {
        http.Error(w, "Failed to read request body", http.StatusBadRequest)
        return
    }
    defer r.Body.Close()

    // Step 3: Parse JSON-RPC request according to MCP specification
    var mcpReq types.MCPRequest
    if err := json.Unmarshal(body, &mcpReq); err != nil {
        // Send proper JSON-RPC error response for invalid requests
        t.writeErrorResponse(w, nil, ErrorCodeInvalidRequest, "Invalid JSON-RPC request", err.Error())
        return
    }

    // Step 4: Process the request through the MCP server
    response := t.mcpServer.HandleRequest(mcpReq)

    // Step 5: Choose response format based on client preferences and request type
    if strings.Contains(accept, "text/event-stream") && t.shouldStream(&mcpReq) {
        // Use SSE streaming for real-time responses (e.g., long-running operations)
        t.writeSSEResponse(w, response, sessionID)
    } else {
        // Use standard JSON response for quick operations
        t.writeJSONResponse(w, response)
    }
}

// handleGET handles GET requests for SSE streams
// This method establishes Server-Sent Event streams for real-time communication
// Used when clients want to maintain persistent connections for streaming updates
func (t *StreamableHTTPTransport) handleGET(w http.ResponseWriter, r *http.Request, sessionID string) {
    // Step 1: Validate Accept header - GET requests must accept SSE
    accept := r.Header.Get("Accept")
    if !strings.Contains(accept, "text/event-stream") {
        http.Error(w, "Accept header must include text/event-stream for GET requests", http.StatusBadRequest)
        return
    }

    // Create new session if not provided
    if sessionID == "" {
        sessionID = t.createSession()
        log.Println("Created new session")
    }

    // Setup SSE stream
    t.setupSSEStream(w, r, sessionID)
}

// shouldStream determines if a request should use SSE streaming
func (t *StreamableHTTPTransport) shouldStream(req *types.MCPRequest) bool {
    // For now, we'll stream for tool calls that might take longer
    return req.Method == "tools/call"
}

// writeSSEResponse writes a response using Server-Sent Events
func (t *StreamableHTTPTransport) writeSSEResponse(w http.ResponseWriter, response types.MCPResponse, sessionID string) {
    // Setup SSE headers
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")

    if sessionID != "" {
        w.Header().Set("Mcp-Session-Id", sessionID)
    }

    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "Server does not support streaming", http.StatusInternalServerError)
        return
    }

    // Write SSE event
    eventID := t.generateEventID()
    responseJSON, err := json.Marshal(response)
    if err != nil {
        log.Printf("Failed to marshal response: %v", err)
        // Send error response to client
        errorResponse := fmt.Sprintf(`{"jsonrpc":"2.0","id":%v,"error":{"code":-32603,"message":"Internal error: failed to serialize response"}}`, response.ID)
        if writeErr := writeSSEEvent(w, eventID, "error", errorResponse); writeErr != nil {
            log.Printf("Failed to write SSE error response: %v", writeErr)
            return
        }
        flusher.Flush()
        return
    }

    if err := writeSSEEvent(w, eventID, "message", string(responseJSON)); err != nil {
        log.Printf("Failed to write SSE response: %v", err)
        return
    }
    flusher.Flush()
}

// setupSSEStream establishes an SSE stream connection
func (t *StreamableHTTPTransport) setupSSEStream(w http.ResponseWriter, r *http.Request, sessionID string) {
    // Setup SSE headers
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    w.Header().Set("Mcp-Session-Id", sessionID)

    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "Server does not support streaming", http.StatusInternalServerError)
        return
    }

    // Send initial connection event
    if err := writeSSEEvent(w, t.generateEventID(), "connection", fmt.Sprintf(`{"type":"connected","session_id":"%s"}`, sessionID)); err != nil {
        log.Printf("Failed to write initial SSE connection event: %v", err)
        return
    }
    flusher.Flush()

    // Keep connection alive with periodic heartbeats
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()

    ctx := r.Context()
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            if err := writeSSEEvent(w, t.generateEventID(), "heartbeat", `{"type":"ping"}`); err != nil {
                log.Printf("Failed to write SSE heartbeat: %v", err)
                return
            }
            flusher.Flush()
        }
    }
}

func sanitizeSSEField(value string) string {
    withoutCR := strings.ReplaceAll(value, "\r", "")
    return strings.ReplaceAll(withoutCR, "\n", "")
}

func writeSSEEvent(w io.Writer, id, event, data string) error {
    if _, err := io.WriteString(w, "id: "+sanitizeSSEField(id)+"\n"); err != nil { // #nosec G705 -- SSE protocol line with sanitized identifier.
        return err
    }
    if _, err := io.WriteString(w, "event: "+sanitizeSSEField(event)+"\n"); err != nil { // #nosec G705 -- SSE protocol line with sanitized event name.
        return err
    }
    for _, line := range strings.Split(data, "\n") {
        if _, err := io.WriteString(w, "data: "+line+"\n"); err != nil { // #nosec G705 -- SSE data payload (JSON/text) intentionally streamed to client.
            return err
        }
    }
    _, err := io.WriteString(w, "\n")
    return err
}

// mapErrorCodeToHTTPStatus maps JSON-RPC error codes to appropriate HTTP status codes
// This function provides semantic HTTP status mapping for both standard JSON-RPC codes
// and application-specific error code ranges defined in protocol.go
func mapErrorCodeToHTTPStatus(code int) int {
    // Standard JSON-RPC 2.0 error codes
    switch code {
    case ErrorCodeInvalidRequest: // -32600
        return http.StatusBadRequest
    case ErrorCodeMethodNotFound: // -32601
        return http.StatusNotFound
    case ErrorCodeInvalidParams: // -32602
        return http.StatusBadRequest
    case ErrorCodeInternalError: // -32603
        return http.StatusInternalServerError
    }

    // Application-specific error code ranges
    switch {
    case code >= -1099 && code <= -1000:
        // Authentication errors → HTTP 401 Unauthorized
        return http.StatusUnauthorized
    case code >= -1199 && code <= -1100:
        // Authorization errors → HTTP 403 Forbidden
        return http.StatusForbidden
    case code >= -1299 && code <= -1200:
        // Validation errors → HTTP 422 Unprocessable Entity
        return http.StatusUnprocessableEntity
    case code >= -1399 && code <= -1300:
        // Resource not found errors → HTTP 404 Not Found
        return http.StatusNotFound
    case code >= -1499 && code <= -1400:
        // Conflict errors → HTTP 409 Conflict
        return http.StatusConflict
    case code >= -1599 && code <= -1500:
        // Rate limiting errors → HTTP 429 Too Many Requests
        return http.StatusTooManyRequests
    case code >= -2999 && code <= -2000:
        // Business logic errors → HTTP 400 Bad Request
        return http.StatusBadRequest
    case code >= -3999 && code <= -3000:
        // Configuration and setup errors → HTTP 500 Internal Server Error
        return http.StatusInternalServerError
    default:
        // Unknown error codes: categorize based on range
        if code < -32768 {
            // Very negative codes likely indicate server/system errors
            return http.StatusInternalServerError
        } else if code < 0 {
            // Negative codes generally indicate client-side errors
            return http.StatusBadRequest
        } else {
            // Positive codes are application-specific, assume client error
            return http.StatusBadRequest
        }
    }
}

// writeJSONResponse writes a standard JSON response
// Maps JSON-RPC error codes to appropriate HTTP status codes per MCP specification
func (t *StreamableHTTPTransport) writeJSONResponse(w http.ResponseWriter, response types.MCPResponse) {
    w.Header().Set("Content-Type", "application/json")

    // Determine HTTP status code based on JSON-RPC error codes
    statusCode := http.StatusOK
    if response.Error != nil {
        statusCode = mapErrorCodeToHTTPStatus(response.Error.Code)
    }

    w.WriteHeader(statusCode)
    if err := json.NewEncoder(w).Encode(response); err != nil {
        log.Printf("Failed to encode JSON response: %v", err)
    }
}

// writeErrorResponse writes a JSON-RPC error response
// This helper function creates properly formatted MCP error responses
func (t *StreamableHTTPTransport) writeErrorResponse(w http.ResponseWriter, id interface{}, code int, message, data string) {
    // Create a proper JSON-RPC 2.0 error response
    response := types.MCPResponse{
        JSONRPC: "2.0", // Required JSON-RPC version
        ID:      id,    // Request ID (may be nil for parse errors)
        Error: &types.MCPError{
            Code:    code,    // Standard JSON-RPC error codes
            Message: message, // Human-readable error message
            Data:    data,    // Additional error details
        },
    }
    t.writeJSONResponse(w, response)
}

// ==========================================
// Session Management Functions
// ==========================================
// These functions provide MCP-compliant session management with
// cryptographically secure session IDs and automatic cleanup

// createSession generates a new cryptographically secure session ID
// Sessions are used to maintain state across multiple MCP requests
// Per MCP specification, session IDs must be globally unique and secure
func (t *StreamableHTTPTransport) createSession() string {
    // Generate 16 random bytes for cryptographically secure session ID
    bytes := make([]byte, 16)
    rand.Read(bytes)
    sessionID := hex.EncodeToString(bytes) // Convert to hex string (32 characters)

    // Store session with thread-safe access
    t.sessionsMux.Lock()
    defer t.sessionsMux.Unlock()

    // Create new session record
    t.sessions[sessionID] = &types.Session{
        ID:        sessionID,
        CreatedAt: time.Now(),
        LastSeen:  time.Now(), // Initialize activity timestamp
        Active:    true,       // Mark session as active
    }

    return sessionID
}

// isValidSession checks if a session ID is valid and active
// This validates both session existence and expiration status
func (t *StreamableHTTPTransport) isValidSession(sessionID string) bool {
    // Use read lock for thread-safe session access
    t.sessionsMux.RLock()
    defer t.sessionsMux.RUnlock()

    // Check if session exists and is marked as active
    session, exists := t.sessions[sessionID]
    if !exists || !session.Active {
        return false
    }

    // Check if session has expired based on configured timeout
    if time.Since(session.LastSeen) > t.config.SessionTimeout {
        return false
    }

    return true
}

// updateSessionActivity updates the last seen time for a session
func (t *StreamableHTTPTransport) updateSessionActivity(sessionID string) {
    t.sessionsMux.Lock()
    defer t.sessionsMux.Unlock()

    if session, exists := t.sessions[sessionID]; exists {
        session.LastSeen = time.Now()
    }
}

// cleanupExpiredSessions removes expired sessions periodically
// This background goroutine prevents memory leaks by cleaning up old sessions
// Runs every minute to check for and remove expired sessions
func (t *StreamableHTTPTransport) cleanupExpiredSessions() {
    // Create ticker for periodic cleanup (every minute)
    ticker := time.NewTicker(1 * time.Minute)
    defer ticker.Stop()

    // Run cleanup loop until the transport is shut down
    for range ticker.C {
        // Use write lock since we'll be modifying the sessions map
        t.sessionsMux.Lock()
        now := time.Now()

        // Check each session for expiration
        for id, session := range t.sessions {
            // If session hasn't been active within timeout period, remove it
            if now.Sub(session.LastSeen) > t.config.SessionTimeout {
                delete(t.sessions, id)
                log.Printf("Cleaned up expired session: %s", id)
            }
        }
        t.sessionsMux.Unlock()
    }
}

// generateEventID generates a unique event ID for SSE
// Event IDs are used in Server-Sent Events for message ordering and resumability
func (t *StreamableHTTPTransport) generateEventID() string {
    // Generate 8 random bytes for a unique event ID
    bytes := make([]byte, 8)
    rand.Read(bytes)
    // Return as 16-character hex string
    return hex.EncodeToString(bytes)
}

// ==========================================
// Transport Interface Implementation
// ==========================================
// These methods implement the Transport interface for lifecycle management

// Start starts the HTTP server
// This method blocks until the server shuts down or encounters an error
func (t *StreamableHTTPTransport) Start() error {
    log.Printf("Starting MCP streamable HTTP server on %s", t.server.Addr)
    // ListenAndServe blocks until server shutdown
    return t.server.ListenAndServe()
}

// Stop gracefully shuts down the HTTP server
// Uses context for timeout control and ensures clean shutdown of all connections
func (t *StreamableHTTPTransport) Stop(ctx context.Context) error {
    log.Println("Shutting down MCP streamable HTTP server...")
    // Graceful shutdown with context timeout
    return t.server.Shutdown(ctx)
}

// GetAddr returns the server address
// Useful for testing and configuration verification
func (t *StreamableHTTPTransport) GetAddr() string {
    return t.server.Addr
}
