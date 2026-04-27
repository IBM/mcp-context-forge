// -*- coding: utf-8 -*-
// a2a-echo-agent - lightweight A2A-compliant echo agent (no LLM dependency)
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Implements:
// - Agent Card: GET /.well-known/agent-card.json (and /.well-known/agent.json alias)
// - Extended card: GET /extendedAgentCard
// - JSON-RPC: POST / (A2A v1 methods with v0.3 compatibility aliases)
// - Health: GET /health
//
// This agent is used by docker-compose testing to exercise the full pipeline:
// gateway -> A2A registry -> invoke -> outbound agent call -> response.

package main

import (
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "os/signal"
    "strings"
    "sync"
    "syscall"
    "time"
)

const (
    appVersion = "1.0.0"

    defaultAddr            = "0.0.0.0:9100"
    defaultName            = "a2a-echo-agent"
    defaultProtocolVersion = "1.0.0"

    readHeaderTimeout = 5 * time.Second
    writeTimeout      = 30 * time.Second
    idleTimeout       = 60 * time.Second
    shutdownTimeout   = 10 * time.Second

    maxBodyBytes  = 1 << 20 // 1 MiB
    maxStoredTasks = 10_000
)

type server struct {
    name            string
    protocolVersion string
    fixedResponse   string

    mu       sync.RWMutex
    tasks    map[string]*storedTask
    taskList []string
}

type storedTask struct {
    ID         string
    ContextID  string
    InputText  string
    OutputText string
    State      string
    CreatedAt  time.Time
    UpdatedAt  time.Time
}

type jsonRPCRequest struct {
    JSONRPC string          `json:"jsonrpc"`
    ID      any             `json:"id,omitempty"`
    Method  string          `json:"method"`
    Params  json.RawMessage `json:"params,omitempty"`
}

type jsonRPCResponse struct {
    JSONRPC string        `json:"jsonrpc"`
    ID      any           `json:"id,omitempty"`
    Result  any           `json:"result,omitempty"`
    Error   *jsonRPCError `json:"error,omitempty"`
}

type jsonRPCError struct {
    Code    int    `json:"code"`
    Message string `json:"message"`
}

type sendMessageParams struct {
    Message map[string]any `json:"message"`
}

type taskLookupParams struct {
    ID string `json:"id"`
}

type listTasksParams struct {
    Status string `json:"status"`
}

func main() {
    addr := getenv("A2A_ECHO_ADDR", defaultAddr)
    name := getenv("A2A_ECHO_NAME", defaultName)
    protocolVersion := getenv("A2A_ECHO_PROTOCOL_VERSION", defaultProtocolVersion)
    fixedResponse := strings.TrimSpace(os.Getenv("A2A_ECHO_FIXED_RESPONSE"))
    publicURLOverride := strings.TrimSpace(os.Getenv("A2A_ECHO_PUBLIC_URL"))

    logger := log.New(os.Stderr, "", log.LstdFlags)
    logger.Printf("Starting %s (%s) on %s with A2A protocol %s", name, appVersion, addr, protocolVersion)

    app := &server{
        name:            name,
        protocolVersion: protocolVersion,
        fixedResponse:   fixedResponse,
        tasks:           make(map[string]*storedTask),
    }

    mux := http.NewServeMux()
    mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.Method == http.MethodOptions {
            writeCORS(w)
            w.WriteHeader(http.StatusNoContent)
            return
        }
        if r.Method == http.MethodGet {
            writeJSON(w, http.StatusOK, map[string]any{
                "name":             name,
                "version":          appVersion,
                "protocol_version": protocolVersion,
                "status":           "running",
            })
            return
        }
        if r.Method != http.MethodPost {
            w.WriteHeader(http.StatusMethodNotAllowed)
            return
        }
        app.handleJSONRPC(w, r)
    }))
    mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
        writeJSON(w, http.StatusOK, map[string]any{
            "status":  "healthy",
            "name":    name,
            "version": appVersion,
        })
    })
    mux.HandleFunc("/.well-known/agent-card.json", func(w http.ResponseWriter, r *http.Request) {
        app.handleAgentCard(w, r, publicURLOverride)
    })
    mux.HandleFunc("/.well-known/agent.json", func(w http.ResponseWriter, r *http.Request) {
        app.handleAgentCard(w, r, publicURLOverride)
    })
    mux.HandleFunc("/extendedAgentCard", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodGet {
            w.WriteHeader(http.StatusMethodNotAllowed)
            return
        }
        baseURL := publicURLOverride
        if baseURL == "" {
            baseURL = guessBaseURL(r, addr)
        }
        writeJSON(w, http.StatusOK, app.buildExtendedAgentCard(baseURL, app.useV1Protocol("", r.Header.Get("A2A-Version"))))
    })
    mux.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodPost {
            w.WriteHeader(http.StatusMethodNotAllowed)
            return
        }
        msg, _ := readLooseMessageText(w, r)
        resp := app.echoText(msg)
        writeJSON(w, http.StatusOK, map[string]any{
            "response":   resp,
            "status":     "success",
            "agent_name": name,
            "timestamp":  time.Now().UTC().Format(time.RFC3339Nano),
        })
    })

    srv := &http.Server{
        Addr:              addr,
        Handler:           mux,
        ReadHeaderTimeout: readHeaderTimeout,
        WriteTimeout:      writeTimeout,
        IdleTimeout:       idleTimeout,
    }

    shutdownCh := make(chan os.Signal, 1)
    signal.Notify(shutdownCh, syscall.SIGINT, syscall.SIGTERM)
    go func() {
        <-shutdownCh
        logger.Printf("Shutting down %s...", name)
        ctx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
        defer cancel()
        _ = srv.Shutdown(ctx)
    }()

    if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
        logger.Fatalf("server error: %v", err)
    }
}

