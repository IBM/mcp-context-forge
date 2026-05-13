#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/performance/test_content_security_benchmark.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Benchmark content security pattern scanning.
Usage:
    uv run python tests/performance/test_content_security_benchmark.py --mode latency
    uv run python tests/performance/test_content_security_benchmark.py --mode service-rps
    uv run python tests/performance/test_content_security_benchmark.py --mode http-e2e
    uv run python tests/performance/test_content_security_benchmark.py --mode all
"""

# Standard
import argparse
import http.client
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

SMALL_CONTENT = "clean end to end prompt content"
TEN_KB_CONTENT = ("clean end to end prompt content without blocked patterns\n" * 190)[:10_000]
HUNDRED_KB_CONTENT = ("clean resource line with ordinary text and no blocked patterns\n" * 1800)[:100_000]
JWT_SECRET = "e2e-benchmark-secret-key-with-minimum-32-bytes"  # pragma: allowlist secret  # nosec B105 - benchmark-only local secret
AUTH_SECRET = "e2e-benchmark-encryption-secret-32-bytes"  # pragma: allowlist secret  # nosec B105 - benchmark-only local secret


def _content_cases() -> list[tuple[str, str, int]]:
    """Return shared content benchmark cases."""
    return [
        ("small", SMALL_CONTENT, 3_000),
        ("10kb", TEN_KB_CONTENT, 1_000),
        ("100kb", HUNDRED_KB_CONTENT, 200),
    ]


def _set_cache(enabled: bool) -> None:
    """Toggle the clean-result cache when the setting exists."""
    # First-Party
    from mcpgateway.config import settings

    if hasattr(settings, "content_pattern_cache_enabled"):
        settings.content_pattern_cache_enabled = enabled


def _service() -> object:
    """Create a fresh content security service."""
    # First-Party
    from mcpgateway.services.content_security import ContentSecurityService

    return ContentSecurityService()


def _time_one_call(service: object, content: str, label: str) -> float:
    """Return one validation call duration in milliseconds."""
    start = time.perf_counter()
    service.detect_malicious_patterns(content, content_type=label)
    return (time.perf_counter() - start) * 1000


def run_latency() -> dict[str, dict[str, float]]:
    """Measure validator latency for first scans and repeated clean scans."""
    results: dict[str, dict[str, float]] = {}
    for label, content, _iterations in _content_cases():
        _set_cache(True)
        service = _service()
        first_ms = _time_one_call(service, content, label)
        samples = [_time_one_call(service, content, label) for _ in range(500)]
        results[label] = {
            "first_ms": first_ms,
            "mean_repeated_ms": statistics.mean(samples),
            "median_repeated_ms": statistics.median(samples),
            "min_repeated_ms": min(samples),
            "max_repeated_ms": max(samples),
        }
    return results


def _bench_service_rps(label: str, content: str, iterations: int, cache: bool) -> dict[str, float]:
    """Measure validator operations per second."""
    _set_cache(cache)
    service = _service()
    if cache:
        service.detect_malicious_patterns(content, content_type=label)

    samples = []
    for _ in range(5):
        start = time.perf_counter()
        for _i in range(iterations):
            service.detect_malicious_patterns(content, content_type=label)
        elapsed = time.perf_counter() - start
        samples.append(iterations / elapsed)

    return {
        "iterations_per_round": iterations,
        "median_rps": statistics.median(samples),
        "min_rps": min(samples),
        "max_rps": max(samples),
    }


def run_service_rps() -> dict[str, dict[str, float]]:
    """Measure validator throughput with and without clean cache hits."""
    results: dict[str, dict[str, float]] = {}
    for label, content, iterations in _content_cases():
        results[f"{label}_uncached"] = _bench_service_rps(label, content, iterations, cache=False)
        results[f"{label}_repeated"] = _bench_service_rps(label, content, iterations, cache=True)
    return results


class GatewayProcess:
    """Temporary local gateway used for the HTTP end-to-end benchmark."""

    def __init__(self) -> None:
        """Create temp resources for a live benchmark gateway."""
        self.db_file = tempfile.NamedTemporaryFile(prefix="mcfg-e2e-bench-", suffix=".db", delete=False)
        self.db_file.close()
        self.log_file = tempfile.NamedTemporaryFile(prefix="mcfg-e2e-bench-", suffix=".log", delete=False)
        self.log_file.close()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.proc: subprocess.Popen | None = None
        self.token = ""

    def _env(self) -> dict[str, str]:
        """Return gateway benchmark environment."""
        env = os.environ.copy()
        env.update(
            {
                "AUTH_REQUIRED": "true",
                "MCP_REQUIRE_AUTH": "true",
                "MCPGATEWAY_UI_ENABLED": "false",
                "MCPGATEWAY_ADMIN_API_ENABLED": "false",
                "DATABASE_URL": f"sqlite:///{self.db_file.name}",
                "JWT_SECRET_KEY": JWT_SECRET,
                "BASIC_AUTH_PASSWORD": "StrongPass123!",  # pragma: allowlist secret
                "AUTH_ENCRYPTION_SECRET": AUTH_SECRET,
                "LOG_LEVEL": "ERROR",
            }
        )
        return env

    def start(self) -> None:
        """Start uvicorn and create a benchmark JWT."""
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            stdout=open(self.log_file.name, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            env=self._env(),
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                status, _data = self.request("GET", "/health", auth=False)
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError(f"Gateway did not become healthy; log={Path(self.log_file.name).read_text(encoding='utf-8')[-2000:]}")

        token_proc = subprocess.run(
            [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin@example.com", "--exp", "60", "--secret", JWT_SECRET],
            env=self._env(),
            check=True,
            text=True,
            capture_output=True,
        )
        self.token = token_proc.stdout.strip().splitlines()[-1]

    def request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, bytes]:
        """Send one HTTP request to the benchmark gateway."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        payload = None if body is None else json.dumps(body).encode()
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        conn.request(method, path, payload, headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def close(self) -> None:
        """Stop gateway and remove temp files."""
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        Path(self.db_file.name).unlink(missing_ok=True)
        Path(self.log_file.name).unlink(missing_ok=True)


def _prompt_payload(name: str, template: str) -> dict:
    """Return a prompt create payload."""
    return {
        "prompt": {
            "name": name,
            "description": "content security benchmark",
            "template": template,
            "arguments": [],
        },
        "team_id": None,
        "visibility": "public",
    }


def _bench_http_case(gateway: GatewayProcess, case: str, template_fn: Callable[[int], str], warmup: int, iterations: int) -> dict[str, float]:
    """Measure POST /prompts throughput for one HTTP case."""
    for i in range(warmup):
        status, data = gateway.request("POST", "/prompts", _prompt_payload(f"warm_{case}_{i}_{time.time_ns()}", template_fn(i)))
        if status != 200:
            raise RuntimeError(f"Warmup {case} failed with {status}: {data[:300]!r}")

    samples = []
    for round_idx in range(5):
        start = time.perf_counter()
        for i in range(iterations):
            status, data = gateway.request("POST", "/prompts", _prompt_payload(f"bench_{case}_{round_idx}_{i}_{time.time_ns()}", template_fn(i + round_idx * iterations)))
            if status != 200:
                raise RuntimeError(f"{case} failed with {status}: {data[:300]!r}")
        elapsed = time.perf_counter() - start
        samples.append(iterations / elapsed)

    return {
        "iterations_per_round": iterations,
        "median_rps": statistics.median(samples),
        "min_rps": min(samples),
        "max_rps": max(samples),
    }


def run_http_e2e() -> dict[str, dict[str, float]]:
    """Measure real HTTP POST /prompts throughput."""
    gateway = GatewayProcess()
    try:
        gateway.start()
        return {
            "small_repeated_post_prompts": _bench_http_case(gateway, "small_repeated", lambda _i: SMALL_CONTENT, warmup=10, iterations=80),
            "10kb_repeated_post_prompts": _bench_http_case(gateway, "10kb_repeated", lambda _i: TEN_KB_CONTENT, warmup=10, iterations=60),
            "10kb_unique_post_prompts": _bench_http_case(gateway, "10kb_unique", lambda i: f"{TEN_KB_CONTENT}\nunique {i}", warmup=10, iterations=60),
        }
    finally:
        gateway.close()


def main() -> None:
    """Run selected benchmark mode."""
    parser = argparse.ArgumentParser(description="Benchmark content security validation")
    parser.add_argument("--mode", choices=["latency", "service-rps", "http-e2e", "all"], default="all")
    args = parser.parse_args()

    results = {}
    if args.mode in {"latency", "all"}:
        results["latency"] = run_latency()
    if args.mode in {"service-rps", "all"}:
        results["service_rps"] = run_service_rps()
    if args.mode in {"http-e2e", "all"}:
        results["http_e2e"] = run_http_e2e()

    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
