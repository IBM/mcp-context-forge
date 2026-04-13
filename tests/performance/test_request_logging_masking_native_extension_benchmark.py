# -*- coding: utf-8 -*-
"""Benchmark the request-logging masking Rust native extension against the Python path."""

# Standard
from __future__ import annotations

import importlib
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware import request_logging_middleware
from mcpgateway.middleware.request_logging_middleware import mask_sensitive_data, mask_sensitive_headers

REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_EXTENSION_MANIFEST = REPO_ROOT / "tools_rust" / "request_logging_masking_native_extension" / "Cargo.toml"


@dataclass(frozen=True)
class BenchmarkScenario:
    name: str
    python_fn: Callable[[Any], Any]
    public_native_fn: Callable[[Any], Any]
    direct_native_fn: Callable[[Any], Any]
    payload: Any
    iterations: int


def _build_scenarios(native_extension: Any) -> list[BenchmarkScenario]:
    def python_data(payload: Any) -> Any:
        settings.experimental_rust_request_logging_masking_enabled = False
        return mask_sensitive_data(payload, 12)

    def public_native_data(payload: Any) -> Any:
        settings.experimental_rust_request_logging_masking_enabled = True
        return mask_sensitive_data(payload, 12)

    def direct_native_data(payload: Any) -> Any:
        return native_extension.mask_sensitive_data(payload, 12)

    def python_headers(payload: Any) -> Any:
        settings.experimental_rust_request_logging_masking_enabled = False
        return mask_sensitive_headers(payload)

    def public_native_headers(payload: Any) -> Any:
        settings.experimental_rust_request_logging_masking_enabled = True
        return mask_sensitive_headers(payload)

    def direct_native_headers(payload: Any) -> Any:
        return native_extension.mask_sensitive_headers(payload)

    return [
        BenchmarkScenario(
            name="nested_payload_masking",
            python_fn=python_data,
            public_native_fn=public_native_data,
            direct_native_fn=direct_native_data,
            payload={
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
            iterations=120,
        ),
        BenchmarkScenario(
            name="headers_masking",
            python_fn=python_headers,
            public_native_fn=public_native_headers,
            direct_native_fn=direct_native_headers,
            payload={
                **{f"X-Custom-{index}": f"value-{index}" for index in range(512)},
                **{f"X-Api-Key-{index}": f"secret-{index}" for index in range(256)},
                "Cookie": "; ".join([f"jwt_token_{index}=abc{index}" for index in range(128)]),
            },
            iterations=300,
        ),
    ]


def test_build_scenarios_exposes_public_and_direct_native_paths(monkeypatch):
    native_extension = type(
        "NativeExtension",
        (),
        {
            "mask_sensitive_data": staticmethod(lambda payload, max_depth: {"path": "direct", "payload": payload, "max_depth": max_depth}),
            "mask_sensitive_headers": staticmethod(lambda payload: {"path": "direct", "payload": payload}),
        },
    )()
    observed_flags: list[bool] = []

    def fake_mask_sensitive_data(payload: Any, max_depth: int = 10) -> Any:
        observed_flags.append(settings.experimental_rust_request_logging_masking_enabled)
        return {"path": "public" if settings.experimental_rust_request_logging_masking_enabled else "python", "max_depth": max_depth}

    def fake_mask_sensitive_headers(payload: Any) -> Any:
        observed_flags.append(settings.experimental_rust_request_logging_masking_enabled)
        return {"path": "public" if settings.experimental_rust_request_logging_masking_enabled else "python"}

    monkeypatch.setattr("tests.performance.test_request_logging_masking_native_extension_benchmark.mask_sensitive_data", fake_mask_sensitive_data)
    monkeypatch.setattr("tests.performance.test_request_logging_masking_native_extension_benchmark.mask_sensitive_headers", fake_mask_sensitive_headers)

    scenarios = {scenario.name: scenario for scenario in _build_scenarios(native_extension)}

    public_data = scenarios["nested_payload_masking"].public_native_fn({"k": "v"})
    direct_data = scenarios["nested_payload_masking"].direct_native_fn({"k": "v"})
    python_data = scenarios["nested_payload_masking"].python_fn({"k": "v"})
    public_headers = scenarios["headers_masking"].public_native_fn({"Authorization": "Bearer x"})
    direct_headers = scenarios["headers_masking"].direct_native_fn({"Authorization": "Bearer x"})

    assert public_data["path"] == "public"
    assert direct_data["path"] == "direct"
    assert python_data["path"] == "python"
    assert public_headers["path"] == "public"
    assert direct_headers["path"] == "direct"
    assert observed_flags == [True, False, True]


def _ensure_native_extension_installed() -> Any:
    subprocess.run(["uv", "run", "maturin", "develop", "--release", "--manifest-path", str(NATIVE_EXTENSION_MANIFEST)], check=True, cwd=REPO_ROOT)
    return importlib.import_module("request_logging_masking_native_extension")


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


def _prepare_public_native_path(native_extension: Any) -> None:
    settings.experimental_rust_request_logging_masking_enabled = True
    request_logging_middleware._RUST_REQUEST_LOGGING_MODULE = native_extension
    request_logging_middleware._RUST_REQUEST_LOGGING_IMPORT_FAILED = False


def main() -> None:
    native_extension = _ensure_native_extension_installed()
    _prepare_public_native_path(native_extension)

    scenarios = _build_scenarios(native_extension)

    _assert_parity(
        scenarios[0].python_fn,
        scenarios[0].direct_native_fn,
        [
            {"password": "secret", "nested": {"authToken": "abc", "ok": "value"}},
            {"token_count": 3, "tokenizer": "ok", "privateKey": "secret"},
            [{"jwt_token": "abc"}, {"normal": "value"}],
        ],
    )
    _assert_parity(
        scenarios[1].python_fn,
        scenarios[1].direct_native_fn,
        [
            {"Authorization": "Bearer abc", "Cookie": "jwt_token=abc; theme=dark", "X-Trace-Id": "123"},
            {"X-Auth-Count": "5", "X-Api-Key": "secret"},
        ],
    )

    for scenario in scenarios:
        print(f"\n{scenario.name} ({scenario.iterations} iterations)")
        python_median, _ = _measure("python", scenario.python_fn, scenario.payload, scenario.iterations)
        public_native_median, _ = _measure("public_native", scenario.public_native_fn, scenario.payload, scenario.iterations)
        direct_native_median, _ = _measure("direct_native", scenario.direct_native_fn, scenario.payload, scenario.iterations)
        print(f"public_speedup={python_median / public_native_median:.2f}x")
        print(f"direct_speedup={python_median / direct_native_median:.2f}x")
        print(f"public_overhead={(public_native_median / direct_native_median - 1) * 100:.1f}%")


if __name__ == "__main__":
    main()