func (s *server) handleJSONRPC(w http.ResponseWriter, r *http.Request) {
    writeCORS(w)
    r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
    defer r.Body.Close()

    body, err := io.ReadAll(r.Body)
    if err != nil {
        writeJSONRPC(w, http.StatusBadRequest, jsonRPCResponse{
            JSONRPC: "2.0",
            Error:   &jsonRPCError{Code: -32700, Message: "failed to read request body"},
        })
        return
    }

    var req jsonRPCRequest
    if err := json.Unmarshal(body, &req); err != nil {
        writeJSONRPC(w, http.StatusBadRequest, jsonRPCResponse{
            JSONRPC: "2.0",
            Error:   &jsonRPCError{Code: -32700, Message: "invalid JSON-RPC request"},
        })
        return
    }
    if req.JSONRPC == "" {
        req.JSONRPC = "2.0"
    }
    if req.Method == "" {
        writeJSONRPC(w, http.StatusBadRequest, jsonRPCResponse{
            JSONRPC: req.JSONRPC,
            ID:      req.ID,
            Error:   &jsonRPCError{Code: -32600, Message: "missing method"},
        })
        return
    }

    useV1 := s.useV1Protocol(req.Method, r.Header.Get("A2A-Version"))

    switch req.Method {
    case "SendMessage", "message/send", "SendStreamingMessage", "message/stream":
        result, rpcErr := s.handleSendMessage(req.Params, useV1)
        writeJSONRPCResult(w, req, result, rpcErr)
    case "GetTask", "tasks/get":
        result, rpcErr := s.handleGetTask(req.Params, useV1)
        writeJSONRPCResult(w, req, result, rpcErr)
    case "ListTasks", "tasks/list":
        result, rpcErr := s.handleListTasks(req.Params, useV1)
        writeJSONRPCResult(w, req, result, rpcErr)
    case "CancelTask", "tasks/cancel":
        result, rpcErr := s.handleCancelTask(req.Params, useV1)
        writeJSONRPCResult(w, req, result, rpcErr)
    case "GetExtendedAgentCard", "agent/getExtendedCard", "agent/getAuthenticatedExtendedCard":
        writeJSONRPCResult(w, req, s.buildExtendedAgentCard(guessBaseURL(r, defaultAddr), useV1), nil)
    default:
        writeJSONRPCResult(w, req, nil, &jsonRPCError{Code: -32601, Message: fmt.Sprintf("method not supported: %s", req.Method)})
    }
}

func (s *server) handleAgentCard(w http.ResponseWriter, r *http.Request, publicURLOverride string) {
    if r.Method == http.MethodOptions {
        writeCORS(w)
        w.WriteHeader(http.StatusNoContent)
        return
    }
    if r.Method != http.MethodGet {
        w.WriteHeader(http.StatusMethodNotAllowed)
        return
    }

    baseURL := publicURLOverride
    if baseURL == "" {
        baseURL = guessBaseURL(r, defaultAddr)
    }
    useV1 := s.useV1Protocol("", r.Header.Get("A2A-Version"))
    card := s.buildAgentCard(baseURL, useV1)
    if useV1 {
        writeJSON(w, http.StatusOK, card)
        return
    }

    legacy := card
    legacy["kind"] = "agent-card"
    writeJSON(w, http.StatusOK, legacy)
}

