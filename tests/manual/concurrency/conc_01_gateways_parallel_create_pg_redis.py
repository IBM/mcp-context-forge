#!/usr/bin/env python3
"""CONC-01 manual concurrency check: parallel same-name gateway creation.

This script targets the parent-scope CONC-01 scenario on /gateways.

Default matrix (single command run):
- api_smoke_20  -> N=20, API checks only
- api_100       -> N=100, API checks only
- api_db_100    -> N=100, API + DB uniqueness checks

Environment variables:
- CONC_BASE_URL (default: http://localhost:8000)
- CONC_TOKEN (required)
- CONC_NAME_PREFIX (default: conc-gw)
- CONC_GATEWAY_URL (default: http://127.0.0.1:9000/sse)
- CONC_DB_CHECK (default: 1; set 0 to skip DB-level uniqueness checks)
- CONC_DB_PATH (default: mcp.db)  # used for sqlite fallback only
- DATABASE_URL (optional; when set to postgresql://..., DB checks use Postgres)
- CONC_CASES (optional; comma-separated case names, e.g. "api_smoke_20,api_100")
- CONC_TIMEOUT_OVERRIDE (optional; positive int seconds applied to selected cases)

Expected behavior per case:
- Exactly 1 success (200/201)
- Exactly N-1 conflicts (409)
- API uniqueness count == 1
- DB uniqueness count == 1 (when DB checks enabled)
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
import os
import sqlite3
import time
from urllib.parse import urlparse

# Third-Party
import httpx

try:
    import psycopg  # type: ignore[import-not-found]  # isort: skip
except Exception:  # pragma: no cover - optional dependency in manual script
    psycopg = None


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_config() -> dict[str, object]:
    token = os.getenv("CONC_TOKEN", "").strip()
    if not token:
        raise ValueError("CONC_TOKEN is required")

    return {
        "base_url": os.getenv("CONC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        "token": token,
        "name_prefix": os.getenv("CONC_NAME_PREFIX", "conc-gw").strip() or "conc-gw",
        "gateway_url": os.getenv("CONC_GATEWAY_URL", "http://127.0.0.1:9000/sse").strip(),
        "db_check_default": _env_bool("CONC_DB_CHECK", True),
        "db_path": os.getenv("CONC_DB_PATH", "mcp.db").strip() or "mcp.db",
        "database_url": os.getenv("DATABASE_URL", "").strip(),
        "cases_filter": os.getenv("CONC_CASES", "").strip(),
        "timeout_override": os.getenv("CONC_TIMEOUT_OVERRIDE", "").strip(),
    }


async def _create_gateway(client: httpx.AsyncClient, base_url: str, token: str, gateway_name: str, gateway_url: str) -> int | str:
    try:
        response = await client.post(
            f"{base_url}/gateways",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "name": gateway_name,
                "url": gateway_url,
                "visibility": "public",
            },
        )
        return response.status_code
    except Exception as exc:  # pragma: no cover - manual script behavior
        return f"{type(exc).__name__}: {exc}"


async def _count_gateway_name_matches_api(client: httpx.AsyncClient, base_url: str, token: str, gateway_name: str) -> int:
    response = await client.get(
        f"{base_url}/gateways",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Expected list response from GET /gateways")
    return sum(1 for item in payload if isinstance(item, dict) and item.get("name") == gateway_name)


def _db_mode(database_url: str) -> str:
    if database_url.startswith("postgresql://") or database_url.startswith("postgresql+psycopg://"):
        return "postgres"
    return "sqlite"


def _normalize_pg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.split("postgresql+psycopg://", 1)[1]
    return database_url


def _count_gateway_name_matches_sqlite(db_path: str, gateway_name: str) -> int:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gateways WHERE name = ? AND visibility = ?", (gateway_name, "public"))
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _count_gateway_name_matches_postgres(database_url: str, gateway_name: str) -> int:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; cannot run Postgres DB checks")
    dsn = _normalize_pg_dsn(database_url)
    with psycopg.connect(dsn) as conn:  # pragma: no cover - manual runtime behavior
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gateways WHERE name = %s AND visibility = %s", (gateway_name, "public"))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _count_gateway_name_matches_db(database_url: str, db_path: str, gateway_name: str) -> int:
    mode = _db_mode(database_url)
    if mode == "postgres":
        return _count_gateway_name_matches_postgres(database_url, gateway_name)
    return _count_gateway_name_matches_sqlite(db_path, gateway_name)


async def _run_case(
    case: _Case,
    base_url: str,
    token: str,
    name_prefix: str,
    gateway_url: str,
    db_check_enabled: bool,
    database_url: str,
    db_path: str,
) -> bool:
    run_id = int(time.time() * 1000)
    gateway_name = f"{name_prefix}-{case.name}-{run_id}"
    case_gateway_url = f"{gateway_url}?conc_run={run_id}"

    print("\n================================================================")
    print(f"Case: {case.name}")
    print("================================================================")
    print(f"Target: POST {base_url}/gateways")
    print(f"Requests: {case.n}")
    print(f"Gateway name: {gateway_name}")
    print(f"Gateway URL: {case_gateway_url}")
    print(f"DB check: {'enabled' if (case.db_check and db_check_enabled) else 'disabled'}")
    if case.db_check and db_check_enabled:
        print(f"DB mode: {_db_mode(database_url)}")
        if _db_mode(database_url) == "sqlite":
            print(f"DB path: {db_path}")
        else:
            host = urlparse(_normalize_pg_dsn(database_url)).hostname or "unknown"
            print(f"DB host: {host}")

    timeout = httpx.Timeout(case.timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_create_gateway(client, base_url, token, gateway_name, case_gateway_url) for _ in range(case.n)]
        results = await asyncio.gather(*tasks)
        try:
            api_unique_count = await _count_gateway_name_matches_api(client, base_url, token, gateway_name)
        except Exception as exc:  # pragma: no cover - manual script behavior
            print(f"\nAPI UNIQUENESS CHECK ERROR: {type(exc).__name__}: {exc}")
            return False

    db_unique_count: int | None = None
    do_db_check = case.db_check and db_check_enabled
    if do_db_check:
        try:
            db_unique_count = _count_gateway_name_matches_db(database_url, db_path, gateway_name)
        except Exception as exc:  # pragma: no cover - manual script behavior
            print(f"\nDB UNIQUENESS CHECK ERROR: {type(exc).__name__}: {exc}")
            return False

    counts = Counter(results)
    print("\nStatus/Error distribution:")
    for key, value in sorted(counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {key}: {value}")

    success_count = counts.get(200, 0) + counts.get(201, 0)
    conflict_count = counts.get(409, 0)
    expected_conflicts = case.n - 1

    print("\nAssertions:")
    print(f"  success(200|201) == 1 -> {success_count}")
    print(f"  conflict(409) == {expected_conflicts} -> {conflict_count}")
    print(f"  api_unique_name_count({gateway_name}) == 1 -> {api_unique_count}")
    if do_db_check and db_unique_count is not None:
        print(f"  db_unique_name_count({gateway_name}) == 1 -> {db_unique_count}")

    db_ok = (db_unique_count == 1) if do_db_check else True
    if success_count == 1 and conflict_count == expected_conflicts and api_unique_count == 1 and db_ok:
        if do_db_check:
            print("\nPASS: API+DB same-name gateway create race behavior is correct.")
        else:
            print("\nPASS: API-level same-name gateway create race behavior is correct.")
        return True

    print("\nFAIL: Unexpected status distribution for CONC-01 gateways.")
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
    gateway_url = str(cfg["gateway_url"])
    db_check_enabled = bool(cfg["db_check_default"])
    db_path = str(cfg["db_path"])
    database_url = str(cfg["database_url"])
    cases_filter_raw = str(cfg["cases_filter"])
    timeout_override_raw = str(cfg["timeout_override"])

    selected_cases = DEFAULT_CASES
    if cases_filter_raw:
        wanted = {name.strip() for name in cases_filter_raw.split(",") if name.strip()}
        selected_cases = [c for c in DEFAULT_CASES if c.name in wanted]
        if not selected_cases:
            print(f"CONFIG ERROR: CONC_CASES did not match known cases: {sorted(wanted)}")
            return 2

    timeout_override: int | None = None
    if timeout_override_raw:
        try:
            parsed = int(timeout_override_raw)
            if parsed <= 0:
                raise ValueError
            timeout_override = parsed
        except ValueError:
            print(f"CONFIG ERROR: CONC_TIMEOUT_OVERRIDE must be a positive integer, got {timeout_override_raw!r}")
            return 2

    if timeout_override is not None:
        selected_cases = [dataclass_replace(c, timeout_sec=timeout_override) for c in selected_cases]

    print("CONC-01 Parallel Gateway Create")
    print(f"Target: POST {base_url}/gateways")
    print(f"Cases: {len(selected_cases)}")
    print(f"Gateway URL under test: {gateway_url}")
    print(f"DB checks globally: {'enabled' if db_check_enabled else 'disabled'}")
    if cases_filter_raw:
        print(f"Case filter: {cases_filter_raw}")
    if timeout_override is not None:
        print(f"Timeout override: {timeout_override}s")

    case_results: list[tuple[str, bool]] = []
    for case in selected_cases:
        ok = await _run_case(
            case=case,
            base_url=base_url,
            token=token,
            name_prefix=name_prefix,
            gateway_url=gateway_url,
            db_check_enabled=db_check_enabled,
            database_url=database_url,
            db_path=db_path,
        )
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
    raise SystemExit(main())
