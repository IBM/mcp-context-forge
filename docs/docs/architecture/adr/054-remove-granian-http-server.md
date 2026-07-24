# ADR-0054: Remove Granian HTTP Server

- *Status:* Accepted
- *Date:* 2026-07-22
- *Deciders:* Core Engineering Team
- *Supersedes:* ADR-0025

## Context

ADR-0025 added Granian, a Rust-based ASGI server, as an alternative HTTP server option alongside Gunicorn with Uvicorn workers. In practice, maintaining two production server stacks has proven costly:

- **Dual maintenance burden:** Every deployment surface (Makefile targets, Containerfiles, docker-compose files, Helm chart values, CI workflows, and documentation) had to carry parallel Gunicorn and Granian configuration paths.
- **No clear production use cases:** Gunicorn + Uvicorn is the established, well-tested production server and the configuration actually exercised in deployments. Granian's differentiating features (native HTTP/2, native backpressure) were not driving adoption.
- **Configuration complexity:** The `HTTP_SERVER` selector and `GRANIAN_*` environment variables added cognitive overhead and documentation surface area without commensurate benefit.

## Decision

Remove Granian as an HTTP server option. **Gunicorn with Uvicorn workers is the sole supported HTTP server.**

This change removes:

- The `granian` pip extra from `pyproject.toml` (and from `uv.lock`)
- The `run-granian.sh` startup script
- The `HTTP_SERVER` server-selection environment variable and all `GRANIAN_*` environment variables
- Granian references from the Makefile (`serve-granian*` targets), Containerfiles, `docker-entrypoint.sh`, docker-compose files, Helm chart, and CI workflows
- Granian sections from deployment and performance documentation

## Consequences

### Positive

- Single, well-tested server stack reduces maintenance and review burden
- Simpler deployment documentation and configuration surface
- Container images no longer install Granian, slightly reducing image size and supply-chain surface

### Negative

- Users who explicitly opted into Granian via `HTTP_SERVER=granian` must migrate to the default Gunicorn + Uvicorn stack
- Native HTTP/2 and native backpressure at the HTTP server layer are no longer available; HTTP/2 requires a reverse proxy (as it did with Gunicorn previously), and overload protection must be handled at the proxy or infrastructure layer

### Neutral

- No changes are required for existing Gunicorn deployments, which are unaffected
- ADR-0025 is retained for historical record with status *Superseded by ADR-0054*

## References

- GitHub Issue: #5556
- Superseded ADR: [ADR-0025: Add Granian as Alternative HTTP Server](025-granian-http-server.md)
- Related ADR: [ADR-0024: Adopt uvicorn[standard] for Enhanced Server Performance](024-uvicorn-standard-extras.md)
