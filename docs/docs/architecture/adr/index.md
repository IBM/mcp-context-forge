# Architecture Decision Records

This page tracks all significant design decisions made for the MCP Gateway project, using the [ADR](https://adr.github.io/) format.

| ID    | Title                                              | Status    | Section        | Date        |
|-------|----------------------------------------------------|-----------|----------------|-------------|
| 0001  | Adopt **FastAPI** + **Pydantic**                   | Accepted  | Framework      | 2025-02-01  |
| 0002  | Use **Async SQLAlchemy** ORM                       | Accepted  | Persistence    | 2025-02-01  |
| 0003  | Expose Multi-Transport Endpoints                   | Accepted  | Transport      | 2025-02-01  |
| 0004  | Combine JWT & Basic Auth                           | Accepted  | Security       | 2025-02-01  |
| 0005  | Structured JSON Logging                            | Accepted  | Observability  | 2025-02-21  |
| 0006  | Gateway & Tool-Level Rate Limiting                 | Accepted  | Performance    | 2025-02-21  |
| 0007  | Pluggable Cache Backend (memory / Redis / DB)      | Accepted  | Caching        | 2025-02-21  |
| 0008  | Federation & Auto-Discovery via DNS-SD             | Accepted  | Federation     | 2025-02-21  |
| 0009  | Built-in Health Checks & Self-Monitoring           | Accepted  | Operations     | 2025-02-21  |
| 0010  | Observability via Prometheus, Structured Logs      | Accepted  | Observability  | 2025-02-21  |
| 0014  | Security Headers & Environment-Aware CORS Middleware | Accepted  | Security       | 2025-08-17  |
| 0015  | Configurable Well-Known URI Handler               | Accepted  | Security       | 2025-08-17  |

> ✳️ Add new decisions chronologically and link to them from this table.
