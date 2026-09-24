# -*- coding: utf-8 -*-
"""Benchmark tool lookup cache latency and database query contracts.

Run with:
    uv run pytest tests/performance/test_tool_lookup_cache_performance.py -v -s
"""

# Standard
import json
import math
import statistics
import time
from unittest.mock import AsyncMock, patch

# Third-Party
import orjson
import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.cache.tool_lookup_cache import ToolLookupCache
from mcpgateway.db import Gateway, Server, Tool
from mcpgateway.services.tool_service import ToolService


def _percentile(samples: list[float], percentile: float) -> float:
    """Return nearest-rank percentile for sorted latency samples.

    Args:
        samples: Latency samples in milliseconds.
        percentile: Percentile from zero through one.

    Returns:
        Selected latency in milliseconds.
    """
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _pool_checked_out(db) -> int | None:
    """Return checked-out connection count when the pool exposes it.

    Args:
        db: SQLAlchemy session.

    Returns:
        Checked-out connection count, or None for pools without this metric.
    """
    checkedout = getattr(db.get_bind().pool, "checkedout", None)
    return checkedout() if callable(checkedout) else None


@pytest.fixture
def cached_tool_record(test_db):
    """Create one public tool attached to one virtual server.

    Args:
        test_db: Isolated SQLAlchemy session.

    Returns:
        Persisted tool and server records.
    """
    gateway = Gateway(
        name="tool-cache-benchmark-gateway",
        slug="tool-cache-benchmark-gateway",
        url="http://tool-cache-benchmark.invalid/mcp",
        transport="STREAMABLEHTTP",
        capabilities={},
        visibility="public",
    )
    tool = Tool(
        original_name="echo",
        name="tool-cache-benchmark-gateway-echo",
        custom_name="echo",
        custom_name_slug="echo",
        description="Tool cache benchmark",
        integration_type="MCP",
        request_type="streamablehttp",
        input_schema={"type": "object"},
        visibility="public",
        enabled=True,
        reachable=True,
        gateway=gateway,
    )
    server = Server(name="tool-cache-benchmark-server", description="Tool cache benchmark", visibility="public", enabled=True)
    server.tools.append(tool)
    test_db.add(server)
    test_db.commit()
    test_db.refresh(tool)
    test_db.refresh(server)
    return tool, server


@pytest.mark.asyncio
async def test_tool_lookup_cache_performance_contract(test_db, query_counter, cached_tool_record, capsys):
    """Record latency, query count, and pool use for each cache path.

    Args:
        test_db: Isolated SQLAlchemy session.
        query_counter: SQLAlchemy statement counter fixture.
        cached_tool_record: Persisted tool and server records.
        capsys: Pytest output capture fixture.
    """
    tool, server = cached_tool_record
    service = ToolService()
    payload = service._build_tool_cache_payload(tool, tool.gateway)
    iterations = 100
    cases: list[tuple[str, ToolLookupCache, str | None, bool]] = []

    disabled_cache = ToolLookupCache()
    disabled_cache._enabled = False
    cases.append(("cache_disabled", disabled_cache, None, False))

    l1_cache = ToolLookupCache()
    l1_cache._enabled = True
    l1_cache._l2_enabled = False
    await l1_cache.set(tool.name, payload)
    cases.append(("l1_hit", l1_cache, None, False))

    redis_cache = ToolLookupCache()
    redis_cache._enabled = True
    redis_cache._l2_enabled = True
    redis = AsyncMock()
    redis.get.return_value = orjson.dumps(payload)
    redis_cache._get_redis_client = AsyncMock(return_value=redis)
    cases.append(("redis_l2_hit", redis_cache, None, True))

    server_cache = ToolLookupCache()
    server_cache._enabled = True
    server_cache._l2_enabled = False
    await server_cache.set(tool.name, payload, server_id=server.id)
    cases.append(("server_scoped_l1_hit", server_cache, server.id, False))

    server_redis_cache = ToolLookupCache()
    server_redis_cache._enabled = True
    server_redis_cache._l2_enabled = True
    server_redis = AsyncMock()
    server_redis.get.return_value = orjson.dumps(payload)
    server_redis_cache._get_redis_client = AsyncMock(return_value=server_redis)
    cases.append(("server_scoped_redis_l2_hit", server_redis_cache, server.id, True))

    report: dict[str, dict[str, float | int | None]] = {}
    expected_queries = {
        "cache_disabled": iterations,
        "l1_hit": 0,
        "redis_l2_hit": 0,
        "server_scoped_l1_hit": iterations,
        "server_scoped_redis_l2_hit": iterations,
    }
    engine = test_db.get_bind()
    benchmark_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    for case_name, cache, server_id, clear_l1 in cases:
        samples: list[float] = []
        pool_before = _pool_checked_out(test_db)
        connection_checkouts = 0

        def _record_checkout(*_args) -> None:
            nonlocal connection_checkouts
            connection_checkouts += 1

        event.listen(engine, "checkout", _record_checkout)
        try:
            with query_counter() as counter:
                with patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache):
                    for _ in range(iterations):
                        if clear_l1:
                            cache.invalidate_all_local()
                        invocation_db = benchmark_session()
                        try:
                            started = time.perf_counter_ns()
                            resolved = await service._resolve_tool_for_invocation(
                                invocation_db,
                                tool.name,
                                None,
                                None,
                                [],
                                server_id,
                                False,
                                False,
                            )
                            samples.append((time.perf_counter_ns() - started) / 1_000_000)
                            assert resolved.tool_payload["id"] == tool.id
                        finally:
                            invocation_db.close()
        finally:
            event.remove(engine, "checkout", _record_checkout)

        report[case_name] = {
            "iterations": iterations,
            "database_queries": counter.count,
            "queries_per_invocation": counter.count / iterations,
            "connection_checkouts": connection_checkouts,
            "checkouts_per_invocation": connection_checkouts / iterations,
            "p50_ms": statistics.median(samples),
            "p95_ms": _percentile(samples, 0.95),
            "p99_ms": _percentile(samples, 0.99),
            "pool_checked_out_before": pool_before,
            "pool_checked_out_after": _pool_checked_out(test_db),
        }
        assert counter.count == expected_queries[case_name]
        assert connection_checkouts == expected_queries[case_name]

    with capsys.disabled():
        print(json.dumps(report, indent=2, sort_keys=True))
