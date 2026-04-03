# -*- coding: utf-8 -*-
"""Benchmark the request-logging masking Rust sidecar against the Python path."""

# Standard
from __future__ import annotations

import importlib
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.request_logging_middleware import mask_sensitive_data, mask_sensitive_headers

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_MANIFEST = REPO_ROOT / "tools_rust" / "request_logging_masking_sidecar" / "Cargo.toml"


def _ensure_sidecar_installed() -> Any:
    subprocess.run(["uv", "run", "maturin", "develop", "--release", "--manifest-path", str(SIDECAR_MANIFEST)], check=True, cwd=REPO_ROOT)
    return importlib.import_module("request_logging_masking_sidecar")


def _measure(label: str, fn: Callable[[Any], Any], payload: Any, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        fn(payload)
        samples.append(time.perf_counter_ns() - started)

    median_ms = statistics.median(samples) / 1_000_000
    p95_ms = statistics.quantiles(samples, n=100)[94] / 1_000_000
    print(f"{label}: median={median_ms:.3f}ms p95={p95_ms:.3f}ms")
    return median_ms, p95_ms


def _assert_parity(python_fn: Callable[[Any], Any], rust_fn: Callable[[Any], Any], payloads: list[Any]) -> None:
    for payload in payloads:
        python_result = python_fn(payload)
        rust_result = rust_fn(payload)
        if python_result != rust_result:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: python={python_result!r} rust={rust_result!r}")


def main() -> None:
    sidecar = _ensure_sidecar_installed()
    settings.experimental_rust_request_logging_masking_enabled = False

    def python_data(payload: Any) -> Any:
        return mask_sensitive_data(payload, 12)

    def rust_data(payload: Any) -> Any:
        return sidecar.mask_sensitive_data(payload, 12)

    python_headers = mask_sensitive_headers
    rust_headers = sidecar.mask_sensitive_headers

    _assert_parity(
        python_data,
        rust_data,
        [
            {"password": "secret", "nested": {"authToken": "abc", "ok": "value"}},
            {"token_count": 3, "tokenizer": "ok", "privateKey": "secret"},
            [{"jwt_token": "abc"}, {"normal": "value"}],
        ],
    )
    _assert_parity(
        python_headers,
        rust_headers,
        [
            {"Authorization": "Bearer abc", "Cookie": "jwt_token=abc; theme=dark", "X-Trace-Id": "123"},
            {"X-Auth-Count": "5", "X-Api-Key": "secret"},
        ],
    )

    scenarios = [
        (
            "nested_payload_masking",
            python_data,
            rust_data,
            {
                "events": [
                    {
                        "actor": {"userName": f"user-{index}", "sessionToken": f"token-{index}", "sessionCount": index},
                        "request": {
                            "clientSecret": f"secret-{index}",
                            "payload": {"safeField": "value" * 8, "authDevice": f"device-{index}", "auth_count": index},
                        },
                    }
                    for index in range(1024)
                ]
            },
            120,
        ),
        (
            "headers_masking",
            python_headers,
            rust_headers,
            {
                **{f"X-Custom-{index}": f"value-{index}" for index in range(512)},
                **{f"X-Api-Key-{index}": f"secret-{index}" for index in range(256)},
                "Cookie": "; ".join([f"jwt_token_{index}=abc{index}" for index in range(128)]),
            },
            300,
        ),
    ]

    for name, python_fn, rust_fn, payload, iterations in scenarios:
        print(f"\n{name} ({iterations} iterations)")
        python_median, _ = _measure("python", python_fn, payload, iterations)
        rust_median, _ = _measure("rust", rust_fn, payload, iterations)
        print(f"speedup={python_median / rust_median:.2f}x")


if __name__ == "__main__":
    main()