func (s *server) handleSendMessage(raw json.RawMessage, useV1 bool) (any, *jsonRPCError) {
    var params sendMessageParams
    if len(raw) > 0 {
        if err := json.Unmarshal(raw, &params); err != nil {
            return nil, &jsonRPCError{Code: -32602, Message: "invalid SendMessage params"}
        }
    }

    inputText := extractMessageText(params.Message)
    if inputText == "" {
        inputText = "hello"
    }
    outputText := s.echoText(inputText)

    now := time.Now().UTC()
    task := &storedTask{
        ID:         fmt.Sprintf("task-%d", now.UnixNano()),
        ContextID:  fmt.Sprintf("ctx-%d", now.UnixNano()),
        InputText:  inputText,
        OutputText: outputText,
        State:      "completed",
        CreatedAt:  now,
        UpdatedAt:  now,
    }

    s.mu.Lock()
    s.tasks[task.ID] = task
    s.taskList = append(s.taskList, task.ID)
    for len(s.taskList) > maxStoredTasks {
        delete(s.tasks, s.taskList[0])
        s.taskList = s.taskList[1:]
    }
    s.mu.Unlock()

    return s.renderTask(task, useV1), nil
}

func (s *server) handleGetTask(raw json.RawMessage, useV1 bool) (any, *jsonRPCError) {
    var params taskLookupParams
    if len(raw) > 0 {
        if err := json.Unmarshal(raw, &params); err != nil {
            return nil, &jsonRPCError{Code: -32602, Message: "invalid GetTask params"}
        }
    }
    task := s.lookupTask(params.ID)
    if task == nil {
        return nil, &jsonRPCError{Code: -32004, Message: "task not found"}
    }
    return s.renderTask(task, useV1), nil
}

func (s *server) handleListTasks(raw json.RawMessage, useV1 bool) (any, *jsonRPCError) {
    params := listTasksParams{}
    if len(raw) > 0 {
        if err := json.Unmarshal(raw, &params); err != nil {
            return nil, &jsonRPCError{Code: -32602, Message: "invalid ListTasks params"}
        }
    }
    wantState := normalizeState(strings.TrimSpace(params.Status))

    s.mu.RLock()
    rendered := make([]any, 0, len(s.taskList))
    for _, id := range s.taskList {
        task := s.tasks[id]
        if task == nil {
            continue
        }
        if wantState != "" && normalizeState(task.State) != wantState {
            continue
        }
        rendered = append(rendered, s.renderTask(task, useV1))
    }
    s.mu.RUnlock()

    return map[string]any{"tasks": rendered}, nil
}

func (s *server) handleCancelTask(raw json.RawMessage, useV1 bool) (any, *jsonRPCError) {
    var params taskLookupParams
    if len(raw) > 0 {
        if err := json.Unmarshal(raw, &params); err != nil {
            return nil, &jsonRPCError{Code: -32602, Message: "invalid CancelTask params"}
        }
    }

    s.mu.Lock()
    defer s.mu.Unlock()

    task := s.tasks[params.ID]
    if task == nil {
        return nil, &jsonRPCError{Code: -32004, Message: "task not found"}
    }
    task.State = "canceled"
    task.UpdatedAt = time.Now().UTC()
    return s.renderTask(task, useV1), nil
}

func (s *server) lookupTask(id string) *storedTask {
    s.mu.RLock()
    defer s.mu.RUnlock()
    if task := s.tasks[id]; task != nil {
        clone := *task
        return &clone
    }
    return nil
}

func (s *server) renderTask(task *storedTask, useV1 bool) map[string]any {
    responseMessage := buildMessage(task.ID+"-response", "agent", task.OutputText, useV1)
    artifact := buildArtifact(task.ID+"-artifact", task.OutputText, useV1)
    state := renderState(task.State, useV1)

    rendered := map[string]any{
        "id":        task.ID,
        "contextId": task.ContextID,
        "status":    map[string]any{"state": state, "message": responseMessage, "timestamp": task.UpdatedAt.Format(time.RFC3339Nano)},
        "artifacts": []any{artifact},
        "createdAt": task.CreatedAt.Format(time.RFC3339Nano),
        "updatedAt": task.UpdatedAt.Format(time.RFC3339Nano),
    }
    if !useV1 {
        rendered["kind"] = "task"
    }
    return rendered
}

