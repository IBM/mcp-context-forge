#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CONC-01 manual concurrency check: parallel same-name server creation.

Slice A only:
- Verify API conflict behavior under concurrent create requests.
- Does not perform direct DB uniqueness verification.

Environment variables:
- CONC_BASE_URL (default: http://localhost:8000)
- CONC_TOKEN (required)
- CONC_NAME_PREFIX (default: conc-01-server)
- CONC_DB_PATH (default: mcp.db)

Example:
  CONC_TOKEN="<jwt>" python tests/manual/concurrency/conc_01_parallel_create.py
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class _Case:
    name: str
    n: int
    timeout_sec: int
    db_check: bool


DEFAULT_CASES = [
    _Case(name="api_smoke_20", n=20, timeout_sec=10, db_check=False),
    _Case(name="api_100", n=100, timeout_sec=20, db_check=False),
    _Case(name="api_db_100", n=100, timeout_sec=20, db_check=True),
]


def _build_config() -> dict[str, object]:
    token = os.getenv("CONC_TOKEN", "").strip()
    if not token:
        raise ValueError("CONC_TOKEN is required")

    return {
        "base_url": os.getenv("CONC_BASE_URL", "http://localhost:8000").rstrip("/"),
        "token": token,
        "name_prefix": os.getenv("CONC_NAME_PREFIX", "conc-01-server").strip() or "conc-01-server",
        "db_path": os.getenv("CONC_DB_PATH", "mcp.db").strip() or "mcp.db",
    }


async def _create_server(client: httpx.AsyncClient, base_url: str, token: str, server_name: str) -> int | str:
    try:
        response = await client.post(
            f"{base_url}/servers",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "server": {
                    "name": server_name,
                    "visibility": "public",
                },
                "team_id": None,
                "visibility": "public",
            },
        )
        return response.status_code
    except Exception as exc:  # pragma: no cover - manual script behavior
        return f"{type(exc).__name__}: {exc}"


async def _count_server_name_matches(client: httpx.AsyncClient, base_url: str, token: str, server_name: str) -> int:
    """Count exact-name matches for a server via API list endpoint."""
    response = await client.get(
        f"{base_url}/servers",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Expected list response from GET /servers")
    return sum(1 for item in payload if isinstance(item, dict) and item.get("name") == server_name)


def _count_server_name_matches_db(db_path: str, server_name: str) -> int:
    """Count exact-name matches in SQLite DB for public visibility."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM servers WHERE name = ? AND visibility = ?",
            (server_name, "public"),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


async def _run_case(case: _Case, base_url: str, token: str, name_prefix: str, db_path: str) -> bool:
    run_id = int(time.time() * 1000)
    server_name = f"{name_prefix}-{case.name}-{run_id}"

    print("\n================================================================")
    print(f"Case: {case.name}")
    print("================================================================")
    print(f"Target: POST {base_url}/servers")
    print(f"Requests: {case.n}")
    print(f"Server name: {server_name}")
    print(f"DB check: {'enabled' if case.db_check else 'disabled'}")
    if case.db_check:
        print(f"DB path: {db_path}")

    timeout = httpx.Timeout(case.timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_create_server(client, base_url, token, server_name) for _ in range(case.n)]
        results = await asyncio.gather(*tasks)
        try:
            unique_count = await _count_server_name_matches(client, base_url, token, server_name)
        except Exception as exc:  # pragma: no cover - manual script behavior
            print(f"\nUNIQUENESS CHECK ERROR: {type(exc).__name__}: {exc}")
            return False

    db_unique_count: int | None = None
    if case.db_check:
        try:
            db_unique_count = _count_server_name_matches_db(db_path, server_name)
        except Exception as exc:  # pragma: no cover - manual script behavior
            print(f"\nDB UNIQUENESS CHECK ERROR: {type(exc).__name__}: {exc}")
            return False

    counts = Counter(results)
    print("\nStatus/Error distribution:")
    for key, value in sorted(counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {key}: {value}")

    success_count = counts.get(201, 0)
    conflict_count = counts.get(409, 0)
    expected_conflicts = case.n - 1

    print("\nAssertions:")
    print(f"  success(201) == 1 -> {success_count}")
    print(f"  conflict(409) == {expected_conflicts} -> {conflict_count}")
    print(f"  unique_name_count({server_name}) == 1 -> {unique_count}")
    if case.db_check and db_unique_count is not None:
        print(f"  db_unique_name_count({server_name}) == 1 -> {db_unique_count}")

    db_ok = (db_unique_count == 1) if case.db_check else True
    if success_count == 1 and conflict_count == expected_conflicts and unique_count == 1 and db_ok:
        if case.db_check:
            print("\nPASS: API+DB same-name create race behavior is correct.")
        else:
            print("\nPASS: API-level same-name create race behavior is correct.")
        return True

    print("\nFAIL: Unexpected status distribution for CONC-01.")
    return False


async def _run() -> int:
    try:
        cfg = _build_config()
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    base_url = str(cfg["base_url"])
    token = str(cfg["token"])
    name_prefix = str(cfg["name_prefix"])
    db_path = str(cfg["db_path"])

    print("CONC-01 Parallel Create (Slice A)")
    print(f"Target: POST {base_url}/servers")
    print(f"Cases: {len(DEFAULT_CASES)}")

    case_results: list[tuple[str, bool]] = []
    for case in DEFAULT_CASES:
        ok = await _run_case(case, base_url, token, name_prefix, db_path)
        case_results.append((case.name, ok))

    passed = sum(1 for _, ok in case_results if ok)
    failed = len(case_results) - passed
    print("\n================================================================")
    print("Summary")
    print("================================================================")
    for name, ok in case_results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"  total: {len(case_results)}, passed: {passed}, failed: {failed}")

    return 0 if failed == 0 else 1


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
