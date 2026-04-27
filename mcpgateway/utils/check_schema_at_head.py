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

from importlib.resources import files
import logging
import sys

# Third-Party
from alembic.config import Config
from sqlalchemy import create_engine

# First-Party
from mcpgateway.bootstrap_db import _alembic_at_head
from mcpgateway.config import settings

logger = logging.getLogger("mcpgateway.check_schema_at_head")


def main() -> int:
    """Probe entry-point. See module docstring for exit semantics."""
    engine = create_engine(settings.database_url)
    ini_path = files("mcpgateway").joinpath("alembic.ini")
    cfg = Config(str(ini_path))

    # Mirror bootstrap_db.main()'s URL handling so configparser doesn't
    # explode on URL-encoded passwords (e.g., %40 for '@').
    escaped_url = settings.database_url.replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", escaped_url)

    try:
        with engine.connect() as conn:
            return 0 if _alembic_at_head(conn, cfg) else 1
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.warning("schema-at-head probe failed: %s", exc)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
