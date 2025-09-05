#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/scripts/run_restler_docker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Run RESTler API fuzzing via Docker when the server is ready.

This helper waits for the gateway at BASE_URL to expose /openapi.json,
downloads it into reports/restler/openapi.json, and then launches RESTler
Docker image to compile and test.

Environment variables:
  MCPFUZZ_BASE_URL        (default: http://localhost:4444)
  MCPFUZZ_AUTH_HEADER     (optional: e.g. "Authorization: Basic ...")
  MCPFUZZ_TIME_BUDGET     (default: 5 minutes)
  MCPFUZZ_NO_SSL          (default: 1 => pass --no_ssl)

CLI options mirror these and take precedence over env values.
"""
# Future
from __future__ import annotations

# Standard
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def project_root() -> Path:
    # tests/fuzz/scripts -> tests -> repo root (parents[2])
    return Path(__file__).resolve().parents[2]


def check_docker_available() -> None:
    if shutil.which("docker") is None:
        print("[RESTler] Docker not found in PATH. Please install Docker.", file=sys.stderr)
        sys.exit(2)


def wait_for_openapi(url: str, headers: dict[str, str], timeout: int = 60) -> bytes:
    """Wait until OpenAPI is available, return its bytes."""
    print(f"[RESTler] Waiting for OpenAPI at {url} (timeout {timeout}s)...")
    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout:
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=5) as resp:
                data = resp.read()
                # Quick sanity check it's JSON
                try:
                    json.loads(data.decode("utf-8", errors="ignore"))
                except Exception:
                    pass  # still accept; RESTler will validate
                print("[RESTler] OpenAPI document fetched.")
                return data
        except (HTTPError, URLError, OSError) as e:
            last_err = e
            time.sleep(1.0)
    print(f"[RESTler] Failed to fetch OpenAPI within timeout: {last_err}", file=sys.stderr)
    sys.exit(3)


def run_docker_restler(out_dir: Path, time_budget: int, no_ssl: bool) -> None:
    volume = f"{out_dir}:{'/workspace'}"
    image = "ghcr.io/microsoft/restler"

    compile_cmd = [
        "docker", "run", "--rm",
        "-v", volume,
        image,
        "restler", "compile",
        "--api_spec", "/workspace/openapi.json",
    ]

    test_cmd = [
        "docker", "run", "--rm",
        "-v", volume,
        image,
        "restler", "test",
        "--grammar_dir", "/workspace/Compile",
        "--time_budget", str(time_budget),
    ]
    if no_ssl:
        test_cmd.append("--no_ssl")

    print("[RESTler] Running compile:", " ".join(compile_cmd))
    res = subprocess.run(compile_cmd, check=False)
    if res.returncode != 0:
        print(f"[RESTler] Compile failed with exit code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)

    print("[RESTler] Running test:", " ".join(test_cmd))
    res = subprocess.run(test_cmd, check=False)
    if res.returncode != 0:
        print(f"[RESTler] Test failed with exit code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)

    print("[RESTler] Completed. Artifacts under:", out_dir)


def parse_header(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    # Expect "Name: Value" format
    if ":" not in header:
        print("[RESTler] Invalid header format. Use 'Name: Value'", file=sys.stderr)
        sys.exit(4)
    name, value = header.split(":", 1)
    return {name.strip(): value.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RESTler via Docker against a running gateway")
    parser.add_argument("--base-url", default=os.getenv("MCPFUZZ_BASE_URL", "http://localhost:4444"), help="Gateway base URL")
    parser.add_argument("--openapi-path", default="/openapi.json", help="OpenAPI path, default /openapi.json")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: reports/restler at repo root)")
    parser.add_argument("--auth-header", default=os.getenv("MCPFUZZ_AUTH_HEADER"), help="Optional single HTTP header 'Name: Value'")
    parser.add_argument("--time-budget", type=int, default=int(os.getenv("MCPFUZZ_TIME_BUDGET", "5")), help="RESTler time budget (minutes)")
    parser.add_argument("--no-ssl", action="store_true", default=os.getenv("MCPFUZZ_NO_SSL", "1") == "1", help="Pass --no_ssl to RESTler test")

    args = parser.parse_args()

    check_docker_available()

    root = project_root()
    out_dir = Path(args.out_dir) if args.out_dir else (root / "reports" / "restler")
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = parse_header(args.auth_header)
    openapi_url = f"{args.base_url.rstrip('/')}{args.openapi_path}"

    data = wait_for_openapi(openapi_url, headers, timeout=60)
    openapi_file = out_dir / "openapi.json"
    openapi_file.write_bytes(data)
    print(f"[RESTler] Saved OpenAPI to {openapi_file}")

    run_docker_restler(out_dir, time_budget=args.time_budget, no_ssl=args.no_ssl)


if __name__ == "__main__":
    main()
