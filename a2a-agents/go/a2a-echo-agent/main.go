// -*- coding: utf-8 -*-
// a2a-echo-agent - lightweight A2A-compliant echo agent (no LLM dependency)
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Implements (A2A v0.3.x):
// - Agent Card: GET /.well-known/agent-card.json (and /.well-known/agent.json alias)
// - JSON-RPC: POST / (message/send, tasks/get, tasks/cancel, etc. via a2a-go server)
// - Health: GET /health
//
// This agent is used by docker-compose load testing to exercise the full pipeline:
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
	"syscall"
	"time"

	"github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"
)

const (
	appVersion = "1.0.0"

	defaultAddr            = "0.0.0.0:9100"
	defaultName            = "a2a-echo-agent"
	defaultProtocolVersion = "0.3.0"

	readHeaderTimeout = 5 * time.Second
	writeTimeout      = 30 * time.Second
	idleTimeout       = 60 * time.Second
	shutdownTimeout   = 10 * time.Second

	maxBodyBytes = 1 << 20 // 1 MiB
)

type echoExecutor struct {
	agentName       string
	fixedResponse   string
	enableSubmitted bool
}

var _ a2asrv.AgentExecutor = (*echoExecutor)(nil)

func (e *echoExecutor) Execute(ctx context.Context, reqCtx *a2asrv.RequestContext, queue eventqueue.Queue) error {
	// For brand-new tasks, emit Submitted -> Working. (Optional but useful for visibility.)
	if e.enableSubmitted && reqCtx.StoredTask == nil {
		ev := a2a.NewStatusUpdateEvent(reqCtx, a2a.TaskStateSubmitted, nil)
		if err := queue.Write(ctx, ev); err != nil {
			return fmt.Errorf("write submitted: %w", err)
		}
	}

	ev := a2a.NewStatusUpdateEvent(reqCtx, a2a.TaskStateWorking, nil)
	if err := queue.Write(ctx, ev); err != nil {
		return fmt.Errorf("write working: %w", err)
	}

	inputText := extractText(reqCtx.Message)
	respText := e.fixedResponse
	if strings.TrimSpace(respText) == "" {
		respText = inputText
	}

	// Primary output as an artifact.
	artEv := a2a.NewArtifactEvent(reqCtx, a2a.TextPart{Text: respText})
	if err := queue.Write(ctx, artEv); err != nil {
		return fmt.Errorf("write artifact: %w", err)
	}

	// Terminal status update.
	msg := a2a.NewMessageForTask(a2a.MessageRoleAgent, reqCtx, a2a.TextPart{Text: respText})
	done := a2a.NewStatusUpdateEvent(reqCtx, a2a.TaskStateCompleted, msg)
	done.Final = true
	if err := queue.Write(ctx, done); err != nil {
		return fmt.Errorf("write completed: %w", err)
	}

	return nil
}

func (e *echoExecutor) Cancel(ctx context.Context, reqCtx *a2asrv.RequestContext, queue eventqueue.Queue) error {
	if reqCtx.StoredTask != nil && reqCtx.StoredTask.Status.State.Terminal() {
		return a2a.ErrTaskNotCancelable
	}

	msg := a2a.NewMessageForTask(a2a.MessageRoleAgent, reqCtx, a2a.TextPart{Text: "task canceled"})
	ev := a2a.NewStatusUpdateEvent(reqCtx, a2a.TaskStateCanceled, msg)
	ev.Final = true
	if err := queue.Write(ctx, ev); err != nil {
		return fmt.Errorf("write canceled: %w", err)
	}
	return nil
}

type agentCardEnvelope struct {
	Kind string `json:"kind"`
	a2a.AgentCard
}

