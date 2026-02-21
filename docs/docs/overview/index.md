# Overview

Welcome to the ContextForge documentation.

This section introduces what ContextForge is, the gateway patterns it supports, and what core features and capabilities it offers out of the box.

---

## What is ContextForge?

**ContextForge** is a production-grade AI gateway that unifies tools, agents, models, and APIs behind a single endpoint. It supports multiple gateway patterns:

- **Tools Gateway** — Federate MCP servers, REST APIs, and gRPC services into one composable tool catalog
- **Agent Gateway** — Route to A2A agents, OpenAI-compatible agents, and Anthropic agents
- **Model Gateway** — LLM proxy with OpenAI API spec, supporting watsonx, OpenAI, Anthropic, Ollama, vLLM, and more
- **API Gateway** — Rate limiting, auth, retries, and reverse proxy for REST services
- **Plugin Extensibility** — 40+ plugins for additional transports, protocols, and integrations
- **Observability** — OpenTelemetry tracing with Phoenix, Jaeger, Zipkin, and other OTLP backends

It also provides protocol enforcement, health monitoring, registry centralization, a visual Admin UI, and audit metadata capture — over HTTP, WebSockets, SSE, StreamableHttp, or stdio.

---

## What's in This Section

| Page | Description |
|------|-------------|
| [Features](features.md) | Breakdown of supported features including federation, transports, and tool wrapping |
| [Admin UI](ui.md) | Screenshots and explanation of the interactive web dashboard |
| [Quick Start](quick_start.md) | Quick Installation and Start up |
