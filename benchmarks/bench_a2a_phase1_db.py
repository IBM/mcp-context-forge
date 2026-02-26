# -*- coding: utf-8 -*-
"""Isolated benchmark for A2A invoke Phase 1 (DB load + lock + payload building).

Measures only the Python Phase 1 path: load agents, batch lock, build payloads.
No Rust or HTTP. Use to validate batched lock and DB profiling.

Usage:
  pytest benchmarks/bench_a2a_phase1_db.py --benchmark-only -v
  make bench BENCH=phase1_db
"""

# Standard
from typing import Any, Dict, List

# Third-Party
import pytest
from sqlalchemy import select

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.services.a2a_service import A2AAgentService


def _make_requests(agent_names: List[str], n_per_agent: int = 1) -> List[Dict[str, Any]]:
    """Build invoke request list: n_per_agent entries per agent name."""
    requests = []
    for name in agent_names:
        for _ in range(n_per_agent):
            requests.append({
                "agent_name": name,
                "parameters": {"query": "bench"},
                "interaction_type": "query",
            })
    return requests


@pytest.fixture
def phase1_bench_db(app_with_temp_db):
    """Session and N agents for Phase 1 benchmark. Uses benchmark app's temp DB."""
    from mcpgateway.db import SessionLocal

    session = SessionLocal()
    try:
        # Create agents with distinct names
        for i in range(20):
            name = f"phase1-bench-agent-{i}"
            slug = name.replace("_", "-")
            existing = session.execute(select(DbA2AAgent).where(DbA2AAgent.name == name)).scalars().first()
            if not existing:
                agent = DbA2AAgent(
                    name=name,
                    slug=slug,
                    endpoint_url="http://127.0.0.1:9999/",
                    agent_type="generic",
                    protocol_version="1.0",
                    visibility="public",
                    enabled=True,
                )
                session.add(agent)
        session.commit()
        yield session
    finally:
        session.close()


def test_bench_phase1_5_agents(benchmark, phase1_bench_db):
    """Phase 1 with 5 agents, 1 request each."""
    service = A2AAgentService()
    agent_names = [f"phase1-bench-agent-{i}" for i in range(5)]
    requests = _make_requests(agent_names, 1)

    def run():
        return service._invoke_phase1(phase1_bench_db, requests)

    result = benchmark(run)
    assert len(result) == 5
    assert all(p.get("agent_id") for p in result)


def test_bench_phase1_10_agents(benchmark, phase1_bench_db):
    """Phase 1 with 10 agents, 1 request each."""
    service = A2AAgentService()
    agent_names = [f"phase1-bench-agent-{i}" for i in range(10)]
    requests = _make_requests(agent_names, 1)

    def run():
        return service._invoke_phase1(phase1_bench_db, requests)

    result = benchmark(run)
    assert len(result) == 10
    assert all(p.get("agent_id") for p in result)


def test_bench_phase1_20_agents(benchmark, phase1_bench_db):
    """Phase 1 with 20 agents, 1 request each."""
    service = A2AAgentService()
    agent_names = [f"phase1-bench-agent-{i}" for i in range(20)]
    requests = _make_requests(agent_names, 1)

    def run():
        return service._invoke_phase1(phase1_bench_db, requests)

    result = benchmark(run)
    assert len(result) == 20
    assert all(p.get("agent_id") for p in result)
