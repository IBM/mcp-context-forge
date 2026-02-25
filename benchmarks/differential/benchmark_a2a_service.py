# -*- coding: utf-8 -*-
"""A2A invoke_agent benchmark: Python (httpx) vs Rust (reqwest).

Uses pytest-benchmark for warmup, calibration, GC control, and statistics.
Run: uv run --extra fuzz python -m pytest benchmarks/differential/test_a2a_invoke_benchmark.py --benchmark-only
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import socket
import uuid
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from aiohttp import web

# First-Party
from mcpgateway.services.a2a_service import A2AAgentService

logging.getLogger("aiohttp.access").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

try:
    from mcpgateway_rust.services import a2a_service as rust_a2a

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False


def _rust_invoke_accepts_dict() -> bool:
    """True if the installed Rust extension accepts request_payload (dict), not request_json (str)."""
    if not RUST_AVAILABLE or not hasattr(rust_a2a, "invoke"):
        return False
    try:
        sig = inspect.signature(rust_a2a.invoke)
        params = list(sig.parameters)
        # New API: second param is request_payload (dict). Old API: request_json (str).
        return len(params) >= 2 and params[1] == "request_payload"
    except (ValueError, TypeError):
        return False


# Shared benchmark options (min_rounds, max_time, warmup)
# calibration_precision set in conftest.py to avoid stuck calibration on I/O
BENCHMARK_OPTS = {
    "min_rounds": 10,
    "max_time": 3.0,
    "disable_gc": True,
    "warmup": True,
    "warmup_iterations": 20,
}


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_server(port: int, latency_ms: float = 0) -> web.Application:
    async def handle_post(request: web.Request) -> web.Response:
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)
        return web.json_response({"response": "ok", "status": "success"})

    app = web.Application()
    app.router.add_post("/", handle_post)
    return app


def _create_mocks(endpoint_url: str) -> tuple[MagicMock, MagicMock]:
    mock_agent = MagicMock()
    mock_agent.id = uuid.uuid4().hex
    mock_agent.name = "bench-agent"
    mock_agent.enabled = True
    mock_agent.endpoint_url = endpoint_url
    mock_agent.auth_type = None
    mock_agent.auth_value = None
    mock_agent.auth_query_params = None
    mock_agent.protocol_version = "1.0"
    mock_agent.agent_type = "generic"
    mock_agent.visibility = "public"
    mock_agent.team_id = None
    mock_agent.owner_email = None

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
    mock_db.commit = MagicMock()
    mock_db.close = MagicMock()

    return mock_db, mock_agent


async def _run_invoke(
    service: A2AAgentService,
    mock_db: MagicMock,
    mock_agent: MagicMock,
    use_rust: bool,
) -> None:
    with patch("mcpgateway.services.a2a_service.get_for_update", return_value=mock_agent):
        with patch("mcpgateway.services.a2a_service.fresh_db_session") as mock_fresh:
            mock_ts_db = MagicMock()
            mock_ts_db.execute.return_value.scalar_one_or_none.return_value = mock_agent
            mock_ts_db.commit = MagicMock()
            mock_fresh.return_value.__enter__.return_value = mock_ts_db
            mock_fresh.return_value.__exit__.return_value = None
            with patch(
                "mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service",
                return_value=MagicMock(),
            ):
                if use_rust:
                    await service.invoke_agent(mock_db, mock_agent.name, {"test": "data"})
                else:
                    # Force Python path: patch invoke to raise, or rely on AttributeError if no invoke
                    if RUST_AVAILABLE and hasattr(rust_a2a, "invoke"):
                        with patch.object(rust_a2a, "invoke", side_effect=ImportError("forced")):
                            await service.invoke_agent(mock_db, mock_agent.name, {"test": "data"})
                    else:
                        await service.invoke_agent(mock_db, mock_agent.name, {"test": "data"})


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def a2a_server(event_loop):
    """Start aiohttp server for benchmark."""
    port = _find_free_port()
    app = event_loop.run_until_complete(_make_server(port))
    runner = web.AppRunner(app)
    event_loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", port)
    event_loop.run_until_complete(site.start())
    yield f"http://127.0.0.1:{port}/"
    event_loop.run_until_complete(runner.cleanup())


@pytest.fixture(scope="module")
def a2a_service():
    return A2AAgentService()


@pytest.fixture
def a2a_mocks(a2a_server):
    return _create_mocks(a2a_server)


@pytest.mark.benchmark(group="a2a_invoke", **BENCHMARK_OPTS)
def test_bench_a2a_python_httpx(benchmark, a2a_service, a2a_mocks, event_loop):
    """Benchmark Python path (httpx fallback)."""
    mock_db, mock_agent = a2a_mocks

    def one_iter():
        return event_loop.run_until_complete(_run_invoke(a2a_service, mock_db, mock_agent, use_rust=False))

    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_log:
        mock_log.log = MagicMock()
        mock_log.info = MagicMock()
        benchmark(one_iter)


@pytest.mark.benchmark(group="a2a_invoke", **BENCHMARK_OPTS)
@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust a2a_service not built")
def test_bench_a2a_rust_reqwest(benchmark, a2a_service, a2a_mocks, event_loop):
    """Benchmark full invoke_agent flow using Rust path (reqwest). Same flow as unit tests; no direct Rust call."""
    mock_db, mock_agent = a2a_mocks

    def one_iter():
        return event_loop.run_until_complete(_run_invoke(a2a_service, mock_db, mock_agent, use_rust=True))

    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_log:
        mock_log.log = MagicMock()
        mock_log.info = MagicMock()
        benchmark(one_iter)
