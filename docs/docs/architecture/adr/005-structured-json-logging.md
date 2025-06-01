# ADR-0005: Structured JSON Logging

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

The gateway must emit logs that:

- Are machine-readable and parseable by tools like ELK, Loki, or Datadog
- Include rich context (e.g., request ID, auth user, duration)
- Can be viewed in plaintext locally and JSON in production

Our configuration supports:

- `LOG_FORMAT`: `json` or `plain`
- `LOG_LEVEL`: standard Python levels
- `LOG_FILE`: optional log file destination

Logs are initialized at startup via `LoggingService`.

## Decision

Use the Python standard `logging` module with:

- A **custom JSON formatter** for structured logs (e.g. `{"level": "INFO", "msg": ..., "request_id": ...}`)
- **Plain text output** when `LOG_FORMAT=plain`
- Per-request context via filters or middleware
- Global setup at app startup to avoid late binding issues

## Consequences

- 📋 Easily parsed logs suitable for production observability pipelines
- ⚙️ Compatible with `stdout`, file, or syslog targets
- 🧪 Local development uses plain logs for readability
- 🧱 Minimal dependency footprint (no third-party logging libraries)

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **loguru** | Elegant syntax, but non-standard; poor compatibility with Python ecosystem. |
| **structlog** | Adds context pipeline complexity; not needed for current log volume. |
| **External sidecar (e.g. Fluent Bit)** | Useful downstream but doesn't solve app-side structure. |
| **Raw print() statements** | Unstructured, difficult to manage at scale. |

## Status

Structured logging is implemented in `LoggingService`, configurable via environment variables.
