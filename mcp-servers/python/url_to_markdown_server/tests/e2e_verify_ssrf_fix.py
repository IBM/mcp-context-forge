#!/usr/bin/env python3
"""Location: ./mcp-servers/python/url_to_markdown_server/tests/e2e_verify_ssrf_fix.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

End-to-end verification for the SSRF fix in url_to_markdown_server.

Unlike tests/test_ssrf.py and tests/test_server.py, which exercise the
validator and fetch path in-process with mocked DNS/HTTP, this script starts
the actual FastMCP server as a real subprocess over real stdio transport and
drives it with a real MCP client (fastmcp.Client), using real sockets:

  - Real outbound internet access (https://example.com) to prove the fix
    does not break legitimate fetches.
  - Real local HTTP servers on 127.0.0.1 (ephemeral ports) standing in for
    "internal" victim services, to prove attacker-reachable targets are
    genuinely never connected to (not just rejected by a string match).
  - Real MCP tool-call protocol round-trips (list_tools/call_tool), so
    pydantic Field validation (batch_convert's 50-URL cap), the generic
    caller-facing error message, and the detailed server-side log line are
    all exercised exactly as a real MCP client (e.g. the ContextForge
    gateway) would exercise them.

Not wired into pytest/CI: it makes a real outbound HTTPS request and starts
several local servers/subprocesses, which is inappropriate for a fast,
network-isolated CI run. Run it manually against a built environment:

    cd mcp-servers/python/url_to_markdown_server
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    python tests/e2e_verify_ssrf_fix.py

Exit code is 0 iff every case's actual outcome matched its expectation.
Prints a human-readable summary and writes a JSON report to
tests/e2e_verify_ssrf_fix_report.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

PKG_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = Path(__file__).resolve().parent / "e2e_verify_ssrf_fix_report.json"


# ---------------------------------------------------------------------------
# Local "victim" HTTP servers - real sockets, real bytes on the wire.
# ---------------------------------------------------------------------------


class _ServerHandle:
    def __init__(self, httpd: HTTPServer, thread: threading.Thread, hit_count: list[int]):
        self.httpd = httpd
        self.thread = thread
        self.hit_count = hit_count  # mutable single-element list, incremented per request

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)


def _start_server(
    handler_factory: Callable[[list[int]], type[BaseHTTPRequestHandler]],
) -> _ServerHandle:
    hit_count = [0]
    handler_cls = handler_factory(hit_count)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return _ServerHandle(httpd, thread, hit_count)


def _quiet(handler_cls: type[BaseHTTPRequestHandler]) -> type[BaseHTTPRequestHandler]:
    handler_cls.log_message = lambda self, fmt, *args: None  # type: ignore[method-assign]
    return handler_cls


def make_secret_handler(hit_count: list[int]) -> type[BaseHTTPRequestHandler]:
    """Serves a marker string. If an SSRF attack succeeded, this content would leak."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hit_count[0] += 1
            body = b"TOP-SECRET-INTERNAL-DATA-e2e-marker"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _quiet(Handler)


def make_redirect_handler(hit_count: list[int], location: str) -> type[BaseHTTPRequestHandler]:
    """Always 302-redirects to `location` - stands in for a hop-1 target."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hit_count[0] += 1
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return _quiet(Handler)


def make_self_loop_handler(hit_count: list[int]) -> type[BaseHTTPRequestHandler]:
    """Always redirects to itself - forces MAX_REDIRECT_HOPS exhaustion."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hit_count[0] += 1
            port = cast(HTTPServer, self.server).server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return _quiet(Handler)