func (s *server) buildAgentCard(baseURL string, useV1 bool) map[string]any {
    url := strings.TrimRight(strings.TrimSpace(baseURL), "/") + "/"
    skill := map[string]any{
        "id":          "echo",
        "name":        "Echo",
        "description": "Echoes input text back as a completed task",
        "tags":        []string{"testing", "echo"},
        "examples":    []string{"Say hello", "Echo this message"},
        "inputModes":  []string{"text"},
        "outputModes": []string{"text"},
    }
    capabilities := map[string]any{
        "streaming":              false,
        "pushNotifications":      false,
        "stateTransitionHistory": false,
    }

    if useV1 {
        return map[string]any{
            "name":                              s.name,
            "description":                       "Lightweight A2A echo agent for docker-compose testing (no LLM dependency)",
            "url":                               url,
            "version":                           appVersion,
            "protocolVersion":                   s.protocolVersion,
            "defaultInputModes":                 []string{"text"},
            "defaultOutputModes":                []string{"text"},
            "capabilities":                      capabilities,
            "skills":                            []any{skill},
            "supportsAuthenticatedExtendedCard": false,
            "supportedInterfaces": []any{
                map[string]any{
                    "transport": "JSONRPC",
                    "url":       url,
                },
            },
            "securitySchemes":      map[string]any{},
            "securityRequirements": []any{},
        }
    }

    return map[string]any{
        "name":                              s.name,
        "description":                       "Lightweight A2A echo agent for docker-compose testing (no LLM dependency)",
        "url":                               url,
        "version":                           appVersion,
        "protocolVersion":                   s.protocolVersion,
        "preferredTransport":                "JSONRPC",
        "additionalInterfaces":              []any{map[string]any{"transport": "JSONRPC", "url": url}},
        "defaultInputModes":                 []string{"text"},
        "defaultOutputModes":                []string{"text"},
        "capabilities":                      capabilities,
        "skills":                            []any{skill},
        "supportsAuthenticatedExtendedCard": false,
    }
}

func (s *server) buildExtendedAgentCard(baseURL string, useV1 bool) map[string]any {
    card := s.buildAgentCard(baseURL, useV1)
    card["documentationUrl"] = "https://a2a-protocol.org/latest/specification/"
    card["provider"] = map[string]any{"organization": "ContextForge"}
    return card
}

func (s *server) echoText(input string) string {
    if strings.TrimSpace(s.fixedResponse) != "" {
        return s.fixedResponse
    }
    return input
}

func (s *server) useV1Protocol(method, headerVersion string) bool {
    switch method {
    case "message/send", "message/stream", "tasks/get", "tasks/list", "tasks/cancel", "tasks/resubscribe", "agent/getExtendedCard", "agent/getAuthenticatedExtendedCard":
        return false
    case "SendMessage", "SendStreamingMessage", "GetTask", "ListTasks", "CancelTask", "SubscribeToTask", "GetExtendedAgentCard":
        return true
    }
    if isV1Version(headerVersion) {
        return true
    }
    return isV1Version(s.protocolVersion)
}

func buildMessage(messageID, role, text string, useV1 bool) map[string]any {
    if useV1 {
        return map[string]any{
            "messageId": messageID,
            "role":      renderRole(role, true),
            "parts":     []any{map[string]any{"text": text}},
        }
    }
    return map[string]any{
        "kind":      "message",
        "messageId": messageID,
        "role":      renderRole(role, false),
        "parts":     []any{map[string]any{"kind": "text", "text": text}},
    }
}

func buildArtifact(artifactID, text string, useV1 bool) map[string]any {
    if useV1 {
        return map[string]any{
            "artifactId":  artifactID,
            "name":        "echo",
            "description": "Echo response",
            "parts":       []any{map[string]any{"text": text}},
        }
    }
    return map[string]any{
        "kind":        "artifact",
        "artifactId":  artifactID,
        "name":        "echo",
        "description": "Echo response",
        "parts":       []any{map[string]any{"kind": "text", "text": text}},
    }
}

func extractMessageText(message map[string]any) string {
    if len(message) == 0 {
        return ""
    }

    if parts, ok := message["parts"].([]any); ok {
        texts := make([]string, 0, len(parts))
        for _, part := range parts {
            partMap, ok := part.(map[string]any)
            if !ok {
                continue
            }
            if text, ok := partMap["text"].(string); ok && strings.TrimSpace(text) != "" {
                texts = append(texts, strings.TrimSpace(text))
            }
        }
        if len(texts) > 0 {
            return strings.Join(texts, " ")
        }
    }

    for _, key := range []string{"text", "query", "content"} {
        if value, ok := message[key]; ok {
            return strings.TrimSpace(fmt.Sprint(value))
        }
    }
    return ""
}

