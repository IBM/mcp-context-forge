# Architecture Decision Records

This page tracks all significant design decisions made for the MCP Gateway project, using the [ADR](https://adr.github.io/) format.

| ID    | Title                                              | Status    | Section        | Date        |
|-------|----------------------------------------------------|-----------|----------------|-------------|
| 0001  | Adopt **FastAPI** + **Pydantic V2** (Rust-core)   | Accepted  | Framework      | 2025-02-01  |
| 0002  | Use **Async SQLAlchemy** ORM with Connection Pooling | Accepted  | Persistence    | 2025-02-01  |
| 0003  | Expose Multi-Transport Endpoints                   | Accepted  | Transport      | 2025-02-01  |
| 0004  | Combine JWT & Basic Auth                           | Accepted  | Security       | 2025-02-01  |
| 0005  | Structured JSON Logging                            | Accepted  | Observability  | 2025-02-21  |
| 0005b | VS Code Dev Container Support                      | Accepted  | Development    | 2025-02-21  |
| 0006  | Gateway & Tool-Level Rate Limiting                 | Accepted  | Performance    | 2025-02-21  |
| 0007  | Pluggable Cache Backend (memory / Redis Cluster / DB) | Accepted  | Caching        | 2025-02-21  |
| 0008  | Federation & Auto-Discovery via DNS-SD             | Accepted  | Federation     | 2025-02-21  |
| 0009  | Built-in Health Checks & Self-Monitoring           | Accepted  | Operations     | 2025-02-21  |
| 0010  | Observability via Prometheus, Structured Logs      | Accepted  | Observability  | 2025-02-21  |
| 0011  | Namespaced Tool Federation                         | Accepted  | Federation     | 2025-03-01  |
| 0012  | Drop-down UI Tool Selection                        | Accepted  | User Interface | 2025-03-01  |
| 0013  | APIs for Server Connection Strings                 | Accepted  | API Design     | 2025-03-01  |
| 0014  | Security Headers & Environment-Aware CORS Middleware | Accepted  | Security       | 2025-08-17  |
| 0015  | Configurable Well-Known URI Handler                | Accepted  | Security       | 2025-08-17  |
| 0016  | Plugin Framework & AI Middleware                   | Accepted  | Extensibility  | 2025-08-17  |
| 0017  | Adopt **orjson** for High-Performance JSON         | Accepted  | Performance    | 2025-10-27  |
| 0018  | Built-in Response Compression (Brotli/Zstd/GZip)   | Accepted  | Performance    | 2025-10-27  |
| 0019  | Modular Architecture Split (14 Independent Modules) | Accepted  | Architecture   | 2025-10-27  |
| 0020  | Multi-Format Packaging Strategy                    | Accepted  | Distribution   | 2025-10-27  |
| 0021  | Built-in Proxy Capabilities vs Service Mesh        | Accepted  | Architecture   | 2025-10-27  |
| 0022  | Elicitation Passthrough Implementation             | Accepted  | MCP Protocol   | 2025-10-26  |
| 0023  | One-Time Authentication Servers                    | Accepted  | Security       | 2025-10-27  |
| 0024  | Adopt **uvicorn[standard]** for Enhanced Server Performance | Accepted | Performance | 2025-12-21 |
| 0025  | Adopt **Granian** as Alternative HTTP Server | Accepted | Performance | 2025-12-21 |
| 0026  | Add **Hiredis** as Default Redis Parser | Accepted | Performance | 2025-12-21 |
| 0027  | Migrate from **Psycopg2** to **Psycopg3** | Accepted | Database | 2025-01-15 |
| 0028  | Authentication Data Caching | Accepted | Performance | 2025-01-15 |
| 0029  | Registry and Admin Stats Caching | Accepted | Performance | 2025-01-15 |

> ✳️ Add new decisions chronologically and link to them from this table.