def make_oversized_handler(hit_count: list[int], size: int) -> type[BaseHTTPRequestHandler]:
    """Serves `size` bytes with no Content-Length header, forcing the streaming path
    to make the abort decision from the running byte count, not a header short-circuit."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hit_count[0] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"A" * 4096
            sent = 0
            try:
                while sent < size:
                    n = min(len(chunk), size - sent)
                    piece = chunk[:n]
                    self.wfile.write(f"{n:x}\r\n".encode())
                    self.wfile.write(piece)
                    self.wfile.write(b"\r\n")
                    sent += n
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # client aborted mid-stream - exactly what we're testing for

    return _quiet(Handler)


# ---------------------------------------------------------------------------
# Case bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    tool: str
    args: dict[str, Any]
    expect: str  # "blocked" | "success" | "tool_error"
    check: Callable[[Any], tuple[bool, str]] | None = None  # extra assertion on result.data
    note: str = ""


@dataclass
class CaseResult:
    name: str
    expect: str
    passed: bool
    detail: str
    elapsed_ms: float
    note: str = ""


RESULTS: list[CaseResult] = []


def record(case: Case, passed: bool, detail: str, elapsed_ms: float) -> None:
    RESULTS.append(CaseResult(case.name, case.expect, passed, detail, elapsed_ms, case.note))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {case.name} ({elapsed_ms:.0f}ms) - {detail}")


async def run_cases(env_overrides: dict[str, str], cases: list[Case], group_label: str) -> None:
    print(f"\n=== {group_label} (env: {env_overrides or '<defaults>'}) ===")
    env = {**os.environ, **env_overrides}
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "url_to_markdown_server.server_fastmcp"],
        cwd=str(PKG_DIR),
        env=env,
    )
    async with Client(transport) as client:
        for case in cases:
            t0 = time.monotonic()
            try:
                result = await client.call_tool(case.tool, case.args)
                elapsed_ms = (time.monotonic() - t0) * 1000
                data = result.data
                if case.expect == "tool_error":
                    record(case, False, f"expected ToolError, got data={data!r}", elapsed_ms)
                    continue
                if case.expect == "blocked":
                    # Rejected by the SSRF validator specifically (ssrf.py) - always
                    # the fixed, generic message, never anything more specific.
                    ok = (
                        isinstance(data, dict)
                        and data.get("success") is False
                        and data.get("error") == "URL is not allowed"
                    )
                    detail = f"data={data!r}"
                elif case.expect == "failed":
                    # Rejected post-validation, at fetch time (streaming size cap,
                    # redirect-hop exhaustion) - success False but a specific,
                    # non-generic error message is correct and expected here.
                    ok = (
                        isinstance(data, dict)
                        and data.get("success") is False
                        and isinstance(data.get("error"), str)
                    )
                    detail = f"data={data!r}"
                elif case.expect == "success":
                    if case.tool == "get_capabilities":
                        ok = (
                            isinstance(data, dict)
                            and "html_engines" in data
                            and "configuration" in data
                        )
                    else:
                        ok = isinstance(data, dict) and data.get("success") is True
                    detail = (
                        f"data={data!r}"
                        if case.tool == "get_capabilities"
                        else f"success={data.get('success') if isinstance(data, dict) else data!r}"
                    )
                else:
                    ok, detail = False, f"unknown expect={case.expect!r}"
                if ok and case.check is not None:
                    ok, extra = case.check(data)
                    detail = f"{detail}; {extra}"
                record(case, ok, detail, elapsed_ms)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - deliberately broad: any exception is a result to classify
                elapsed_ms = (time.monotonic() - t0) * 1000
                type_name = type(exc).__name__
                message = str(exc)
                if case.expect == "tool_error":
                    ok = type_name in ("ToolError", "McpError") and "50 items" in message
                    record(case, ok, f"{type_name}: {message.splitlines()[0]}", elapsed_ms)
                else:
                    is_raw_python_exception = type_name in (
                        "UnicodeEncodeError",
                        "UnicodeDecodeError",
                        "ValueError",
                        "AttributeError",
                        "TypeError",
                        "KeyError",
                    )
                    if is_raw_python_exception:
                        kind = "raw Python exception leaked to caller"
                    else:
                        kind = "unexpected error"
                    record(
                        case,
                        False,
                        f"UNEXPECTED {kind}: {type_name}: {message.splitlines()[0]}",
                        elapsed_ms,
                    )


async def main() -> int:
    print("=" * 78)
    print("E2E verification: SSRF fix in url_to_markdown_server")
    print(f"Package under test: {PKG_DIR}")
    print(f"Python:             {sys.executable}")
    print("=" * 78)

    secret_srv = _start_server(make_secret_handler)
    loop_srv = _start_server(make_self_loop_handler)
    oversized_srv = _start_server(lambda hc: make_oversized_handler(hc, size=200_000))
    redirect_to_metadata_srv = _start_server(
        lambda hc: make_redirect_handler(hc, "http://169.254.169.254/latest/meta-data/")
    )
    redirect_to_rfc1918_srv = _start_server(
        lambda hc: make_redirect_handler(hc, "http://10.255.255.255/internal")
    )

    try:
        # --------------------------------------------------------------
        # Group A: default, secure-by-default configuration (no escape
        # hatches). This is what a real deployment runs unless an operator
        # deliberately opts out.
        # --------------------------------------------------------------
        group_a: list[Case] = [
            Case(
                "deny: AWS/GCP/Azure cloud metadata (literal IP)",
                "convert_url",
                {"url": "http://169.254.169.254/latest/meta-data/"},
                "blocked",
                note="link-local, blocked unconditionally",
            ),
            Case(
                "deny: loopback - real local 'secret' service never reached",
                "convert_url",
                {"url": f"http://127.0.0.1:{secret_srv.port}/"},
                "blocked",
                check=lambda _d: (
                    secret_srv.hit_count[0] == 0,
                    f"secret server hit_count={secret_srv.hit_count[0]} (must be 0)",
                ),
            ),
            Case(
                "deny: RFC1918 private range (literal IP)",
                "convert_url",
                {"url": "http://10.1.2.3/"},
                "blocked",
            ),
            Case(
                "deny: carrier-grade NAT 100.64.0.0/10 (not covered by is_private)",
                "convert_url",
                {"url": "http://100.64.0.1/"},
                "blocked",
            ),
            Case(
                "deny: IPv6 loopback [::1]",
                "convert_url",
                {"url": "http://[::1]/"},
                "blocked",
            ),
            Case(
                "deny: credentials-in-URL bypass attempt",
                "convert_url",
                {"url": "http://trusted-looking.example@127.0.0.1/"},
                "blocked",
            ),
            Case(
                "deny: disallowed scheme (file://)",
                "convert_url",
                {"url": "file:///etc/passwd"},
                "blocked",
            ),
            Case(
                "regression: IDN hostname that fails to resolve -> clean generic "
                "error, not a raw UnicodeEncodeError (pre-fix this crashed)",
                "convert_url",
                {"url": "http://xn--nxasmq6b.invalid/"},  # already-punycode, non-resolving TLD
                "blocked",
            ),
            Case(
                "allow: real public fetch still works (https://example.com)",
                "convert_url",
                {"url": "https://example.com/"},
                "success",
                check=lambda d: (
                    isinstance(d.get("markdown"), str) and len(d["markdown"]) > 0,
                    f"markdown_len={len(d.get('markdown', ''))}",
                ),
            ),
            Case(
                "bound: batch_convert rejects 51 URLs before any fetch happens",
                "batch_convert",
                {"urls": ["http://a.example/"] * 51},
                "tool_error",
            ),
            Case(
                "mixed batch: 1 legit + 1 blocked in the same batch_convert call",
                "batch_convert",
                {"urls": ["https://example.com/", f"http://127.0.0.1:{secret_srv.port}/"]},
                "success",
                check=lambda d: (
                    d.get("successful") == 1
                    and d.get("failed") == 1
                    and any(r.get("success") for r in d.get("results", []))
                    and any(
                        not r.get("success") and r.get("error") == "URL is not allowed"
                        for r in d.get("results", [])
                    ),
                    f"successful={d.get('successful')} failed={d.get('failed')} "
                    f"results={d.get('results')}",
                ),
            ),
            Case(
                "regression: unrelated tool (get_capabilities) still works",
                "get_capabilities",
                {},
                "success",
                check=lambda d: (
                    "html_engines" in d and "configuration" in d,
                    f"keys={sorted(d.keys())}",
                ),
            ),
            Case(
                "regression: unrelated tool (convert_content, no network) still works",
                "convert_content",
                {"content": "<h1>Hi</h1><p>World</p>", "content_type": "text/html"},
                "success",
                check=lambda d: (
                    "Hi" in d.get("markdown", "") and "World" in d.get("markdown", ""),
                    f"markdown={d.get('markdown')!r}",
                ),
            ),
        ]
        await run_cases({}, group_a, "Group A: secure defaults")

        # --------------------------------------------------------------
        # Group B: MARKDOWN_ALLOW_LOCALHOST=true.
        #
        # This is a supported, documented, opt-in escape hatch (default
        # false). We use it here only because a sandboxed test run has no
        # real public server willing to redirect us to an attacker target
        # on demand - so we use our own loopback server as a stand-in for
        # "a target the operator has explicitly allowed" and prove that
        # granting it does NOT also grant the redirect target, which is a
        # different, always-blocked category (link-local / RFC1918).
        # --------------------------------------------------------------
        group_b: list[Case] = [
            Case(
                "redirect re-validation: allowed hop-1 (real local server) "
                "redirects to link-local metadata IP -> hop-2 independently blocked",
                "convert_url",
                {"url": f"http://127.0.0.1:{redirect_to_metadata_srv.port}/"},
                "blocked",
                check=lambda _d: (
                    redirect_to_metadata_srv.hit_count[0] == 1,
                    f"redirector hit_count={redirect_to_metadata_srv.hit_count[0]} "
                    "(must be exactly 1 - hop-1 WAS connected to since it's allowed; "
                    "the redirect target must never have been connected to)",
                ),
            ),
            Case(
                "redirect re-validation: allowed hop-1 redirects to RFC1918 target "
                "-> hop-2 independently blocked (escape hatch does not cross categories)",
                "convert_url",
                {"url": f"http://127.0.0.1:{redirect_to_rfc1918_srv.port}/"},
                "blocked",
            ),
            Case(
                "loopback escape hatch does not un-block RFC1918 for a direct request",
                "convert_url",
                {"url": "http://10.9.9.9/"},
                "blocked",
                note="proves MARKDOWN_ALLOW_LOCALHOST only loosens loopback, nothing else",
            ),
        ]
        await run_cases(
            {"MARKDOWN_ALLOW_LOCALHOST": "true"}, group_b, "Group B: MARKDOWN_ALLOW_LOCALHOST=true"
        )

        # --------------------------------------------------------------
        # Group C: MARKDOWN_ALLOW_LOCALHOST=true + tightened resource
        # limits, to exercise the streaming-abort and redirect-hop-bound
        # branches within a fast test run (defaults are 50MB / 10 hops).
        # --------------------------------------------------------------
        group_c: list[Case] = [
            Case(
                "streaming abort: response exceeds MAX_CONTENT_SIZE, "
                "connection aborted mid-transfer (not fully buffered first)",
                "convert_url",
                {"url": f"http://127.0.0.1:{oversized_srv.port}/"},
                "failed",
                check=lambda d: (
                    "too large" in d.get("error", "").lower(),
                    f"error={d.get('error')!r}",
                ),
            ),
            Case(
                "redirect-loop bound: self-redirecting server exhausts "
                "MAX_REDIRECT_HOPS rather than looping forever",
                "convert_url",
                {"url": f"http://127.0.0.1:{loop_srv.port}/"},
                "failed",
                check=lambda d: (
                    "too many redirects" in d.get("error", "").lower(),
                    f"error={d.get('error')!r}",
                ),
            ),
        ]
        await run_cases(
            {
                "MARKDOWN_ALLOW_LOCALHOST": "true",
                "MARKDOWN_MAX_CONTENT_SIZE": "8192",
                "MARKDOWN_MAX_REDIRECT_HOPS": "3",
            },
            group_c,
            "Group C: MARKDOWN_ALLOW_LOCALHOST=true, tightened limits",
        )

        hits = loop_srv.hit_count[0]
        expected_hits = 4  # MAX_REDIRECT_HOPS=3 + 1 initial request
        assert hits == expected_hits, f"expected {expected_hits} loop-server attempts, got {hits}"
        print(
            f"\n[info] redirect-loop server was hit exactly {hits} times "
            "- proves the loop bound, not an infinite loop.",
        )

    finally:
        for srv in (
            secret_srv,
            loop_srv,
            oversized_srv,
            redirect_to_metadata_srv,
            redirect_to_rfc1918_srv,
        ):
            srv.shutdown()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = len(RESULTS)
    failed = [r for r in RESULTS if not r.passed]
    print("\n" + "=" * 78)
    print(f"RESULT: {total - len(failed)}/{total} passed")
    if failed:
        print("\nFAILED CASES:")
        for r in failed:
            print(f"  - {r.name}\n    {r.detail}")
    print("=" * 78)

    report = {
        "package_under_test": str(PKG_DIR),
        "python": sys.executable,
        "total": total,
        "passed": total - len(failed),
        "failed": len(failed),
        "cases": [r.__dict__ for r in RESULTS],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report written to: {REPORT_PATH}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
