# -*- coding: utf-8 -*-
"""Database bootstrap/upgrade entry-point for MCP Gateway.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

The script:

1. Creates a synchronous SQLAlchemy ``Engine`` from ``settings.database_url``.
2. Looks for an *alembic.ini* two levels up from this file to drive migrations.
3. If the database is still empty (no ``gateways`` table), it:
   - builds the base schema with ``Base.metadata.create_all()``
   - stamps the migration head so Alembic knows it is up-to-date
4. Otherwise, it applies any outstanding Alembic revisions.
5. Logs a **"Database ready"** message on success.

It is intended to be invoked via ``python -m mcpgateway.bootstrap_db`` or
directly with ``python mcpgateway/bootstrap_db.py``.
"""

# Standard
import asyncio
import logging
from pathlib import Path

# Third-Party
from sqlalchemy import create_engine, inspect

# First-Party
from alembic import command
from alembic.config import Config
from mcpgateway.config import settings
from mcpgateway.db import Base

logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Bootstrap or upgrade the database schema, then log readiness.

    Runs `create_all()` + `alembic stamp head` on an empty DB, otherwise just
    executes `alembic upgrade head`, leaving application data intact.

    Args:
        None
    """
    engine = create_engine(settings.database_url)
    project_root = Path(__file__).resolve().parents[1]
    ini_path = project_root / "alembic.ini"
    cfg = Config(ini_path)  # path in container
    cfg.attributes["configure_logger"] = False

    command.ensure_version(cfg)

    insp = inspect(engine)
    if "gateways" not in insp.get_table_names():
        logger.info("Empty DB detected - creating baseline schema")
        Base.metadata.create_all(engine)
        command.stamp(cfg, "head")  # record baseline
    else:
        command.upgrade(cfg, "head")  # apply any new revisions
    logger.info("Database ready")


if __name__ == "__main__":
    asyncio.run(main())
