# mcpgateway/bootstrap_db.py
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command
from mcpgateway.db import Base
import os, logging

def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    cfg = Config("/app/alembic.ini")          # path in container

    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        logging.info("Empty DB detected – creating baseline schema")
        Base.metadata.create_all(engine)
        command.stamp(cfg, "head")            # record baseline

    command.upgrade(cfg, "head")              # apply any new revisions
    logging.info("Database ready")

if __name__ == "__main__":
    main()