func normalizeState(state string) string {
    normalized := strings.TrimSpace(strings.ToLower(state))
    normalized = strings.TrimPrefix(normalized, "task_state_")
    normalized = strings.ReplaceAll(normalized, "-", "_")
    return normalized
}

func renderState(state string, useV1 bool) string {
    normalized := normalizeState(state)
    if !useV1 {
        return normalized
    }
    switch normalized {
    case "submitted":
        return "TASK_STATE_SUBMITTED"
    case "working":
        return "TASK_STATE_WORKING"
    case "input_required":
        return "TASK_STATE_INPUT_REQUIRED"
    case "canceled", "cancelled":
        return "TASK_STATE_CANCELED"
    case "failed":
        return "TASK_STATE_FAILED"
    case "auth_required":
        return "TASK_STATE_AUTH_REQUIRED"
    case "rejected":
        return "TASK_STATE_REJECTED"
    default:
        return "TASK_STATE_COMPLETED"
    }
}

func renderRole(role string, useV1 bool) string {
    switch strings.ToLower(strings.TrimSpace(role)) {
    case "system", "role_system":
        if useV1 {
            return "ROLE_SYSTEM"
        }
        return "system"
    case "agent", "role_agent":
        if useV1 {
            return "ROLE_AGENT"
        }
        return "agent"
    default:
        if useV1 {
            return "ROLE_USER"
        }
        return "user"
    }
}

func readLooseMessageText(w http.ResponseWriter, r *http.Request) (string, error) {
    r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
    defer r.Body.Close()
    body, err := io.ReadAll(r.Body)
    if err != nil {
        return "", err
    }

    var s string
    if err := json.Unmarshal(body, &s); err == nil {
        return strings.TrimSpace(s), nil
    }
    var obj map[string]any
    if err := json.Unmarshal(body, &obj); err == nil {
        for _, k := range []string{"message", "text", "query", "content"} {
            if v, ok := obj[k]; ok {
                return strings.TrimSpace(fmt.Sprint(v)), nil
            }
        }
    }

    return strings.TrimSpace(string(body)), nil
}

func writeCORS(w http.ResponseWriter) {
    w.Header().Set("Access-Control-Allow-Origin", "*")
    w.Header().Set("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    w.Header().Set("Access-Control-Allow-Headers", "Accept,A2A-Version,Authorization,Content-Type,Traceparent")
}

func writeJSON(w http.ResponseWriter, status int, v any) {
    writeCORS(w)
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    enc := json.NewEncoder(w)
    enc.SetEscapeHTML(false)
    _ = enc.Encode(v)
}

func writeJSONRPC(w http.ResponseWriter, status int, response jsonRPCResponse) {
    writeCORS(w)
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    enc := json.NewEncoder(w)
    enc.SetEscapeHTML(false)
    _ = enc.Encode(response)
}

func writeJSONRPCResult(w http.ResponseWriter, req jsonRPCRequest, result any, rpcErr *jsonRPCError) {
    response := jsonRPCResponse{
        JSONRPC: req.JSONRPC,
        ID:      req.ID,
        Result:  result,
        Error:   rpcErr,
    }
    status := http.StatusOK
    if rpcErr != nil && rpcErr.Code == -32700 {
        status = http.StatusBadRequest
    }
    writeJSONRPC(w, status, response)
}

func getenv(key, def string) string {
    v := strings.TrimSpace(os.Getenv(key))
    if v == "" {
        return def
    }
    return v
}

func guessBaseURL(r *http.Request, fallbackAddr string) string {
    if r == nil {
        return "http://" + fallbackAddr
    }
    scheme := "http"
    if r.TLS != nil {
        scheme = "https"
    }
    host := strings.TrimSpace(r.Host)
    if host == "" {
        host = fallbackAddr
    }
    return fmt.Sprintf("%s://%s", scheme, host)
}

func isV1Version(version string) bool {
    normalized := strings.TrimSpace(version)
    if normalized == "" {
        return true
    }
    parts := strings.Split(normalized, ".")
    if len(parts) == 0 {
        return true
    }
    return parts[0] != "0"
}
