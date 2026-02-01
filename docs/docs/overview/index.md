# Overview

Welcome to the MCP Gateway documentation.

This section introduces what the Gateway is, how it fits into the MCP ecosystem, and what core features and capabilities it offers out of the box.

---

## What is MCP Gateway?

**MCP Gateway** is an orchestration and federation layer for the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). It provides:

- A unified entrypoint for tools, resources, prompts, and agents
- Federation of multiple MCP servers into one composable catalog
- Protocol enforcement, health monitoring, and registry centralization
- A visual Admin UI to manage everything in real time
- **Audit metadata capture** (creator, modifier, source) for core registry entities
- **Doctest coverage for key modules** (see `development/doctest-coverage.md`)

Whether you're integrating REST APIs, local functions, or full LLM agents, MCP Gateway standardizes access and transport - over HTTP, WebSockets, SSE, StreamableHttp or stdio.

---

## What's in This Section

| Page | Description |
|------|-------------|
| [Features](features.md) | Breakdown of supported features including federation, transports, and tool wrapping |
| [Admin UI](ui.md) | Screenshots and explanation of the interactive web dashboard |
| [Quick Start](quick_start.md) | Quick Installation and Start up |
