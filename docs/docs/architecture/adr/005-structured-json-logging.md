# ADR-0005: Structured JSON Logging

- *Status:* Implemented
- *Date:* 2025-01-09
- *Deciders:* Core Engineering Team

## Context

The gateway must emit logs that:

- Are machine-readable and parseable by tools like ELK, Loki, or Datadog
- Include rich context (e.g., request ID, auth user, duration)
- Can be viewed in plaintext locally and JSON in production

Our configuration supports:

- `LOG_FORMAT`: `json` or `text` (console format only)
- `LOG_LEVEL`: standard Python levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
- `LOG_TO_FILE`: enable file logging (default: `false` - stdout/stderr only)
- `LOG_FILE`: log filename when file logging is enabled (default: `null`)
- `LOG_FOLDER`: directory for log files when enabled (default: `null`)
- `LOG_FILEMODE`: file write mode (default: `a+` for append)
- `LOG_ROTATION_ENABLED`: enable automatic log rotation (default: `false`)
- `LOG_MAX_SIZE_MB`: maximum file size before rotation in MB (default: `1`)
- `LOG_BACKUP_COUNT`: number of backup files to keep (default: `5`)

Logs are initialized at startup via centralized `LoggingService`. By default, logs go only to stdout/stderr. File logging with dual-format output is optional via `LOG_TO_FILE=true`.

## Decision

Use the Python standard `logging` module with centralized `LoggingService`:

- **JSON formatter** for file logs using `python-json-logger` library
- **Text formatter** for console logs for human readability
- **Dual output**: JSON to files, text to console
- **Optional rotating file handler** for automatic log management (configurable)
- **Centralized service** integrated across all 22+ modules
- Global setup at app startup with lazy handler initialization

## Consequences

- 📋 **Structured JSON logs** suitable for production observability pipelines (ELK, Datadog, etc.)
- ⚙️ **Dual format support**: JSON files for machines, text console for humans
- 🔄 **Optional log rotation** prevents disk space issues when enabled
- 🧪 **Development-friendly** with human-readable console output
- 📁 **Organized storage** with configurable log directories and retention
- 🧱 **Minimal dependencies**: Uses standard library + `python-json-logger`
- 🎯 **Consistent logging** across all application modules

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **loguru** | Elegant syntax, but non-standard; poor compatibility with Python ecosystem. |
| **structlog** | Adds context pipeline complexity; not needed for current log volume. |
| **External sidecar (e.g. Fluent Bit)** | Useful downstream but doesn't solve app-side structure. |
| **Raw print() statements** | Unstructured, difficult to manage at scale. |

## Status

**✅ Implemented** - Structured logging is fully implemented in `LoggingService` with:

- Centralized logging service integrated across all modules
- Dual-format output (JSON to files, text to console)
- HTTP access log capture (uvicorn.access and uvicorn.error loggers)
- Optional log rotation with configurable size limits and retention
- Environment variable configuration support
- Production-ready with proper error handling and lazy initialization

**Files Modified**: 22 modules updated to use `LoggingService`
**Dependencies Added**: `python-json-logger>=2.0.0`
**Configuration**: Via `LOG_LEVEL`, `LOG_FORMAT`, `LOG_TO_FILE`, `LOG_FILE`, `LOG_FOLDER`, `LOG_FILEMODE`, `LOG_ROTATION_ENABLED`, `LOG_MAX_SIZE_MB`, `LOG_BACKUP_COUNT`
