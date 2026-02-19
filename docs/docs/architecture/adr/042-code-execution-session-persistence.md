# ADR-0042: Code Execution Session Persistence for Multi-Worker Deployments

- **Status:** Accepted
- **Date:** 2026-02-19
- **Deciders:** ContextForge Core Maintainers
- **Technical Story:** [#2976](https://github.com/IBM/mcp-context-forge/pull/2976)

## Context

ADR-0041 introduced `code_execution` server type with a virtual tool filesystem and sandbox execution. Sessions are keyed by `(server_id, user_email, language)` and stored in an in-memory `_sessions` dict on a module-level `CodeExecutionService` singleton.

In production, the gateway runs behind nginx with multiple containers (3 replicas), each running gunicorn with 24 UvicornWorker processes — totaling **72 independent Python processes**. Each process has its own `_sessions` dict and each container has its own Docker filesystem.

### Problem

1. **Session dict is process-local.** Worker A creates a session; worker B receives the next request, finds an empty dict, creates a new session with a different random UUID.

2. **Filesystem is container-local.** Even if two workers in the same container share a session, workers in different containers write to different `/tmp/mcpgateway_code_execution/` trees.

3. **Session directories use random UUIDs.** Path `{base}/{server_id}/{user_slug}/{uuid4().hex}/` is unpredictable — no two processes can derive the same path independently.

**Measured impact (20 consecutive requests from one client):**

| Metric | Value |
|--------|-------|
| Unique sessions created | 17 (of 20 requests) |
| Session reuse rate | 15% |
| Orphan session directories | 44 across 3 containers |
| Orphan files | 1,415 (9.8 MB) |
| DB queries wasted | ~44 × (tools + skills resolve) |

This renders all cross-request operations broken: `fs_write` → `fs_read`, `shell_exec` write → `fs_browse`, and any multi-turn code execution workflow.

### Existing Pattern

ADR-038 solved the equivalent problem for MCP transport sessions using Redis-based ownership and Pub/Sub forwarding. Code execution sessions have different requirements (shared filesystem access rather than request routing) but should follow the same Redis-coordinated approach.

## Decision

Implement three complementary changes to make code execution sessions work across all workers and containers:

### 1) Deterministic Session Directory Paths

Replace random UUID session paths with a deterministic hash derived from the session key:

```python
# Before (random, unpredictable)
session_id = uuid.uuid4().hex
root = base_dir / server_id / slugify(user_email) / session_id

# After (deterministic, any worker resolves identically)
key_material = f"{server_id}:{user_email}:{language}"
session_id = hashlib.sha256(key_material.encode()).hexdigest()[:24]
root = base_dir / server_id / slugify(user_email) / session_id
```

Any of the 72 workers receiving a request for the same `(server_id, user_email, language)` tuple derives the same filesystem path.

### 2) Redis Session Registry

Store session metadata in Redis so all workers share a consistent view of session state:

```
Key:   mcpgw:code_exec_session:{server_id}:{user_slug}:{language}
Value: JSON { session_id, content_hash, last_used_at, created_at }
TTL:   code_execution_session_ttl_seconds (default 900s)
```

This provides:
- **Content hash caching**: Workers skip VFS regeneration when tools/skills haven't changed
- **TTL-based expiry**: Redis EXPIRE handles session cleanup without a background sweeper
- **Atomic creation**: Redis SET with NX flag prevents race conditions

When Redis is unavailable, the service falls back to in-memory session management (single-worker behavior) for graceful degradation.

### 3) Shared Docker Volume

Mount a named volume for `CODE_EXECUTION_BASE_DIR` across all gateway containers:

```yaml
volumes:
  code_exec_data:

services:
  gateway:
    volumes:
      - code_exec_data:/tmp/mcpgateway_code_execution
```

All containers read and write the same filesystem tree. Combined with deterministic paths, any worker on any container accesses the same session directory.

### 4) File-Based Locking for Initialization

Use `fcntl.flock()` on a session-level lock file to serialize concurrent initialization:

```python
lock_path = root / ".session.lock"
with open(lock_path, "w") as lock_fd:
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    # Check if another worker already initialized
    # If not, create directories, generate stubs, write metadata
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
```

This prevents two workers from simultaneously regenerating tool stubs for the same session.

## Consequences

### Positive

- Cross-request session persistence works across all 72 workers and 3 containers
- Eliminates orphan session directory proliferation (1 directory per unique user/server/language, not per request)
- Reduces redundant DB queries for mounted tools/skills (content hash cached in Redis)
- Follows the established Redis coordination pattern from ADR-038
- Graceful degradation: falls back to in-memory when Redis is unavailable

### Negative

- Adds Redis dependency for session coordination (Redis already required for ADR-038)
- Shared volume adds a Docker volume dependency (must be configured in compose/Helm)
- File-based locking adds complexity for concurrent initialization
- Deterministic paths mean session data is not automatically isolated between restarts (TTL cleanup handles this)

### Risks and Mitigations

- **Risk:** Stale session directories accumulate if Redis TTL expires but files remain
  - **Mitigation:** Periodic cleanup of directories older than 2× TTL via existing session reaper
- **Risk:** File lock contention under high concurrency
  - **Mitigation:** Lock is held only during initialization (~10-50ms); subsequent requests skip locking when session exists
- **Risk:** Shared volume introduces a single point of failure
  - **Mitigation:** Use a resilient volume driver (e.g., NFS, EFS) in production; local volumes sufficient for dev/test

## Alternatives Considered

### A. Nginx Sticky Sessions (`ip_hash`)

Routes all requests from the same IP to the same container, but does **not** solve intra-container worker isolation (24 workers per container still create separate sessions). Also breaks when clients share IPs (corporate NAT, load balancers).

### B. Separate Code Execution Microservice

Clean architectural boundary, but adds network latency to the tool bridge callback (~1-5ms per nested tool call). The callback pattern (`sandbox → code_exec_service → tool_service → upstream MCP server`) would require cross-service RPC. Deferred as a future evolution; the Redis + shared volume changes are prerequisites regardless.

### C. Database-Backed Session Registry

Store session metadata in PostgreSQL instead of Redis. Slower for the frequent lookups required (~5ms vs ~0.5ms) and doesn't provide native TTL support. Redis is already required for ADR-038 session affinity.

### D. Full Redis Storage (Files + Metadata)

Store file contents in Redis instead of on disk, eliminating the shared volume requirement. Adds significant memory pressure for large scratch files and complicates the sandbox runtime integration (which expects filesystem paths).

## Related

- [ADR-0038: Multi-Worker Session Affinity](./038-multi-worker-session-affinity.md) — Redis-based session routing for MCP transport
- [ADR-0041: Secure Code Execution](./041-secure-code-execution-virtual-tool-filesystem.md) — Original code execution architecture
- [ADR-0007: Pluggable Cache Backend](./007-pluggable-cache-backend.md) — Redis cache infrastructure