func main() {
	addr := getenv("A2A_ECHO_ADDR", defaultAddr)
	name := getenv("A2A_ECHO_NAME", defaultName)

	protocolVersion := getenv("A2A_ECHO_PROTOCOL_VERSION", defaultProtocolVersion)
	fixedResponse := strings.TrimSpace(os.Getenv("A2A_ECHO_FIXED_RESPONSE"))
	publicURLOverride := strings.TrimSpace(os.Getenv("A2A_ECHO_PUBLIC_URL"))

	logger := log.New(os.Stderr, "", log.LstdFlags)
	logger.Printf("Starting %s (%s) on %s", name, appVersion, addr)

	exec := &echoExecutor{
		agentName:       name,
		fixedResponse:   fixedResponse,
		enableSubmitted: true,
	}

	// A2A server: transport-agnostic handler + JSON-RPC transport.
	handler := a2asrv.NewHandler(exec)
	jsonrpcHandler := a2asrv.NewJSONRPCHandler(handler)

	mux := http.NewServeMux()

	// Root handler: GET is informational, POST is JSON-RPC.
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			writeCORS(w, r)
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

		// Enforce a request size limit.
		writeCORS(w, r)
		r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
		jsonrpcHandler.ServeHTTP(w, r)
	}))

	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":  "healthy",
			"name":    name,
			"version": appVersion,
		})
	})

	// A2A Agent Card (public).
	mux.HandleFunc("/.well-known/agent-card.json", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			writeCORS(w, r)
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		baseURL := publicURLOverride
		if baseURL == "" {
			baseURL = guessBaseURL(r, addr)
		}
		card := buildAgentCard(name, protocolVersion, baseURL)
		writeJSON(w, http.StatusOK, agentCardEnvelope{Kind: "agent-card", AgentCard: card})
	})

	// Compatibility alias.
	mux.HandleFunc("/.well-known/agent.json", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			writeCORS(w, r)
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		baseURL := publicURLOverride
		if baseURL == "" {
			baseURL = guessBaseURL(r, addr)
		}
		card := buildAgentCard(name, protocolVersion, baseURL)
		writeJSON(w, http.StatusOK, agentCardEnvelope{Kind: "agent-card", AgentCard: card})
	})

	// Compatibility endpoint used by some demos.
	mux.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		msg, _ := readLooseMessageText(w, r)
		resp := fixedResponse
		if resp == "" {
			resp = msg
		}
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

	// Graceful shutdown.
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

func buildAgentCard(name, protocolVersion, baseURL string) a2a.AgentCard {
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	url := baseURL + "/"

	return a2a.AgentCard{
		Name:               name,
		Description:        "Lightweight A2A echo agent for docker-compose testing (no LLM dependency)",
		ProtocolVersion:    protocolVersion,
		Version:            appVersion,
		URL:                url,
		PreferredTransport: a2a.TransportProtocolJSONRPC,
		AdditionalInterfaces: []a2a.AgentInterface{
			{Transport: a2a.TransportProtocolJSONRPC, URL: url},
		},
		Capabilities: a2a.AgentCapabilities{
			Streaming:              false,
			PushNotifications:      false,
			StateTransitionHistory: false,
		},
		DefaultInputModes:  []string{"text/plain"},
		DefaultOutputModes: []string{"text/plain"},
		Skills: []a2a.AgentSkill{
			{
				ID:          "echo",
				Name:        "Echo",
				Description: "Echoes input text back as a completed task",
				Tags:        []string{"testing", "echo"},
				Examples:    []string{"Say hello", "Echo this message"},
				InputModes:  []string{"text/plain"},
				OutputModes: []string{"text/plain"},
			},
		},
	}
}

func extractText(msg *a2a.Message) string {
	if msg == nil {
		return ""
	}
	parts := make([]string, 0, len(msg.Parts))
	for _, p := range msg.Parts {
		switch v := p.(type) {
		case a2a.TextPart:
			parts = append(parts, v.Text)
		case *a2a.TextPart:
			parts = append(parts, v.Text)
		default:
			// Ignore non-text parts for the echo result.
		}
	}
	return strings.Join(parts, " ")
}

func readLooseMessageText(w http.ResponseWriter, r *http.Request) (string, error) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	defer r.Body.Close()
	body, err := io.ReadAll(r.Body)
	if err != nil {
		return "", err
	}

	// Try JSON forms first.
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

func writeCORS(w http.ResponseWriter, r *http.Request) {
	_ = r
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type,Authorization,Traceparent")
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	writeCORS(w, nil)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
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
