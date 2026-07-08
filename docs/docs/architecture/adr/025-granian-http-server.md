# ADR-0025: Add Granian as Alternative HTTP Server

**Status**: Superseded
**Date**: 2025-12-21 (superseded 2025-07-08)

## Context

Granian was previously added as an alternative HTTP server option alongside Gunicorn+Uvicorn. It provided native backpressure and HTTP/2 support via a Rust-based ASGI server.

## Decision

Granian has been removed from the project. Gunicorn with Uvicorn workers is the sole HTTP server.

## Consequences

- The `granian` pip extra has been removed from `pyproject.toml`
- The `run-granian.sh` script has been deleted
- All `GRANIAN_*` environment variables and `HTTP_SERVER` selection logic have been removed
- Docker, Makefile, Helm chart, and CI configurations no longer reference Granian
