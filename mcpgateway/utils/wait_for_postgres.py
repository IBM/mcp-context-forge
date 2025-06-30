#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wait_for_postgres.py  —  simple readiness probe

• Reads connection info from the usual env-vars that your Helm chart
  already sets (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER,
  POSTGRES_PASSWORD).

• Tries to open a TCP+auth connection every 2 s (30× by default ~= 60 s).

• Exits 0 as soon as Postgres answers; exits 1 after all retries fail.
"""
# Standard
import os
import sys
import time

try:
    # Third-Party
    import psycopg2  # noqa: F401  (kept for import-time side effects)
except ImportError:
    sys.stderr.write("❌ psycopg2 not installed — aborting\n")
    sys.exit(1)

MAX_TRIES = int(os.getenv("PG_WAIT_MAX_TRIES", 30))
SLEEP_SEC = float(os.getenv("PG_WAIT_INTERVAL", 2))

dsn = "dbname={db} user={user} password={pwd} host={host} port={port}".format(
    db=os.getenv("POSTGRES_DB", "postgres"),
    user=os.getenv("POSTGRES_USER", "postgres"),
    pwd=os.getenv("POSTGRES_PASSWORD", ""),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=os.getenv("POSTGRES_PORT", "5432"),
)

for attempt in range(1, MAX_TRIES + 1):
    try:
        # Third-Party
        import psycopg2

        psycopg2.connect(dsn, connect_timeout=2).close()
        print("✅ Postgres is ready")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001  (broad ok for probe)
        print(f"⏳ waiting for Postgres… ({attempt}/{MAX_TRIES}) — {exc}")
        time.sleep(SLEEP_SEC)

print("❌ Postgres not ready after {:.0f}s".format(MAX_TRIES * SLEEP_SEC))
sys.exit(1)
