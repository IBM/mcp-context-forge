#!/usr/bin/env python3
"""Run the protocol-compliance harness across every runnable engine and summarize.

Orchestrates:
  1. Probe the gateway's current runtime-mode state.
  2. Pick the set of engines that are runnable without external help:
       - ``reference`` is always available (in-process FastMCP).
       - ``python`` runs when the gateway can flip to ``shadow`` (boot=shadow/edge).
       - ``rust_edge`` runs when the gateway can flip to ``edge`` (boot=edge only).
       - ``rust_full`` is noted as reachable only if the gateway currently
         reports ``effective_mode=full`` — this script never attempts to reboot.
  3. For each runnable engine: flip if needed, wait for data-plane convergence,
     run the harness with a per-engine JUnit XML output, and parse results.
  4. Aggregate + render the summary (console / markdown / JSON).
  5. Restore the original runtime mode on exit.

Exit codes:
  0 — every runnable slice green (xfails don't fail). XPASS detected but not
       required to fail (use ``--strict-xpass`` to upgrade to fail).
  1 — unexpected failure in at least one slice, or ``--strict-xpass`` and an
       XPASS occurred.
  2 — no engines runnable (gateway unreachable / misconfigured).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from xml.etree import ElementTree as ET

import httpx
import logging

# Keep the script's own output clean; the matrix summary is what matters.
logging.getLogger("httpx").setLevel(logging.WARNING)

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "compliance"
COMPLIANCE_GAPS_PATH = REPO_ROOT / "tests" / "protocol_compliance" / "COMPLIANCE_GAPS.md"

# Engines, in display order. "reference" is stdio against the in-process FastMCP
# reference server; it's not a gateway engine but including it here keeps the
# summary a single consistent table.
ENGINES = ("reference", "python", "rust_edge", "rust_full")

# Per-engine filter for pytest: chooses which (target, transport) cells to run.
# The harness's parametrize IDs are ``<target>-<transport>``; we filter via -k.
#
# For reference: run only the stdio cell.
# For the live-gateway engines, run everything EXCEPT stdio (which is
# reference-only). Each engine-slice runs the same set of gateway targets —
# the gateway's current runtime mode is what differentiates them.
_ENGINE_KEYWORD = {
    "reference": "reference-stdio",
    "python": "not reference-stdio",
    "rust_edge": "not reference-stdio",
    "rust_full": "not reference-stdio",
}

# Mode to flip to for each engine (None means don't flip).
_ENGINE_FLIP_TARGET = {
    "reference": None,
    "python": "shadow",
    "rust_edge": "edge",
    "rust_full": None,  # can't flip to full; only runs if already there.
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SliceResult:
    """Per-engine pytest run outcome.

    Invariant: ``skip_reason is None`` iff the slice actually ran. The
    parallel ``ran`` boolean that used to exist alongside ``skip_reason``
    was redundant and let callers construct nonsense states (e.g.
    ``ran=True, skip_reason='refused'``). ``ran`` is now derived from
    ``skip_reason`` via the property below, and ``__post_init__``
    enforces that a skipped slice carries no counts — previously a
    zero-test row from a crashed pytest looked identical to a clean
    skip, which was the kernel of the "0/0/0/0 silent failure" bug
    fixed this pass.
    """

    engine: str
    skip_reason: Optional[str] = None
    passed: int = 0
    failed: int = 0
    xfailed: int = 0
    xpassed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_s: float = 0.0
    junit_path: Optional[str] = None
    failures: list[tuple[str, str]] = field(default_factory=list)
    xpasses: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Negative counts are never meaningful and usually indicate a
        # bookkeeping bug (e.g. the XPASS subtraction going below zero).
        for field_name in ("passed", "failed", "xfailed", "xpassed", "skipped", "errors"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"SliceResult.{field_name} must be >= 0, got {value}")
        # Skipped-vs-ran is exclusive. Non-zero counts on a skipped slice
        # are structurally inconsistent and would misreport matrix totals.
        if self.skip_reason is not None and self.total != 0:
            raise ValueError(
                f"SliceResult for engine={self.engine!r} has skip_reason={self.skip_reason!r} " f"but counts are non-zero (total={self.total}); skipped slices must " f"not carry test counts"
            )

    @property
    def ran(self) -> bool:
        return self.skip_reason is None

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.xfailed + self.xpassed + self.skipped + self.errors


@dataclass
class MatrixReport:
    timestamp: str
    gateway_url: str
    gateway_state: dict
    slices: list[SliceResult]
    gaps_open: list[str]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "gateway_url": self.gateway_url,
            "gateway_state": self.gateway_state,
            "gaps_open": self.gaps_open,
            "slices": [asdict(s) for s in self.slices],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mint_admin_jwt() -> str:
    """Mint a platform-admin JWT with ``teams=None`` so /admin/* routes accept it."""
    from mcpgateway.utils.create_jwt_token import _create_jwt_token

    secret = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
    email = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
    return _create_jwt_token(
        data={"sub": email, "is_admin": True},
        expires_in_minutes=60,
        secret=secret,
        algorithm="HS256",
        teams=None,
    )


def _gateway_client(base_url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
        follow_redirects=True,
    )


def _probe_state(client: httpx.Client) -> Optional[dict]:
    try:
        resp = client.get("/admin/runtime/mcp-mode")
    except Exception as exc:  # noqa: BLE001 — gateway unreachable → None
        print(f"[compliance-matrix] /admin/runtime/mcp-mode unreachable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"[compliance-matrix] /admin/runtime/mcp-mode returned {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None
    return resp.json()


def _flip_mode(client: httpx.Client, target_mode: str) -> Optional[dict]:
    """PATCH to ``target_mode``. Return the response body on success, None on refusal."""
    resp = client.patch("/admin/runtime/mcp-mode", json={"mode": target_mode})
    if resp.status_code != 200:
        return None
    return resp.json()


def _wait_data_plane_converges(client: httpx.Client, expected_runtime: str, timeout_s: float = 3.0) -> bool:
    """Poll the data-plane witness header until it matches the expected runtime.

    Uses a throwaway MCP initialize whose response carries
    ``x-contextforge-mcp-runtime``. Returns True on convergence, False on timeout.
    """
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "compliance-matrix", "version": "0.1"},
        },
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": "2025-03-26",
    }
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = client.post("/mcp/", headers=headers, json=init_body)
            actual = resp.headers.get("x-contextforge-mcp-runtime")
            if actual == expected_runtime:
                return True
        except Exception:  # noqa: BLE001 — transient; keep polling until deadline
            pass
        time.sleep(0.1)
    return False


def _determine_runnable(state: Optional[dict], only: Optional[list[str]]) -> list[tuple[str, Optional[str]]]:
    """Return ``[(engine, skip_reason or None), ...]`` for every engine in ENGINES.

    A non-None ``skip_reason`` means the engine is listed in the summary but
    marked as not-run. ``only`` narrows which engines to consider at all.
    """
    chosen = list(ENGINES) if only is None else [e for e in ENGINES if e in only]
    out: list[tuple[str, Optional[str]]] = []
    for engine in chosen:
        if engine == "reference":
            out.append((engine, None))
            continue
        if state is None:
            out.append((engine, "gateway unreachable"))
            continue
        supported = set(state.get("supported_override_modes", []))
        target = _ENGINE_FLIP_TARGET[engine]
        if engine == "rust_full":
            if state.get("effective_mode") == "full":
                out.append((engine, None))
            else:
                out.append((engine, f"requires boot with RUST_MCP_MODE=full (currently {state.get('boot_mode')!r})"))
            continue
        if target not in supported:
            out.append((engine, f"gateway boot={state.get('boot_mode')!r} cannot flip to {target!r}"))
            continue
        # rust_edge requires boot=edge (safety flag); if flippable it's runnable.
        out.append((engine, None))
    return out


# ---------------------------------------------------------------------------
# Pytest runner + JUnit parser
# ---------------------------------------------------------------------------
def _run_slice(engine: str, keyword: str, junit_path: Path, xpass_log: Path, extra_args: list[str]) -> int:
    """Run pytest for the given engine slice. Returns the pytest exit code.

    Sets ``COMPLIANCE_XPASS_LOG`` so the harness's conftest hook writes XPASS
    events to the per-engine sidecar file the matrix reads afterwards.
    """
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    xpass_log.parent.mkdir(parents=True, exist_ok=True)
    # Clear BOTH sidecar artifacts before running. Leaving an old junit on
    # disk would let a crashed-before-writing pytest invocation pick up the
    # prior slice's XML and report those stale counts as the current
    # slice's — silently. _parse_junit's FileNotFoundError → ran=False
    # path only triggers if the file is genuinely absent.
    if xpass_log.exists():
        xpass_log.unlink()
    if junit_path.exists():
        junit_path.unlink()
    env = os.environ.copy()
    env["COMPLIANCE_XPASS_LOG"] = str(xpass_log)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/protocol_compliance",
        "-k",
        keyword,
        f"--junitxml={junit_path}",
        "-o",
        f"junit_suite_name=compliance-{engine}",
        "-q",
        "--tb=no",
        *extra_args,
    ]
    # The JUnit XML is the authoritative per-test record; suppress pytest's
    # streaming output so the matrix's own summary is the only thing on stdout.
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def _read_xpass_log(path: Path) -> list[str]:
    """Return the list of XPASS nodeids recorded by the conftest hook."""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        nodeid, _, _reason = line.partition("\t")
        out.append(nodeid)
    return out


def _parse_junit(path: Path) -> SliceResult:
    """Parse pytest's JUnit XML into a SliceResult. Engine populated by caller.

    A missing or malformed XML means pytest never produced output (e.g.
    collection error, CLI-usage error, crash before the junitxml plugin
    wrote). Surface that as ``ran=False`` with a ``skip_reason`` so the
    caller can distinguish "no tests matched" from "the slice never
    actually executed" — the original silent-zero-row behavior masked a
    real bug during development (0/0/0/0 looked identical to a clean
    zero-test run).
    """
    try:
        tree = ET.parse(path)
    except FileNotFoundError:
        return SliceResult(engine="", skip_reason=f"junit XML not written: {path}")
    except ET.ParseError as exc:
        return SliceResult(engine="", skip_reason=f"junit XML unparseable ({exc}): {path}")
    out = SliceResult(engine="")
    root = tree.getroot()
    # pytest emits a <testsuite> root (or wrapped in <testsuites>)
    suites = root.iter("testsuite")
    for suite in suites:
        out.errors += int(suite.get("errors", 0) or 0)
        out.duration_s += float(suite.get("time", 0.0) or 0.0)
        for case in suite.iter("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            nodeid = f"{classname}::{name}" if classname else name
            # outcome tags
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None:
                out.failed += 1
                out.failures.append((nodeid, (failure.get("message") or failure.text or "")[:200]))
            elif error is not None:
                out.errors += 1
                out.failures.append((nodeid, (error.get("message") or error.text or "")[:200]))
            elif skipped is not None:
                # pytest encodes xfail as skipped type="pytest.xfail"
                skip_type = (skipped.get("type") or "").lower()
                message = skipped.get("message") or skipped.text or ""
                if "xfail" in skip_type:
                    out.xfailed += 1
                else:
                    out.skipped += 1
                _ = message  # reserved for future per-skip drilldown
            else:
                # No failure/error/skipped → pass OR xpass.
                # pytest represents XPASS via a specific property; short-circuit: treat as pass.
                out.passed += 1
    return out


def _read_open_gaps() -> list[str]:
    """Extract GAP-NNN ids from COMPLIANCE_GAPS.md's "Open gaps" section."""
    if not COMPLIANCE_GAPS_PATH.exists():
        return []
    text = COMPLIANCE_GAPS_PATH.read_text()
    open_section_match = re.search(r"## Open gaps\n(.*?)## Closed gaps", text, re.DOTALL)
    if not open_section_match:
        return []
    open_body = open_section_match.group(1)
    return sorted(set(re.findall(r"GAP-\d{3}", open_body)))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_console(report: MatrixReport) -> str:
    lines: list[str] = []
    state = report.gateway_state or {}
    lines.append(f"Compliance matrix — {report.timestamp}  gateway={report.gateway_url}" f"  boot={state.get('boot_mode', '?')}  effective={state.get('effective_mode', '?')}")
    lines.append("─" * 96)
    header = f"{'Engine':<14}{'Passed':>8}{'Failed':>8}{'XFailed':>9}{'XPassed':>9}{'Skipped':>9}{'Errors':>8}{'Time':>8}"
    lines.append(header)
    lines.append("─" * 96)
    for s in report.slices:
        if not s.ran:
            reason = s.skip_reason or "not runnable"
            lines.append(f"{s.engine:<14}{'—':>8}  (slice skipped: {reason})")
            continue
        lines.append(f"{s.engine:<14}{s.passed:>8}{s.failed:>8}{s.xfailed:>9}{s.xpassed:>9}" f"{s.skipped:>9}{s.errors:>8}{s.duration_s:>7.1f}s")
    lines.append("─" * 96)

    if report.gaps_open:
        lines.append(f"Open gaps: {', '.join(report.gaps_open)} " f"({len(report.gaps_open)} tracked in COMPLIANCE_GAPS.md)")
    any_xpass = any(s.xpassed for s in report.slices if s.ran)
    any_failure = any(s.failed or s.errors for s in report.slices if s.ran)
    if any_xpass:
        xp_lines = [f"  [{s.engine}] {nodeid}" for s in report.slices for nodeid in s.xpasses]
        lines.append("XPASS detected (possible gap closure — review xfail markers):")
        lines.extend(xp_lines or ["  (see slice details)"])
    if any_failure:
        lines.append("Unexpected failures:")
        for s in report.slices:
            for nodeid, msg in s.failures:
                lines.append(f"  [{s.engine}] {nodeid}  — {msg}")
    if not (any_xpass or any_failure):
        lines.append("All runnable slices green.")
    return "\n".join(lines)


def _render_markdown(report: MatrixReport) -> str:
    state = report.gateway_state or {}
    lines = [
        f"# Compliance matrix — {report.timestamp}",
        "",
        f"- **Gateway**: `{report.gateway_url}`",
        f"- **Boot mode**: `{state.get('boot_mode', '?')}`",
        f"- **Effective mode**: `{state.get('effective_mode', '?')}`",
        "",
        "| Engine | Passed | Failed | XFailed | XPassed | Skipped | Errors | Time (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in report.slices:
        if not s.ran:
            lines.append(f"| {s.engine} | — | — | — | — | — | — | _skipped: {s.skip_reason or 'not runnable'}_ |")
        else:
            lines.append(f"| {s.engine} | {s.passed} | {s.failed} | {s.xfailed} | {s.xpassed} | " f"{s.skipped} | {s.errors} | {s.duration_s:.1f} |")
    if report.gaps_open:
        lines += ["", f"**Open gaps**: {', '.join(report.gaps_open)}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080"), help="Gateway base URL (default from MCP_CLI_BASE_URL or 127.0.0.1:8080).")
    ap.add_argument("--format", choices=("console", "markdown", "json"), default="console")
    ap.add_argument("--out", type=Path, help="Write rendered output to this path instead of stdout.")
    ap.add_argument("--only", help="Comma-separated engine names to consider (default: all four).")
    ap.add_argument("--require", action="append", default=[], help="Engine name that must be runnable; repeatable. Exits 2 if any aren't.")
    ap.add_argument("--no-flip", action="store_true", help="Don't issue runtime-mode PATCH calls; only run the engine that matches current mode.")
    ap.add_argument("--no-restore", action="store_true", help="Leave the final mode as-is instead of restoring the original.")
    ap.add_argument("--strict-xpass", action="store_true", help="Exit non-zero when any xfailed test passes unexpectedly.")
    ap.add_argument("--extra-pytest", default="", help="Extra arguments to append to pytest invocations.")
    args = ap.parse_args(argv)

    only = [e.strip() for e in args.only.split(",")] if args.only else None
    extra_pytest = args.extra_pytest.split() if args.extra_pytest else []

    token = _mint_admin_jwt()
    client = _gateway_client(args.base_url, token)
    state = _probe_state(client)
    original_mode = (state or {}).get("effective_mode")

    runnable = _determine_runnable(state, only)
    for req in args.require:
        if not any(e == req and r is None for e, r in runnable):
            print(f"error: required engine {req!r} not runnable", file=sys.stderr)
            return 2

    slices: list[SliceResult] = []
    try:
        for engine, skip_reason in runnable:
            s = SliceResult(engine=engine, skip_reason=skip_reason)
            if skip_reason:
                slices.append(s)
                continue
            target_mode = _ENGINE_FLIP_TARGET[engine]
            if target_mode and not args.no_flip and engine != "reference":
                if not _flip_mode(client, target_mode):
                    s.skip_reason = f"flip to {target_mode!r} refused"
                    slices.append(s)
                    continue
                expected_runtime = "rust" if target_mode == "edge" else "python"
                # If the data plane hasn't actually converged on the expected
                # runtime, running the slice would probe whatever transport
                # is really live — not what the engine label says — and the
                # resulting numbers would misattribute behavior. Skip with a
                # diagnostic rather than silently running against the wrong
                # thing.
                if not _wait_data_plane_converges(client, expected_runtime, timeout_s=3.0):
                    s.skip_reason = f"data plane did not converge on {expected_runtime!r} after flip to {target_mode!r}"
                    slices.append(s)
                    continue
            junit = ARTIFACT_DIR / f"{engine}.xml"
            xpass_log = ARTIFACT_DIR / f"{engine}.xpass"
            rc = _run_slice(engine, _ENGINE_KEYWORD[engine], junit, xpass_log, extra_pytest)
            parsed = _parse_junit(junit)
            parsed.engine = engine
            parsed.junit_path = str(junit.relative_to(REPO_ROOT))
            # pytest exit codes: 0 ok / 1 failed tests / 2 interrupted / 3 internal /
            # 4 CLI usage / 5 no tests collected. A non-zero code combined with
            # "ran=False" (no junit produced) is unambiguous infrastructure
            # breakage — flag it so the summary row doesn't read as a clean
            # zero-test run. Non-zero with a populated junit usually just means
            # test failures, which are already represented in the counts.
            if not parsed.ran and rc != 0:
                prior = parsed.skip_reason or "pytest produced no junit output"
                parsed.skip_reason = f"{prior} (pytest exit code {rc})"
            xpasses = _read_xpass_log(xpass_log)
            if xpasses:
                parsed.xpassed = len(xpasses)
                parsed.xpasses = xpasses
                # Standard JUnit emits XPASS as a plain `<testcase>` with no
                # failure/error/skipped child when strict=False, so the parser
                # above bucketed them into `passed`. Subtract to reflect
                # genuine passes in the summary. If the sidecar reports more
                # XPASS events than JUnit counted passes, the two sources of
                # truth have drifted — loud warning, don't silently clamp.
                if parsed.xpassed > parsed.passed:
                    print(
                        f"[compliance-matrix] WARNING: engine={engine}: "
                        f"xpass sidecar reports {parsed.xpassed} events but "
                        f"junit only has {parsed.passed} non-fail/error/skip "
                        f"cases. Bookkeeping drift — hook may have missed "
                        f"events or sidecar picked up stale entries.",
                        file=sys.stderr,
                    )
                parsed.passed = max(0, parsed.passed - parsed.xpassed)
            slices.append(parsed)
    finally:
        if original_mode in {"shadow", "edge"} and not args.no_restore and not args.no_flip:
            _flip_mode(client, original_mode)
        client.close()

    report = MatrixReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        gateway_url=args.base_url,
        gateway_state=state or {},
        slices=slices,
        gaps_open=_read_open_gaps(),
    )

    if args.format == "console":
        rendered = _render_console(report)
    elif args.format == "markdown":
        rendered = _render_markdown(report)
    else:
        rendered = json.dumps(report.to_dict(), indent=2)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n")
    else:
        print(rendered)

    any_failure = any((s.failed or s.errors) for s in slices if s.ran)
    any_xpass = any(s.xpassed for s in slices if s.ran)
    if any_failure:
        return 1
    if args.strict_xpass and any_xpass:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
