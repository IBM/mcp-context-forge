# -*- coding: utf-8 -*-
"""CLI: exit 0 iff the database schema is at the Alembic script-directory head.

Used as the gateway pod's startup-probe command in the Helm chart so that
pods refuse Ready until the schema has been migrated — regardless of which
migration runner did the work (Helm pre/post-install Job, init container,
external CD pipeline, manual operator step).

Exits:
    0  schema is at head
    1  schema is missing, mismatched, or any error encountered

Usage::

    python3 -m mcpgateway.utils.check_schema_at_head
"""

# Standard
from __future__ import annotations

import logging
import sys

# Third-Party
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

# First-Party
from mcpgateway.bootstrap_db import alembic_at_head, make_alembic_cfg
from mcpgateway.config import settings
from mcpgateway.db import connect_args

logger = logging.getLogger("mcpgateway.check_schema_at_head")


def main() -> int:
    """Probe entry-point. See module docstring for exit semantics."""
    # Align connection-establishment behavior with the production engine in
    # ``mcpgateway.db``. Pool internals (``pool_size`` / ``pool_timeout`` /
    # ``pool_recycle``) don't apply: the probe opens one connection per K8s
    # tick and disposes the engine, so ``NullPool`` truthfully describes the
    # lifetime. ``connect_args`` carries production-side parameters that *do*
    # matter on every connect call (psycopg TCP keepalives + prepare_threshold
    # for PostgreSQL, ``check_same_thread`` for SQLite) — alignment here keeps
    # probe-vs-prod connect behavior identical.
    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    cfg = make_alembic_cfg(settings.database_url)

    try:
        with engine.connect() as conn:
            return 0 if alembic_at_head(conn, cfg) else 1
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.warning("schema-at-head probe failed: %s", exc)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
