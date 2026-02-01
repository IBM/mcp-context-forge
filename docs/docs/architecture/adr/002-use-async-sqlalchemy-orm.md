# ADR-0002: Use Async SQLAlchemy ORM

- *Status:* Accepted
- *Date:* 2025-02-01
- *Deciders:* Mihai Criveti

## Context

The gateway must persist:

- Tool metadata
- Resource configurations
- Usage metrics
- Peer discovery and federation state

We require a relational database with schema evolution, strong typing, and async support. The current codebase already uses SQLAlchemy ORM models with an async engine and declarative mapping style.

## Decision

We will use:

- **SQLAlchemy 2.x (async)** for all data persistence.
- **AsyncSession** and `async with` scoped transactions.
- **Alembic** for migrations, with autogeneration and CLI support.
- **SQLite** for development; **PostgreSQL or MySQL** for production via `DATABASE_URL`.
- **Configurable connection pooling** with auto-scaling based on worker count and deployment size.

This provides consistent, well-understood relational behavior and integrates cleanly with FastAPI.

Connection pooling is configured via environment variables:

- `DB_POOL_SIZE`: Persistent connections per worker (default: 50)
- `DB_MAX_OVERFLOW`: Additional connections allowed (default: 10)
- `DB_POOL_TIMEOUT`: Wait time before timeout (default: 60s)
- `DB_POOL_RECYCLE`: Connection recycle interval (default: 3600s)

For multi-pod deployments, total connections = `(pods × workers × pool_size × 1.2) + buffer`.

## Consequences

- 🧱 Mature and reliable ORM with a wide developer base.
- 🔄 Fully async I/O stack without thread-pools or blocking.
- 🔧 Migrations handled declaratively using Alembic.
- 📄 Pydantic models can be derived from or synchronized with SQLAlchemy models if needed.
- ⚙️ Connection pooling auto-scales with deployment size (vertical and horizontal scaling).

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Raw asyncpg / aiosqlite** | Manual query strings, error-prone joins, no built-in migrations. |
| **Tortoise ORM / GINO** | Less widely used, more magic, lower confidence in long-term maintainability. |
| **Django ORM** | Not async-native, tightly coupled to Django ecosystem, too heavyweight. |
| **NoSQL (e.g., MongoDB)** | No relational guarantees, weaker query language, major refactor from current SQL-based model. |

## Status

This decision is in place and all gateway persistence uses SQLAlchemy 2.x with async support.
