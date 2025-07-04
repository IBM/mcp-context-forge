# mcpgateway/bootstrap_db.py
# Standard
import asyncio
import logging
from pathlib import Path

# First-Party
from alembic import command
from alembic.config import Config
from mcpgateway.config import settings
from mcpgateway.db import Base

# Third-Party
from sqlalchemy import create_engine, inspect

logger = logging.getLogger(__name__)


async def main():
    """
    Bootstrap or upgrade the database schema, then log readiness.

    Runs `create_all()` + `alembic stamp head` on an empty DB, otherwise just
    executes `alembic upgrade head`, leaving application data intact.
    """
    engine = create_engine(settings.database_url)
    project_root = Path(__file__).resolve().parents[1]
    ini_path = project_root / "alembic.ini"
    cfg = Config(ini_path)  # path in container
    cfg.attributes["configure_logger"] = False

    command.ensure_version(cfg)

    insp = inspect(engine)
    if "gateways" not in insp.get_table_names():
        logger.info("Empty DB detected – creating baseline schema")
        Base.metadata.create_all(engine)
        command.stamp(cfg, "head")  # record baseline
    else:
        command.upgrade(cfg, "head")  # apply any new revisions
    logger.info("Database ready")


if __name__ == "__main__":
    asyncio.run(main())
