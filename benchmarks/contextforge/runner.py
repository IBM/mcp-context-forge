# -*- coding: utf-8 -*-
"""Sequential benchmark suite runner for TOML-driven performance scenarios."""

from __future__ import annotations

# Standard
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import tomllib
from typing import Any

# First-Party
from benchmarks.contextforge.workload import SUPPORTED_WORKLOAD_SELECTIONS, benchmark_catalog, benchmark_request_names, resolve_requests_from_workload

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = BUNDLE_ROOT / "scenarios"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "benchmarks"
RUNTIME_STAGING_ROOT = DEFAULT_OUTPUT_ROOT / "_runtime_staging"
LOCUST_IMAGE = "docker.io/locustio/locust:latest"
SUMMARY_LIMIT = 10
SUPPORTED_TOP_LEVEL_KEYS = {"suite", "defaults", "scenario"}
SUPPORTED_SUITE_KEYS = {
    "name",
    "description",
    "output_root",
    "continue_on_failure",
    "save_intermediate_artifacts",
    "flamegraph_enabled",
    "baseline_run",
    "baseline_rps_drop_pct",
    "baseline_p95_regression_pct",
    "baseline_failure_increase",
}
SUPPORTED_DEFAULT_SECTION_KEYS = {
    "setup",
    "build",
    "runtime",
    "gateway",
    "load",
    "measurement",
    "requests",
    "profiling",
    "plugins",
    "execution",
}
SUPPORTED_SCENARIO_KEYS = {
    "name",
    "description",
    "scenario_type",
    "setup",
    "build",
    "runtime",
    "gateway",
    "load",
    "measurement",
    "requests",
    "profiling",
    "plugins",
    "execution",
}
SUPPORTED_SETUP_KEYS = {"target_kind", "auth_mode", "plugins_enabled", "expected_mcp_runtime", "expected_mcp_runtime_mode", "expected_a2a_runtime"}
SUPPORTED_BUILD_KEYS = {"rust_plugins", "profiling_image", "container_file", "image_name", "image_tag", "rebuild_policy", "repo_url", "git_ref", "git_commit", "args"}
SUPPORTED_RUNTIME_KEYS = {"http_server", "host", "transport_type", "gunicorn", "granian", "uvicorn"}
SUPPORTED_GUNICORN_KEYS = {"workers", "timeout", "graceful_timeout", "keep_alive", "max_requests", "max_requests_jitter", "backlog", "preload_app", "dev_mode"}
SUPPORTED_GRANIAN_KEYS = {
    "workers",
    "runtime_mode",
    "runtime_threads",
    "blocking_threads",
    "http",
    "loop",
    "task_impl",
    "http1_pipeline_flush",
    "http1_buffer_size",
    "backlog",
    "backpressure",
    "respawn_failed",
    "workers_lifetime",
    "workers_max_rss",
    "dev_mode",
    "log_level",
}
SUPPORTED_UVICORN_KEYS = {"workers", "loop", "http", "backlog", "timeout_keep_alive", "limit_max_requests", "log_level", "dev_mode"}
SUPPORTED_GATEWAY_KEYS = {"trust_proxy_auth", "disable_access_log", "templates_auto_reload", "structured_logging_database_enabled", "sqlalchemy_echo", "log_level", "environment"}
SUPPORTED_LOAD_KEYS = {
    "locustfile",
    "user_class",
    "headless",
    "only_summary",
    "html_report",
    "users",
    "spawn_rate",
    "run_time",
    "request_count",
    "host",
    "seed",
    "tags",
    "exclude_tags",
    "extra_args",
    "env",
    "target_service",
    "workload",
}
SUPPORTED_WORKLOAD_KEYS = {"selection", "fallback_endpoint", "endpoints"}
SUPPORTED_WORKLOAD_ENDPOINT_KEYS = {"enabled", "weight"}
SUPPORTED_MEASUREMENT_KEYS = {"warmup_seconds", "measure_seconds", "profile_seconds", "cooldown_seconds"}
SUPPORTED_REQUESTS_KEYS = {
    "enabled_groups",
    "disabled_groups",
    "enabled_endpoints",
    "disabled_endpoints",
    "enabled_tags",
    "disabled_tags",
    "include_admin_endpoints",
    "include_mcp_endpoints",
    "include_resource_endpoints",
    "include_prompt_endpoints",
    "include_tool_endpoints",
}
SUPPORTED_PROFILING_KEYS = {"enabled", "tools", "py_spy", "duration_seconds", "required"}
SUPPORTED_EXECUTION_KEYS = {"retry_enabled", "max_attempts", "capture_logs", "save_raw_results", "reuse_stack"}
SUPPORTED_REBUILD_POLICIES = {"never", "missing", "always"}


@dataclass(frozen=True)
class ContainerRuntime:
    """Container runtime and compose command pair."""

    engine: str
    compose_cmd: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioSource:
    """Resolved source checkout for a benchmark scenario."""

    repo_root: Path
    commit: str
    ref_label: str
    content_fingerprint: str
    repo_url: str | None = None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, ScenarioSource):
        return {
            "repo_root": str(value.repo_root),
            "commit": value.commit,
            "ref_label": value.ref_label,
            "content_fingerprint": value.content_fingerprint,
            "repo_url": value.repo_url,
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _emit_progress(message: str) -> None:
    try:
        print(f"[benchmark-suite] {message}", flush=True)
    except BrokenPipeError:
        return


def _unavailable_sections(reason: str) -> dict[str, dict[str, Any]]:
    return {
        "endpoint_metrics": {"status": "unavailable", "reason": reason},
        "plugin_timing": {"status": "unavailable", "reason": reason},
        "pyspy": {"status": "unavailable", "reason": reason},
        "memray": {"status": "unavailable", "reason": reason},
        "process_stats": {"status": "unavailable", "reason": reason},
        "flamegraph_run": {"status": "unavailable", "reason": reason},
        "database_metrics": {"status": "unavailable", "reason": reason},
        "system_metrics": {"status": "unavailable", "reason": reason},
    }


def _slugify(name: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in name).strip("-") or "benchmark"


def _trim_status_text(value: str, limit: int = 240) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _compose_probe_detail(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    if not output:
        return fallback

    text = _trim_status_text(output)
    noisy_markers = (
        "Executing external compose provider",
        "Error: executing /opt/homebrew/bin/podman-compose",
        "Error: executing /usr/bin/podman-compose",
        "can only create exec sessions on running containers",
        "no container with name or ID",
    )
    if any(marker in text for marker in noisy_markers):
        return fallback
    return text


def _numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_percent_delta(left: float, right: float) -> float | None:
    if left == 0:
        return None
    return ((right - left) / left) * 100.0


def _round_metric(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _status_badge(status: str) -> str:
    mapping = {"ok": "good", "validated": "neutral", "pending": "neutral", "failed": "bad", "unavailable": "warn"}
    return mapping.get(status, "neutral")


def _is_mountable_runtime_path(path: Path) -> bool:
    resolved = path.resolve()
    return str(resolved).startswith("/Users/")


def _discover_rust_components(repo_root: Path) -> dict[str, list[str]]:
    plugins_dir = repo_root / "plugins_rust"
    tools_dir = repo_root / "tools_rust"
    plugins = sorted(path.name for path in plugins_dir.iterdir() if path.is_dir() and (path / "Cargo.toml").exists()) if plugins_dir.exists() else []
    tools = sorted(path.name for path in tools_dir.iterdir() if path.is_dir() and (path / "Cargo.toml").exists()) if tools_dir.exists() else []
    return {"plugins_rust": plugins, "tools_rust": tools}


def _compose_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _scenario_build(scenario: dict[str, Any]) -> dict[str, Any]:
    return scenario.get("build", {}) or {}


def _scenario_build_args(build: dict[str, Any]) -> dict[str, str]:
    raw_args = build.get("args", {}) or {}
    if not isinstance(raw_args, dict):
        return {}
    return {str(key): str(value) for key, value in raw_args.items()}


def _scenario_requests(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    workload = (scenario.get("load", {}) or {}).get("workload")
    requests = resolve_requests_from_workload(workload)
    return requests or benchmark_catalog()


def _scenario_uses_fast_time_fixture(scenario: dict[str, Any]) -> bool:
    for request in _scenario_requests(scenario):
        definition = request.get("request", {}) or {}
        if request.get("group") in {"mcp", "tools", "resources", "prompts", "servers"}:
            return True
        if definition.get("kind") == "mcp":
            return True
    return False


def _scenario_uses_a2a_fixture(scenario: dict[str, Any]) -> bool:
    for request in _scenario_requests(scenario):
        if request.get("group") == "a2a":
            return True
        if str((request.get("request", {}) or {}).get("path", "")).startswith("/a2a"):
            return True
    return False


def _scenario_source_ref(build: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    repo_url = str(build.get("repo_url", "") or "").strip() or None
    git_ref = str(build.get("git_ref", "") or "").strip() or None
    commit = str(build.get("git_commit", "") or "").strip() or None
    return repo_url, git_ref, commit


def _git_ref_available(repo_root: Path, ref: str) -> bool:
    result = _run_command(["git", "-C", str(repo_root), "rev-parse", "--verify", ref], check=False, timeout=15)
    return result.returncode == 0


def _scenario_source_fingerprint(repo_root: Path, commit: str) -> str:
    if repo_root != REPO_ROOT:
        return commit[:12]

    tracked_diff = _run_command(["git", "-C", str(repo_root), "diff", "--no-ext-diff", "--binary", "HEAD", "--"], check=False, timeout=60)
    untracked_result = _run_command(["git", "-C", str(repo_root), "ls-files", "-z", "--others", "--exclude-standard"], check=False, timeout=30)
    untracked_paths = sorted(path for path in (untracked_result.stdout or "").split("\0") if path)
    if not (tracked_diff.stdout or tracked_diff.stderr or untracked_paths):
        return commit[:12]

    digest = hashlib.sha256()
    digest.update(commit.encode("utf-8"))
    digest.update((tracked_diff.stdout or "").encode("utf-8"))
    digest.update((tracked_diff.stderr or "").encode("utf-8"))
    for relative_path in untracked_paths:
        digest.update(relative_path.encode("utf-8"))
        file_path = repo_root / relative_path
        if not file_path.exists() or file_path.is_dir():
            continue
        digest.update(file_path.read_bytes())
    return f"{commit[:12]}-{digest.hexdigest()[:10]}"


def _copy_build_context_file(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_symlink():
        target = os.readlink(source_path)
        if destination_path.exists() or destination_path.is_symlink():
            destination_path.unlink()
        os.symlink(target, destination_path)
        return
    shutil.copy2(source_path, destination_path)


def _prepare_benchmark_build_context(source: ScenarioSource) -> Path:
    context_root = RUNTIME_STAGING_ROOT / "build_contexts" / source.content_fingerprint
    marker_path = context_root / ".contextforge-build-context"
    bench_required = source.repo_root != REPO_ROOT
    if marker_path.exists():
        if bench_required and not (context_root / "benchmarks" / "contextforge").exists():
            marker_path.unlink(missing_ok=True)
            if context_root.exists():
                shutil.rmtree(context_root, ignore_errors=True)
        else:
            return context_root

    if context_root.exists():
        shutil.rmtree(context_root, ignore_errors=True)
    context_root.mkdir(parents=True, exist_ok=True)

    tracked_result = _run_command(["git", "-C", str(source.repo_root), "ls-files", "-z"], timeout=30)
    untracked_result = _run_command(["git", "-C", str(source.repo_root), "ls-files", "-z", "--others", "--exclude-standard"], timeout=30)
    relative_paths = sorted(
        {
            path
            for path in itertools.chain((tracked_result.stdout or "").split("\0"), (untracked_result.stdout or "").split("\0"))
            if path
        }
    )
    for relative_path in relative_paths:
        source_path = source.repo_root / relative_path
        if not source_path.exists() and not source_path.is_symlink():
            continue
        if source_path.is_dir():
            continue
        _copy_build_context_file(source_path, context_root / relative_path)

    # When building from another ref (e.g. compare scenario), that ref may not
    # contain benchmarks/contextforge/. Inject the runner's benchmark suite
    # so the same Containerfile works (COPY benchmarks/contextforge/ and entrypoint scripts).
    if source.repo_root != REPO_ROOT:
        bench_src = REPO_ROOT / "benchmarks" / "contextforge"
        bench_dst = context_root / "benchmarks" / "contextforge"
        if bench_src.is_dir():
            bench_dst.mkdir(parents=True, exist_ok=True)
            for path in bench_src.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(bench_src)
                    (bench_dst / rel).parent.mkdir(parents=True, exist_ok=True)
                    _copy_build_context_file(path, bench_dst / rel)

    marker_path.write_text(
        json.dumps({"commit": source.commit, "ref_label": source.ref_label, "content_fingerprint": source.content_fingerprint}, sort_keys=True),
        encoding="utf-8",
    )
    return context_root


def _repo_cache_key(repo_url: str, git_ref: str | None, commit: str | None) -> str:
    payload = f"{repo_url}\0{git_ref or ''}\0{commit or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _ensure_scenario_source(scenario: dict[str, Any]) -> ScenarioSource:
    cached = scenario.get("_scenario_source")
    if isinstance(cached, ScenarioSource):
        return cached

    build = _scenario_build(scenario)
    repo_url, git_ref, commit = _scenario_source_ref(build)
    if not repo_url and not git_ref and not commit:
        resolved_commit = _run_command(["git", "rev-parse", "HEAD"], timeout=15).stdout.strip()
        source = ScenarioSource(
            repo_root=REPO_ROOT,
            commit=resolved_commit,
            ref_label="workspace",
            content_fingerprint=_scenario_source_fingerprint(REPO_ROOT, resolved_commit),
        )
        scenario["_scenario_source"] = source
        return source

    if not repo_url:
        raise RuntimeError(f"Scenario '{scenario['name']}' must define build.repo_url when using build.git_ref or build.git_commit")

    checkout_dir = RUNTIME_STAGING_ROOT / "source_checkouts" / _repo_cache_key(repo_url, git_ref, commit)
    if not checkout_dir.exists():
        checkout_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_command(["git", "clone", repo_url, str(checkout_dir)], timeout=300)

    _run_command(["git", "-C", str(checkout_dir), "remote", "set-url", "origin", repo_url], check=False, timeout=30)
    _run_command(["git", "-C", str(checkout_dir), "fetch", "--tags", "origin"], check=False, timeout=180)
    if git_ref:
        _run_command(["git", "-C", str(checkout_dir), "fetch", "origin", git_ref], check=False, timeout=180)

    if commit and not _git_ref_available(checkout_dir, commit):
        raise RuntimeError(f"Scenario '{scenario['name']}' references unknown git commit '{commit}'")

    ref = commit or f"origin/{git_ref}" if git_ref else "origin/HEAD"
    if not _git_ref_available(checkout_dir, ref):
        raise RuntimeError(f"Scenario '{scenario['name']}' references unknown git ref '{ref}'")

    resolved_commit = _run_command(["git", "-C", str(checkout_dir), "rev-parse", ref], timeout=15).stdout.strip()
    head_commit = _run_command(["git", "-C", str(checkout_dir), "rev-parse", "HEAD"], check=False, timeout=15).stdout.strip()
    if head_commit != resolved_commit:
        _run_command(["git", "-C", str(checkout_dir), "checkout", "--detach", resolved_commit], timeout=120)

    ref_label = commit or git_ref or "origin/HEAD"
    source = ScenarioSource(
        repo_root=checkout_dir,
        commit=resolved_commit,
        ref_label=ref_label,
        content_fingerprint=resolved_commit[:12],
        repo_url=repo_url,
    )
    scenario["_scenario_source"] = source
    return source


def resolve_profile_path(profile: str) -> Path:
    candidate = Path(profile)
    if candidate.exists():
        return candidate.resolve()
    profile_path = SCENARIO_DIR / f"{profile}.toml"
    if profile_path.exists():
        return profile_path.resolve()
    raise FileNotFoundError(f"Benchmark scenario not found: {profile}")


def list_profiles() -> list[str]:
    return sorted(path.stem for path in SCENARIO_DIR.glob("*.toml"))


def list_scenarios() -> list[str]:
    return list_profiles()


def _resolve_scenario_relative_path(scenario: dict[str, Any], raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate

    scenario_file = scenario.get("_scenario_file")
    if isinstance(scenario_file, Path):
        local_candidate = scenario_file.parent / candidate
        if local_candidate.exists():
            return local_candidate

    repo_candidate = REPO_ROOT / candidate
    if repo_candidate.exists():
        return repo_candidate

    return candidate


def _validate_known_keys(path_label: str, payload: dict[str, Any], supported: set[str]) -> None:
    unsupported = sorted(set(payload) - supported)
    if unsupported:
        raise ValueError(f"{path_label} has unsupported keys: {', '.join(unsupported)}")


def _validate_raw_profile(raw_suite: dict[str, Any]) -> None:
    _validate_known_keys("benchmark profile", raw_suite, SUPPORTED_TOP_LEVEL_KEYS)

    suite_meta = raw_suite.get("suite", {})
    if not isinstance(suite_meta, dict):
        raise ValueError("[suite] must be a table")
    _validate_known_keys("[suite]", suite_meta, SUPPORTED_SUITE_KEYS)

    defaults = raw_suite.get("defaults", {})
    if defaults:
        if not isinstance(defaults, dict):
            raise ValueError("[defaults] must be a table")
        _validate_known_keys("[defaults]", defaults, SUPPORTED_DEFAULT_SECTION_KEYS)
        _validate_section_tables("[defaults]", defaults)

    scenarios = raw_suite.get("scenario", [])
    if scenarios and not isinstance(scenarios, list):
        raise ValueError("[[scenario]] must be declared as an array of tables")
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise ValueError(f"[[scenario]] entry #{index + 1} must be a table")
        _validate_known_keys(f"[[scenario]] #{index + 1}", scenario, SUPPORTED_SCENARIO_KEYS)
        _validate_section_tables(f"[[scenario]] #{index + 1}", scenario)


def _validate_section_tables(path_label: str, payload: dict[str, Any]) -> None:
    if "setup" in payload:
        _validate_known_keys(f"{path_label}.setup", payload["setup"], SUPPORTED_SETUP_KEYS)
    if "build" in payload:
        _validate_known_keys(f"{path_label}.build", payload["build"], SUPPORTED_BUILD_KEYS)
    if "runtime" in payload:
        runtime = payload["runtime"]
        _validate_known_keys(f"{path_label}.runtime", runtime, SUPPORTED_RUNTIME_KEYS)
        if "gunicorn" in runtime:
            _validate_known_keys(f"{path_label}.runtime.gunicorn", runtime["gunicorn"], SUPPORTED_GUNICORN_KEYS)
        if "granian" in runtime:
            _validate_known_keys(f"{path_label}.runtime.granian", runtime["granian"], SUPPORTED_GRANIAN_KEYS)
        if "uvicorn" in runtime:
            _validate_known_keys(f"{path_label}.runtime.uvicorn", runtime["uvicorn"], SUPPORTED_UVICORN_KEYS)
    if "gateway" in payload:
        _validate_known_keys(f"{path_label}.gateway", payload["gateway"], SUPPORTED_GATEWAY_KEYS)
    if "load" in payload:
        load = payload["load"]
        _validate_known_keys(f"{path_label}.load", load, SUPPORTED_LOAD_KEYS)
        workload = load.get("workload")
        if workload is not None:
            if not isinstance(workload, dict):
                raise ValueError(f"{path_label}.load.workload must be a table")
            _validate_known_keys(f"{path_label}.load.workload", workload, SUPPORTED_WORKLOAD_KEYS)
            endpoint_overrides = workload.get("endpoints", {})
            if endpoint_overrides is not None and not isinstance(endpoint_overrides, dict):
                raise ValueError(f"{path_label}.load.workload.endpoints must be a table")
            for endpoint_name, endpoint_payload in endpoint_overrides.items():
                if not isinstance(endpoint_payload, dict):
                    raise ValueError(f"{path_label}.load.workload.endpoints.{endpoint_name} must be a table")
                _validate_known_keys(f"{path_label}.load.workload.endpoints.{endpoint_name}", endpoint_payload, SUPPORTED_WORKLOAD_ENDPOINT_KEYS)
    if "measurement" in payload:
        _validate_known_keys(f"{path_label}.measurement", payload["measurement"], SUPPORTED_MEASUREMENT_KEYS)
    if "requests" in payload:
        _validate_known_keys(f"{path_label}.requests", payload["requests"], SUPPORTED_REQUESTS_KEYS)
    if "profiling" in payload:
        _validate_known_keys(f"{path_label}.profiling", payload["profiling"], SUPPORTED_PROFILING_KEYS)
    if "execution" in payload:
        _validate_known_keys(f"{path_label}.execution", payload["execution"], SUPPORTED_EXECUTION_KEYS)


def _validate_stop_condition(load_config: dict[str, Any]) -> None:
    if not load_config.get("run_time") and not load_config.get("request_count"):
        raise ValueError("Scenario load config must define at least one of run_time or request_count")


def _parse_run_time_seconds(run_time: str | None) -> int:
    """Parse Locust run_time (e.g. '180s', '5m', '1h') to seconds. Returns 0 if missing or unparseable."""
    if not run_time or not str(run_time).strip():
        return 0
    s = str(run_time).strip().lower()
    if s.endswith("s") and s[:-1].isdigit():
        return int(s[:-1])
    if s.endswith("m") and s[:-1].isdigit():
        return int(s[:-1]) * 60
    if s.endswith("h") and s[:-1].isdigit():
        return int(s[:-1]) * 3600
    if s.isdigit():
        return int(s)
    return 0


def _validate_scenario(scenario: dict[str, Any]) -> None:
    for field in ("name", "description", "scenario_type"):
        if not scenario.get(field):
            raise ValueError(f"Scenario missing required field '{field}'")

    for block in ("setup", "runtime", "load", "measurement", "profiling"):
        if not isinstance(scenario.get(block), dict):
            raise ValueError(f"Scenario '{scenario['name']}' missing required block [{block}]")

    setup = scenario["setup"]
    for required in ("target_kind", "auth_mode", "plugins_enabled"):
        if required not in setup:
            raise ValueError(f"Scenario '{scenario['name']}' missing setup.{required}")
    if setup.get("target_kind") != "gateway":
        raise ValueError(f"Scenario '{scenario['name']}' setup.target_kind must be 'gateway'")
    expected_mcp_runtime = setup.get("expected_mcp_runtime")
    if expected_mcp_runtime is not None and expected_mcp_runtime not in {"python", "rust"}:
        raise ValueError(f"Scenario '{scenario['name']}' setup.expected_mcp_runtime must be 'python' or 'rust'")
    expected_mcp_runtime_mode = setup.get("expected_mcp_runtime_mode")
    if expected_mcp_runtime_mode is not None and not str(expected_mcp_runtime_mode).strip():
        raise ValueError(f"Scenario '{scenario['name']}' setup.expected_mcp_runtime_mode must be non-empty when provided")
    expected_a2a_runtime = setup.get("expected_a2a_runtime")
    if expected_a2a_runtime is not None and expected_a2a_runtime not in {"python", "rust"}:
        raise ValueError(f"Scenario '{scenario['name']}' setup.expected_a2a_runtime must be 'python' or 'rust'")

    runtime = scenario["runtime"]
    if runtime.get("http_server") not in {"gunicorn", "granian", "uvicorn"}:
        raise ValueError(f"Scenario '{scenario['name']}' has unsupported http_server '{runtime.get('http_server')}'")

    load = scenario["load"]
    locustfile = load.get("locustfile")
    if not locustfile:
        raise ValueError(f"Scenario '{scenario['name']}' must define load.locustfile")
    locustfile_path = _resolve_scenario_relative_path(scenario, str(locustfile))
    if not locustfile_path.exists():
        raise ValueError(f"Scenario '{scenario['name']}' locustfile does not exist: {locustfile_path}")
    if load.get("target_service", "nginx") not in {"nginx", "gateway"}:
        raise ValueError(f"Scenario '{scenario['name']}' load.target_service must be 'nginx' or 'gateway'")
    _validate_stop_condition(load)
    workload = load.get("workload")
    if workload is not None:
        selection = str(workload.get("selection", "weighted-random"))
        if selection not in SUPPORTED_WORKLOAD_SELECTIONS:
            raise ValueError(
                f"Scenario '{scenario['name']}' load.workload.selection must be one of: {', '.join(sorted(SUPPORTED_WORKLOAD_SELECTIONS))}"
            )
        known_requests = benchmark_request_names()
        fallback_endpoint = str(workload.get("fallback_endpoint", "") or "")
        if fallback_endpoint and fallback_endpoint not in known_requests:
            raise ValueError(f"Scenario '{scenario['name']}' load.workload.fallback_endpoint is unknown: {fallback_endpoint}")
        for endpoint_name, endpoint_payload in (workload.get("endpoints", {}) or {}).items():
            if endpoint_name not in known_requests:
                raise ValueError(f"Scenario '{scenario['name']}' load.workload references unknown endpoint: {endpoint_name}")
            weight = endpoint_payload.get("weight")
            if weight is not None and int(weight) < 0:
                raise ValueError(f"Scenario '{scenario['name']}' load.workload endpoint '{endpoint_name}' must use a non-negative weight")

    build = scenario.get("build", {})
    rebuild_policy = str(build.get("rebuild_policy", "never"))
    if rebuild_policy not in SUPPORTED_REBUILD_POLICIES:
        raise ValueError(f"Scenario '{scenario['name']}' rebuild_policy must be one of: {', '.join(sorted(SUPPORTED_REBUILD_POLICIES))}")
    if "git_remote" in build or "git_branch" in build:
        raise ValueError(f"Scenario '{scenario['name']}' must use build.repo_url/build.git_ref instead of git_remote/git_branch")
    repo_url, git_ref, commit = _scenario_source_ref(build)
    if git_ref is None and commit is not None and len(commit) < 7:
        raise ValueError(f"Scenario '{scenario['name']}' build.git_commit must be a valid git sha or ref")
    if (git_ref or commit) and not repo_url:
        raise ValueError(f"Scenario '{scenario['name']}' must define build.repo_url when using build.git_ref or build.git_commit")

    measurement = scenario["measurement"]
    measure_seconds = int(measurement.get("measure_seconds", 0) or 0)
    profile_seconds = int(measurement.get("profile_seconds", 0) or 0)
    if measure_seconds and profile_seconds and profile_seconds > measure_seconds:
        raise ValueError(f"Scenario '{scenario['name']}' profile_seconds must be <= measure_seconds")

    profiling = scenario["profiling"]
    allowed_tools = {"py_spy", "memray", "process_stats"}
    tools = set(profiling.get("tools", []) or [])
    if profiling.get("py_spy"):
        tools.add("py_spy")
    invalid = sorted(tools - allowed_tools)
    if invalid:
        raise ValueError(f"Scenario '{scenario['name']}' has unsupported profiling tools: {', '.join(invalid)}")

    execution = scenario.get("execution", {})
    if execution.get("retry_enabled") and int(execution.get("max_attempts", 1) or 1) < 2:
        raise ValueError(f"Scenario '{scenario['name']}' retry_enabled requires execution.max_attempts >= 2")

    for plugin_name, config in (scenario.get("plugins", {}) or {}).items():
        mode = (config or {}).get("mode", "auto")
        if mode not in {"off", "python", "rust", "auto"}:
            raise ValueError(f"Scenario '{scenario['name']}' plugin '{plugin_name}' has invalid mode '{mode}'")


def resolve_suite(profile_path: Path, smoke: bool = False) -> dict[str, Any]:
    raw_suite = _load_toml(profile_path)
    _validate_raw_profile(raw_suite)
    suite_meta = raw_suite.get("suite", {})
    defaults = raw_suite.get("defaults", {})
    scenarios = raw_suite.get("scenario", [])

    if not suite_meta.get("name"):
        raise ValueError("Benchmark suite missing [suite].name")
    if not scenarios:
        raise ValueError("Benchmark suite must declare at least one [[scenario]]")

    resolved_scenarios = []
    for index, raw_scenario in enumerate(scenarios):
        scenario = _deep_merge(defaults, raw_scenario)
        scenario["_order"] = index
        scenario["_scenario_file"] = profile_path
        if smoke:
            scenario.setdefault("load", {})
            scenario["load"]["users"] = 1
            scenario["load"]["spawn_rate"] = min(int(scenario["load"].get("spawn_rate", 1)), 1)
            scenario["load"]["run_time"] = "5s"
            scenario.setdefault("measurement", {})
            scenario["measurement"]["warmup_seconds"] = 0
            scenario["measurement"]["measure_seconds"] = 3
            scenario["measurement"]["profile_seconds"] = 0
            scenario["measurement"]["cooldown_seconds"] = 0
        _validate_scenario(scenario)
        resolved_scenarios.append(scenario)

    names = [scenario["name"] for scenario in resolved_scenarios]
    if len(names) != len(set(names)):
        raise ValueError("Scenario names must be unique within a suite")

    suite_meta.setdefault("flamegraph_enabled", True)
    suite_meta.setdefault("continue_on_failure", False)
    suite_meta.setdefault("save_intermediate_artifacts", True)
    return {"suite": suite_meta, "defaults": defaults, "scenarios": resolved_scenarios}


def resolve_scenario_paths(selection: str | None = None, run_all: bool = False) -> list[Path]:
    if run_all:
        scenario_paths = sorted(SCENARIO_DIR.glob("*.toml"))
        if not scenario_paths:
            raise FileNotFoundError(f"No benchmark scenarios found under {SCENARIO_DIR}")
        return [path.resolve() for path in scenario_paths]
    if not selection:
        raise ValueError("Provide --scenario or --all")
    return [resolve_profile_path(selection)]


def resolve_scenario_collection(selection: str | None = None, run_all: bool = False, smoke: bool = False) -> tuple[str, list[Path], dict[str, Any]]:
    scenario_paths = resolve_scenario_paths(selection=selection, run_all=run_all)
    suites = [resolve_suite(path, smoke=smoke) for path in scenario_paths]
    if len(suites) == 1:
        return scenario_paths[0].stem, scenario_paths, suites[0]

    combined_suite = {
        "name": "contextforge-scenarios",
        "description": "Combined execution of all committed benchmark scenarios",
        "output_root": str(DEFAULT_OUTPUT_ROOT),
        "continue_on_failure": False,
        "save_intermediate_artifacts": True,
        "flamegraph_enabled": False,
    }
    for suite in suites:
        combined_suite["continue_on_failure"] = bool(suite["suite"].get("continue_on_failure", False)) or bool(combined_suite["continue_on_failure"])
        if suite["suite"].get("output_root"):
            combined_suite["output_root"] = str(suite["suite"]["output_root"])
    scenarios = [scenario for suite in suites for scenario in suite["scenarios"]]
    return "all-scenarios", scenario_paths, {"suite": combined_suite, "scenarios": scenarios}


def _scenario_env(scenario: dict[str, Any]) -> dict[str, str]:
    load = scenario.get("load", {})
    requests = scenario.get("requests", {})
    workload = load.get("workload")
    profiling = scenario.get("profiling", {})
    measurement = scenario.get("measurement", {})
    runtime = scenario.get("runtime", {})
    setup = scenario.get("setup", {})
    target_service = load.get("target_service", "nginx")
    host = "http://nginx:80" if target_service == "nginx" else "http://gateway:4444"
    env = {
        "LOADTEST_HOST": str(load.get("host") or host),
        "LOADTEST_USERS": str(load.get("users", "")),
        "LOADTEST_SPAWN_RATE": str(load.get("spawn_rate", "")),
        "LOADTEST_RUN_TIME": str(load.get("run_time", "")),
        "LOADTEST_REQUEST_COUNT": str(load.get("request_count", "")),
        "LOADTEST_SEED": str(load.get("seed", "")),
        "LOCUST_USERS": str(load.get("users", "")),
        "LOCUST_SPAWN_RATE": str(load.get("spawn_rate", "")),
        "LOCUST_RUN_TIME": str(load.get("run_time", "")),
        "BENCHMARK_HTTP_SERVER": str(runtime.get("http_server", "")),
        "BENCHMARK_AUTH_MODE": str(setup.get("auth_mode", "")),
        "BENCHMARK_WARMUP_SECONDS": str(measurement.get("warmup_seconds", "")),
        "BENCHMARK_MEASURE_SECONDS": str(measurement.get("measure_seconds", "")),
        "BENCHMARK_PROFILE_SECONDS": str(measurement.get("profile_seconds", "")),
        "BENCHMARK_COOLDOWN_SECONDS": str(measurement.get("cooldown_seconds", "")),
        "BENCH_REQUEST_COUNT": str(load.get("request_count", "")),
        "BENCH_SEED": str(load.get("seed", "")),
        "BENCH_TARGET_SERVICE": str(target_service),
        "BENCH_PYSPY_REQUIRED": str(profiling.get("required", False)).lower(),
        "SSO_KEYCLOAK_ROLE_MAPPINGS": "{}",
    }
    if workload is not None:
        env["BENCH_WORKLOAD"] = json.dumps(workload, sort_keys=True)
    else:
        env.update(
            {
                "BENCH_ENABLED_GROUPS": json.dumps(requests.get("enabled_groups", [])),
                "BENCH_DISABLED_GROUPS": json.dumps(requests.get("disabled_groups", [])),
                "BENCH_ENABLED_ENDPOINTS": json.dumps(requests.get("enabled_endpoints", [])),
                "BENCH_DISABLED_ENDPOINTS": json.dumps(requests.get("disabled_endpoints", [])),
                "BENCH_ENABLED_TAGS": json.dumps(requests.get("enabled_tags", [])),
                "BENCH_DISABLED_TAGS": json.dumps(requests.get("disabled_tags", [])),
                "BENCH_INCLUDE_ADMIN_ENDPOINTS": str(requests.get("include_admin_endpoints", False)).lower(),
                "BENCH_INCLUDE_MCP_ENDPOINTS": str(requests.get("include_mcp_endpoints", False)).lower(),
                "BENCH_INCLUDE_RESOURCE_ENDPOINTS": str(requests.get("include_resource_endpoints", False)).lower(),
                "BENCH_INCLUDE_PROMPT_ENDPOINTS": str(requests.get("include_prompt_endpoints", False)).lower(),
                "BENCH_INCLUDE_TOOL_ENDPOINTS": str(requests.get("include_tool_endpoints", False)).lower(),
            }
        )
    for key, value in (load.get("env", {}) or {}).items():
        env[str(key)] = str(value)
    return env


def _compose_env_args(env: dict[str, str]) -> list[str]:
    args: list[str] = []
    for key, value in sorted(env.items()):
        args.extend(["-e", f"{key}={value}"])
    return args


def _binary_is_podman_shim(binary_name: str) -> bool:
    binary_path = shutil.which(binary_name)
    if not binary_path:
        return False
    try:
        resolved = Path(binary_path).resolve()
    except OSError:
        resolved = Path(binary_path)
    return resolved.name.startswith("podman")


def _compose_candidates(preferred_runtime: str) -> tuple[tuple[str, ...], ...]:
    docker_is_podman_shim = _binary_is_podman_shim("docker")
    if preferred_runtime == "podman":
        # Prefer the docker CLI when it is a podman shim because it suppresses
        # provider-wrapper noise while still exercising the podman backend.
        if docker_is_podman_shim:
            return (("docker", "compose"), ("podman", "compose"), ("podman-compose",))
        return (("podman", "compose"), ("podman-compose",), ("docker", "compose"))
    if preferred_runtime == "docker":
        return (("docker", "compose"), ("podman", "compose"), ("podman-compose",))
    return (("docker", "compose"), ("podman", "compose"), ("podman-compose",))


def _detect_runtime() -> ContainerRuntime:
    preferred_runtime = (os.environ.get("CONTAINER_RUNTIME") or "").strip().lower()
    candidates = _compose_candidates(preferred_runtime)
    failures: list[str] = []
    for candidate in candidates:
        engine = "podman" if candidate[0].startswith("podman") else "docker"
        uses_podman_backend = engine == "podman" or _binary_is_podman_shim(engine)
        if uses_podman_backend and not _ensure_podman_ready():
            failures.append(f"{' '.join(candidate)}: podman backend is not ready")
            continue
        _emit_progress(f"checking runtime candidate {' '.join(candidate)}")
        try:
            result = _run_command([*candidate, "version"], check=False, timeout=10)
        except RuntimeError:
            failures.append(f"{' '.join(candidate)}: command failed")
            continue
        if result.returncode == 0:
            if candidate[0] == "podman-compose":
                return ContainerRuntime(engine="podman", compose_cmd=tuple(candidate))
            try:
                engine_check = _run_command([engine, "info"], check=False, timeout=10)
            except RuntimeError:
                failures.append(f"{' '.join(candidate)}: engine info failed")
                continue
            if engine_check.returncode == 0:
                return ContainerRuntime(engine=engine, compose_cmd=tuple(candidate))
            failures.append(f"{' '.join(candidate)}: engine info failed: {(engine_check.stderr or engine_check.stdout).strip()}")
            continue
        failures.append(f"{' '.join(candidate)}: {(result.stderr or result.stdout).strip()}")
    details = "; ".join(failures) if failures else "no candidates tried"
    raise RuntimeError(f"No compose command available (expected docker compose, podman compose, or podman-compose). Details: {details}")


def _compose_base_args(runtime: ContainerRuntime, project_name: str, compose_path: Path) -> list[str]:
    return [*runtime.compose_cmd, "-p", project_name, "-f", str(compose_path)]


def _podman_machine_entries() -> list[dict[str, Any]]:
    result = _run_command(["podman", "machine", "list", "--format", "json"], check=False, timeout=10)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _podman_connection_entries() -> list[dict[str, Any]]:
    result = _run_command(["podman", "system", "connection", "list", "--format", "json"], check=False, timeout=10)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _podman_info_ok() -> bool:
    result = _run_command(["podman", "info"], check=False, timeout=10)
    return result.returncode == 0


def _set_podman_connection_default(name: str) -> bool:
    result = _run_command(["podman", "system", "connection", "default", name], check=False, timeout=10)
    return result.returncode == 0


def _start_podman_machine(name: str) -> bool:
    result = _run_command(["podman", "machine", "start", name], check=False, timeout=60)
    return result.returncode == 0 or "already running" in ((result.stderr or "") + (result.stdout or "")).lower()


def _ensure_podman_ready() -> bool:
    if shutil.which("podman") is None:
        return False
    if _podman_info_ok():
        return True

    machines = _podman_machine_entries()
    connections = {str(entry.get("Name", "")): entry for entry in _podman_connection_entries()}
    running_names = [str(entry.get("Name", "")) for entry in machines if entry.get("Running")]
    candidate_names = [name for name in running_names if name in connections]
    if not candidate_names:
        default_names = [str(entry.get("Name", "")) for entry in machines if entry.get("Default")]
        candidate_names = [name for name in default_names if name]
    for name in candidate_names:
        if name in connections:
            if _set_podman_connection_default(name):
                if _podman_info_ok():
                    return True

    for entry in machines:
        name = str(entry.get("Name", ""))
        if not name:
            continue
        if not entry.get("Running"):
            _start_podman_machine(name)
        if name in connections:
            if _set_podman_connection_default(name):
                if _podman_info_ok():
                    return True
    return False


def _run_command(args: list[str], env: dict[str, str] | None = None, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["PODMAN_COMPOSE_WARNING_LOGS"] = "false"
    if env:
        merged_env.update(env)
    try:
        result = subprocess.run(args, cwd=str(REPO_ROOT), env=merged_env, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        result = subprocess.CompletedProcess(args=args, returncode=124, stdout=stdout, stderr=stderr or f"Command timed out after {timeout}s")
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-4000:])
    return result


def _run_compose(
    compose_args: list[str],
    extra: list[str],
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_command(compose_args + extra, env=env, check=check, timeout=timeout)


def _scenario_image_name(scenario: dict[str, Any]) -> str:
    build = _scenario_build(scenario)
    image_name = str(build.get("image_name", "mcpgateway/mcpgateway"))
    image_tag = str(build.get("image_tag", "latest"))
    source = scenario.get("_scenario_source")
    source_fingerprint = getattr(source, "content_fingerprint", "") or getattr(source, "commit", "")
    if source_fingerprint:
        image_tag = f"{image_tag}-{str(source_fingerprint)}"
    return f"{image_name}:{image_tag}"


def _ensure_benchmark_image(runtime: ContainerRuntime, scenario: dict[str, Any]) -> str:
    source = _ensure_scenario_source(scenario)
    image_name = _scenario_image_name(scenario)
    build = _scenario_build(scenario)
    rebuild_policy = str(build.get("rebuild_policy", "never"))
    inspect = _run_command([runtime.engine, "image", "inspect", image_name], check=False)
    image_exists = inspect.returncode == 0
    if rebuild_policy == "never":
        if not image_exists:
            raise RuntimeError(f"Required benchmark image not found and rebuild_policy=never: {image_name}")
        return image_name
    if rebuild_policy == "missing" and image_exists:
        return image_name

    _emit_progress(f"{scenario['name']}: building benchmark image {image_name} from {build.get('container_file', 'benchmarks/contextforge/Containerfile')}")
    build_context = _prepare_benchmark_build_context(source)
    container_file = _resolve_scenario_relative_path(scenario, str(build.get("container_file", "benchmarks/contextforge/Containerfile")))
    if not container_file.is_absolute():
        build_context_container_file = build_context / container_file
        container_file = build_context_container_file if build_context_container_file.exists() else (REPO_ROOT / container_file)
    if not container_file.exists():
        raise RuntimeError(f"Benchmark container file does not exist: {container_file}")
    cmd = [
        runtime.engine,
        "build",
        "-f",
        str(container_file),
        "--build-arg",
        f"ENABLE_RUST={'true' if build.get('rust_plugins', False) else 'false'}",
        "--build-arg",
        f"ENABLE_PROFILING={'true' if build.get('profiling_image', False) else 'false'}",
    ]
    for key, value in sorted(_scenario_build_args(build).items()):
        cmd.extend(["--build-arg", f"{key}={value}"])
    cmd.extend(["-t", image_name, str(build_context)])
    _run_command(cmd)
    _emit_progress(f"{scenario['name']}: finished building benchmark image {image_name}")
    return image_name


def _ensure_locust_image(runtime: ContainerRuntime) -> str:
    inspect = _run_command([runtime.engine, "image", "inspect", LOCUST_IMAGE], check=False)
    if inspect.returncode == 0:
        return LOCUST_IMAGE
    _emit_progress(f"pulling benchmark load image {LOCUST_IMAGE}")
    _run_command([runtime.engine, "pull", LOCUST_IMAGE])
    return LOCUST_IMAGE


def _nginx_benchmark_image_name(source: ScenarioSource) -> str:
    return f"mcpgateway/nginx-cache:benchmark-suite-{source.content_fingerprint}"


def _ensure_benchmark_nginx_image(runtime: ContainerRuntime, scenario: dict[str, Any]) -> str:
    source = _ensure_scenario_source(scenario)
    image_name = _nginx_benchmark_image_name(source)
    inspect = _run_command([runtime.engine, "image", "inspect", image_name], check=False)
    if inspect.returncode == 0:
        return image_name

    build_context = _prepare_benchmark_build_context(source)
    container_file = build_context / "infra" / "nginx" / "Dockerfile"
    _emit_progress(f"{scenario['name']}: building benchmark nginx image {image_name}")
    _run_command([runtime.engine, "build", "-f", str(container_file), "-t", image_name, str(container_file.parent)])
    return image_name


def _a2a_echo_benchmark_image_name(source: ScenarioSource) -> str:
    return f"mcpgateway/a2a-echo-agent:benchmark-suite-{source.content_fingerprint}"


def _ensure_benchmark_a2a_echo_image(runtime: ContainerRuntime, scenario: dict[str, Any]) -> str:
    source = _ensure_scenario_source(scenario)
    image_name = _a2a_echo_benchmark_image_name(source)
    inspect = _run_command([runtime.engine, "image", "inspect", image_name], check=False)
    if inspect.returncode == 0:
        return image_name

    build_context = _prepare_benchmark_build_context(source)
    build_root = build_context / "a2a-agents" / "go" / "a2a-echo-agent"
    dockerfile_path = build_root / "Dockerfile"
    if not dockerfile_path.exists():
        raise RuntimeError(f"A2A echo agent Dockerfile does not exist: {dockerfile_path}")
    _emit_progress(f"{scenario['name']}: building benchmark A2A echo image {image_name}")
    _run_command([runtime.engine, "build", "-f", str(dockerfile_path), "-t", image_name, str(build_root)])
    return image_name


def _render_plugin_config_for_scenario(scenario: dict[str, Any], output_path: Path, validate_only: bool = False) -> Path:
    if not scenario.get("setup", {}).get("plugins_enabled", False):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("plugin_dirs: []\nplugin_settings: {}\nplugins: []\n", encoding="utf-8")
        return output_path
    if validate_only:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# validation placeholder; rendered at execution time\n", encoding="utf-8")
        return output_path

    from benchmarks.contextforge.render_benchmark_config import render_plugin_config  # pylint: disable=import-outside-toplevel

    return render_plugin_config(scenario, output_path)


def _compose_environment_dict(values: Any) -> dict[str, str]:
    if isinstance(values, dict):
        return {str(key): str(value) for key, value in values.items()}
    environment: dict[str, str] = {}
    for entry in values or []:
        if not isinstance(entry, str):
            continue
        if "=" not in entry:
            environment[entry] = ""
            continue
        key, value = entry.split("=", 1)
        environment[key] = value
    return environment


def _resolve_compose_env_value(value: str, env: dict[str, str]) -> str:
    text = str(value)
    while "${" in text:
        start = text.find("${")
        depth = 0
        end = -1
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end == -1:
            break
        expression = text[start + 2 : end]
        if ":-" in expression:
            name, default = expression.split(":-", 1)
            name = name.strip()
            replacement = env.get(name, "")
            if replacement == "":
                replacement = _resolve_compose_env_value(default, env)
        else:
            replacement = env.get(expression.strip(), "")
        text = f"{text[:start]}{replacement}{text[end + 1:]}"
    return text


def _merge_compose_environment(values: Any, overrides: dict[str, str]) -> Any:
    if isinstance(values, dict):
        merged = {str(key): str(value) for key, value in values.items()}
        merged.update({str(key): str(value) for key, value in overrides.items()})
        return merged

    interpolation_env = {str(key): str(value) for key, value in os.environ.items()}
    interpolation_env.update({str(key): str(value) for key, value in overrides.items()})
    entries: list[str] = []
    existing_keys: dict[str, int] = {}
    for entry in values or []:
        if not isinstance(entry, str):
            continue
        if "=" in entry:
            key, raw_value = entry.split("=", 1)
            resolved_value = _resolve_compose_env_value(raw_value, interpolation_env)
            if raw_value.strip().startswith("${") and resolved_value == "" and key not in overrides:
                continue
            entry = f"{key}={resolved_value}"
        else:
            key = entry
        existing_keys[str(key)] = len(entries)
        entries.append(entry)

    for key, value in overrides.items():
        rendered = f"{key}={value}"
        if key in existing_keys:
            entries[existing_keys[key]] = rendered
        else:
            entries.append(rendered)
    return entries


def _normalize_compose_volume_entry(entry: Any, source_root: Path) -> Any:
    if not isinstance(entry, str):
        return entry
    parts = entry.split(":")
    if not parts:
        return entry
    source = parts[0]
    if source.startswith("${") or source.startswith("/"):
        return entry
    if source.startswith(".") or "/" in source:
        parts[0] = str((source_root / source).resolve())
        return ":".join(parts)
    return entry


def _write_compose_override(scenario: dict[str, Any], scenario_dir: Path, image_name: str, nginx_image_name: str, a2a_echo_image_name: str, source_root: Path) -> Path:
    import yaml  # pylint: disable=import-outside-toplevel

    runtime = scenario.get("runtime", {}) or {}
    gunicorn_runtime = runtime.get("gunicorn", {}) or {}
    granian_runtime = runtime.get("granian", {}) or {}
    uvicorn_runtime = runtime.get("uvicorn", {}) or {}
    gateway = scenario.get("gateway", {}) or {}
    setup = scenario.get("setup", {}) or {}
    scenario_mount = str(scenario_dir.resolve())

    environment: dict[str, str] = {
        "IMAGE_LOCAL": image_name,
        "HTTP_SERVER": str(runtime.get("http_server", "gunicorn")),
        "TRANSPORT_TYPE": str(runtime.get("transport_type", "streamablehttp")),
        "PLUGINS_ENABLED": "true" if setup.get("plugins_enabled", False) else "false",
        "PLUGINS_CONFIG_FILE": "/mnt/bench/plugins.yaml",
        "AUTH_REQUIRED": "false" if setup.get("auth_mode", "none") == "none" else "true",
        "MCP_REQUIRE_AUTH": "false" if setup.get("auth_mode", "none") == "none" else "true",
        "MCP_CLIENT_AUTH_ENABLED": "false" if setup.get("auth_mode", "none") == "none" else "true",
        "TRUST_PROXY_AUTH": str(gateway.get("trust_proxy_auth", False)).lower(),
        "DISABLE_ACCESS_LOG": str(gateway.get("disable_access_log", True)).lower(),
        "TEMPLATES_AUTO_RELOAD": str(gateway.get("templates_auto_reload", False)).lower(),
        "STRUCTURED_LOGGING_DATABASE_ENABLED": str(gateway.get("structured_logging_database_enabled", False)).lower(),
        "SQLALCHEMY_ECHO": str(gateway.get("sqlalchemy_echo", False)).lower(),
        "LOG_LEVEL": str(gateway.get("log_level", "ERROR")),
        "SSO_KEYCLOAK_ROLE_MAPPINGS": "{}",
        "BENCHMARK_PLUGIN_TIMING_ENABLED": "true" if setup.get("plugins_enabled", False) else "false",
        "BENCHMARK_PLUGIN_TIMING_DIR": "/mnt/bench/plugin_timing",
        "BENCHMARK_PLUGIN_TIMING_FILE": "/mnt/bench/plugin_timing_live.json",
    }
    for key, value in _compose_environment_dict(gateway.get("environment", {})).items():
        environment[str(key)] = str(value)
    gunicorn_env_map = {
        "workers": "GUNICORN_WORKERS",
        "timeout": "GUNICORN_TIMEOUT",
        "graceful_timeout": "GUNICORN_GRACEFUL_TIMEOUT",
        "keep_alive": "GUNICORN_KEEPALIVE",
        "max_requests": "GUNICORN_MAX_REQUESTS",
        "max_requests_jitter": "GUNICORN_MAX_REQUESTS_JITTER",
        "backlog": "GUNICORN_BACKLOG",
        "preload_app": "GUNICORN_PRELOAD_APP",
        "dev_mode": "DEVELOPER_MODE",
    }
    granian_env_map = {
        "workers": "GRANIAN_WORKERS",
        "runtime_mode": "GRANIAN_RUNTIME_MODE",
        "runtime_threads": "GRANIAN_RUNTIME_THREADS",
        "blocking_threads": "GRANIAN_BLOCKING_THREADS",
        "http": "GRANIAN_HTTP",
        "loop": "GRANIAN_LOOP",
        "task_impl": "GRANIAN_TASK_IMPL",
        "http1_pipeline_flush": "GRANIAN_HTTP1_PIPELINE_FLUSH",
        "http1_buffer_size": "GRANIAN_HTTP1_BUFFER_SIZE",
        "backlog": "GRANIAN_BACKLOG",
        "backpressure": "GRANIAN_BACKPRESSURE",
        "respawn_failed": "GRANIAN_RESPAWN_FAILED",
        "workers_lifetime": "GRANIAN_WORKERS_LIFETIME",
        "workers_max_rss": "GRANIAN_WORKERS_MAX_RSS",
        "dev_mode": "DEVELOPER_MODE",
        "log_level": "LOG_LEVEL",
    }
    uvicorn_env_map = {
        "workers": "UVICORN_WORKERS",
        "loop": "UVICORN_LOOP",
        "http": "UVICORN_HTTP",
        "backlog": "UVICORN_BACKLOG",
        "timeout_keep_alive": "UVICORN_TIMEOUT_KEEP_ALIVE",
        "limit_max_requests": "UVICORN_LIMIT_MAX_REQUESTS",
        "log_level": "LOG_LEVEL",
        "dev_mode": "DEVELOPER_MODE",
    }
    for key, env_name in gunicorn_env_map.items():
        if key in gunicorn_runtime:
            environment[env_name] = str(gunicorn_runtime[key])
    for key, env_name in granian_env_map.items():
        if key not in granian_runtime:
            continue
        value = granian_runtime[key]
        if key in {"workers_lifetime", "workers_max_rss"}:
            try:
                if int(value) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        environment[env_name] = str(value)
    for key, env_name in uvicorn_env_map.items():
        if key in uvicorn_runtime:
            environment[env_name] = str(uvicorn_runtime[key])

    base_payload = yaml.safe_load((source_root / "docker-compose.yml").read_text(encoding="utf-8"))
    selected_services = ["postgres", "redis", "pgbouncer", "gateway"]
    if scenario.get("load", {}).get("target_service", "nginx") == "nginx":
        selected_services.append("nginx")
    if _scenario_uses_fast_time_fixture(scenario):
        selected_services.extend(["fast_time_server", "register_fast_time"])
    if _scenario_uses_a2a_fixture(scenario):
        selected_services.extend(["a2a_echo_agent", "register_a2a_echo"])
    compose_payload = {
        "services": {name: deepcopy(base_payload["services"][name]) for name in selected_services},
        "networks": deepcopy(base_payload.get("networks", {})),
        "volumes": deepcopy(base_payload.get("volumes", {})),
    }

    for name, service in compose_payload["services"].items():
        service.pop("profiles", None)
        service.pop("ports", None)
        service.pop("build", None)
        service.pop("deploy", None)
        if "volumes" in service:
            service["volumes"] = [_normalize_compose_volume_entry(entry, source_root) for entry in service.get("volumes", [])]
        if name in {"gateway", "nginx", "a2a_echo_agent"}:
            if name == "gateway":
                service["image"] = image_name
            elif name == "nginx":
                service["image"] = nginx_image_name
            else:
                service["image"] = a2a_echo_image_name

    gateway_service = compose_payload["services"]["gateway"]
    gateway_service["cap_add"] = ["SYS_PTRACE"]
    gateway_service["security_opt"] = ["seccomp:unconfined"]
    gateway_service["environment"] = _merge_compose_environment(gateway_service.get("environment", []), environment)
    gateway_volumes = list(gateway_service.get("volumes", []))
    gateway_volumes.append(f"{scenario_mount}:/mnt/bench")
    gateway_service["volumes"] = gateway_volumes

    override_path = scenario_dir / "docker-compose.benchmark.yml"
    override_path.write_text(yaml.safe_dump(compose_payload, sort_keys=False), encoding="utf-8")
    return override_path


def _wait_for_gateway_health(compose_args: list[str], timeout_seconds: int = 45) -> bool:
    command = (
        "python3 - <<'PY'\n"
        "import json\n"
        "import sys\n"
        "import urllib.request\n"
        "try:\n"
        "    resp = urllib.request.urlopen('http://127.0.0.1:4444/health', timeout=2)\n"
        "    data = json.loads(resp.read())\n"
        "    print(data.get('status', 'unknown'))\n"
        "    sys.exit(0 if data.get('status') == 'healthy' else 1)\n"
        "except Exception as exc:\n"
        "    print(f'health probe error: {type(exc).__name__}: {exc}')\n"
        "    sys.exit(1)\n"
        "PY"
    )
    deadline = time.time() + timeout_seconds
    started_at = time.time()
    last_reported_second = -1
    while time.time() < deadline:
        result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=10)
        if result.returncode == 0:
            return True
        elapsed = int(time.time() - started_at)
        if elapsed != last_reported_second and elapsed % 5 == 0:
            last_reported_second = elapsed
            detail = _compose_probe_detail(result, "gateway health probe still failing")
            _emit_progress(f"gateway: waiting for /health ({elapsed}s/{timeout_seconds}s) - {detail}")
        time.sleep(1)
    return False


def _benchmark_registration_probe(compose_args: list[str], token: str) -> tuple[bool, str]:
    command = (
        "python3 - <<'PY'\n"
        "import json, sys, urllib.request\n"
        "from urllib.error import HTTPError, URLError\n"
        f"token = {token!r}\n"
        "headers = {'Authorization': f'Bearer {token}'}\n"
        "def fetch(path):\n"
        "    req = urllib.request.Request(f'http://127.0.0.1:4444{path}', headers=headers)\n"
        "    with urllib.request.urlopen(req, timeout=3) as response:\n"
        "        return json.loads(response.read().decode('utf-8'))\n"
        "try:\n"
        "    servers = fetch('/servers')\n"
        "except HTTPError as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'HTTPError: {exc.code} {exc.reason}'}))\n"
        "    sys.exit(1)\n"
        "except URLError as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'URLError: {exc.reason}'}))\n"
        "    sys.exit(1)\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'{type(exc).__name__}: {exc}'}))\n"
        "    sys.exit(1)\n"
        "fast_time_server = next((server for server in servers if server.get('name') == 'Fast Time Server'), None)\n"
        "associated_tools = list(fast_time_server.get('associatedTools') or []) if fast_time_server else []\n"
        "associated_resources = list(fast_time_server.get('associatedResources') or []) if fast_time_server else []\n"
        "associated_prompts = list(fast_time_server.get('associatedPrompts') or []) if fast_time_server else []\n"
        "ready = bool(fast_time_server) and len(associated_tools) >= 2 and len(associated_resources) >= 1 and len(associated_prompts) >= 1\n"
        "print(json.dumps({'ready': ready, 'server_found': bool(fast_time_server), 'associated_tools': associated_tools, 'associated_resources_count': len(associated_resources), 'associated_prompts_count': len(associated_prompts)}))\n"
        "sys.exit(0 if ready else 1)\n"
        "PY"
    )
    result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=10)
    detail = _compose_probe_detail(result, "registration probe not ready")
    return result.returncode == 0, detail


def _wait_for_benchmark_registration(runtime: ContainerRuntime, compose_args: list[str], timeout_seconds: int = 90) -> tuple[bool, str]:
    token = _benchmark_token(runtime, compose_args)
    deadline = time.time() + timeout_seconds
    started_at = time.time()
    last_reported_second = -1
    last_detail = "registration probe not ready"
    while time.time() < deadline:
        ready, detail = _benchmark_registration_probe(compose_args, token)
        if ready:
            return True, detail
        last_detail = detail or last_detail
        elapsed = int(time.time() - started_at)
        if elapsed != last_reported_second and elapsed % 5 == 0:
            last_reported_second = elapsed
            _emit_progress(f"register_fast_time: waiting for benchmark objects ({elapsed}s/{timeout_seconds}s) - {last_detail}")
        time.sleep(1)
    return False, last_detail


def _a2a_registration_probe(compose_args: list[str], token: str) -> tuple[bool, str]:
    command = (
        "python3 - <<'PY'\n"
        "import json, sys, urllib.request\n"
        "from urllib.error import HTTPError, URLError\n"
        f"token = {token!r}\n"
        "headers = {'Authorization': f'Bearer {token}'}\n"
        "req = urllib.request.Request('http://127.0.0.1:4444/a2a', headers=headers)\n"
        "try:\n"
        "    with urllib.request.urlopen(req, timeout=3) as response:\n"
        "        payload = json.loads(response.read().decode('utf-8'))\n"
        "except HTTPError as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'HTTPError: {exc.code} {exc.reason}'}))\n"
        "    sys.exit(1)\n"
        "except URLError as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'URLError: {exc.reason}'}))\n"
        "    sys.exit(1)\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ready': False, 'error': f'{type(exc).__name__}: {exc}'}))\n"
        "    sys.exit(1)\n"
        "agents = payload if isinstance(payload, list) else payload.get('agents', payload.get('items', []))\n"
        "agent = next((item for item in agents if item.get('name') == 'a2a-echo-agent'), None)\n"
        "ready = bool(agent)\n"
        "print(json.dumps({'ready': ready, 'agent_found': bool(agent), 'agent_id': (agent or {}).get('id', '')}))\n"
        "sys.exit(0 if ready else 1)\n"
        "PY"
    )
    result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=10)
    detail = _compose_probe_detail(result, "A2A registration probe not ready")
    return result.returncode == 0, detail


def _wait_for_a2a_registration(runtime: ContainerRuntime, compose_args: list[str], timeout_seconds: int = 90) -> tuple[bool, str]:
    token = _benchmark_token(runtime, compose_args)
    deadline = time.time() + timeout_seconds
    started_at = time.time()
    last_reported_second = -1
    last_detail = "A2A registration probe not ready"
    while time.time() < deadline:
        ready, detail = _a2a_registration_probe(compose_args, token)
        if ready:
            return True, detail
        last_detail = detail or last_detail
        elapsed = int(time.time() - started_at)
        if elapsed != last_reported_second and elapsed % 5 == 0:
            last_reported_second = elapsed
            _emit_progress(f"register_a2a_echo: waiting for A2A benchmark objects ({elapsed}s/{timeout_seconds}s) - {last_detail}")
        time.sleep(1)
    return False, last_detail


def _mcp_runtime_probe(compose_args: list[str], token: str) -> tuple[bool, dict[str, Any]]:
    command = (
        "python3 - <<'PY'\n"
        "import json, sys, urllib.request, uuid\n"
        "from urllib.error import HTTPError, URLError\n"
        f"token = {token!r}\n"
        "headers = {'Authorization': f'Bearer {token}'}\n"
        "def fetch_json(path):\n"
        "    req = urllib.request.Request(f'http://127.0.0.1:4444{path}', headers=headers)\n"
        "    with urllib.request.urlopen(req, timeout=5) as response:\n"
        "        body = response.read().decode('utf-8')\n"
        "        return json.loads(body), dict(response.headers.items())\n"
        "payload = {'ready': False}\n"
        "try:\n"
        "    health_body, health_headers = fetch_json('/health')\n"
        "    servers, _ = fetch_json('/servers')\n"
        "    if isinstance(servers, dict):\n"
        "        servers = servers.get('items', servers.get('servers', []))\n"
        "    preferred_names = {'Fast Time Server', 'fast_time', 'fast-time'}\n"
        "    fast_time_server = next((server for server in servers if (server.get('name') or '') in preferred_names), None)\n"
        "    if not fast_time_server:\n"
        "        fast_time_server = next((server for server in servers if 'fast_time' in str(server.get('url') or '')), None)\n"
        "    if not fast_time_server:\n"
        "        fast_time_server = next((server for server in servers if len(server.get('associatedTools') or []) >= 2), None)\n"
        "    if not fast_time_server:\n"
        "        payload.update({'error': 'Benchmark MCP server not found', 'health_headers': health_headers, 'health_body': health_body})\n"
        "        print(json.dumps(payload))\n"
        "        sys.exit(1)\n"
        "    request_payload = json.dumps({\n"
        "        'jsonrpc': '2.0',\n"
        "        'id': str(uuid.uuid4()),\n"
        "        'method': 'initialize',\n"
        "        'params': {\n"
        "            'protocolVersion': '2024-11-05',\n"
        "            'capabilities': {'tools': {}, 'resources': {}, 'prompts': {}},\n"
        "            'clientInfo': {'name': 'benchmark-suite-runtime-probe', 'version': '1.0.0'}\n"
        "        }\n"
        "    }).encode('utf-8')\n"
        "    request_headers = {**headers, 'Content-Type': 'application/json', 'Accept': 'application/json'}\n"
        "    request = urllib.request.Request(\n"
        "        f\"http://127.0.0.1:4444/servers/{fast_time_server['id']}/mcp\",\n"
        "        data=request_payload,\n"
        "        headers=request_headers,\n"
        "        method='POST',\n"
        "    )\n"
        "    with urllib.request.urlopen(request, timeout=5) as response:\n"
        "        body = json.loads(response.read().decode('utf-8'))\n"
        "        payload.update({\n"
        "            'ready': True,\n"
        "            'health_headers': health_headers,\n"
        "            'health_body': health_body,\n"
        "            'mcp_headers': dict(response.headers.items()),\n"
        "            'mcp_body': body,\n"
        "            'server_id': fast_time_server['id'],\n"
        "        })\n"
        "        print(json.dumps(payload))\n"
        "        sys.exit(0)\n"
        "except HTTPError as exc:\n"
        "    payload['error'] = f'HTTPError: {exc.code} {exc.reason}'\n"
        "except URLError as exc:\n"
        "    payload['error'] = f'URLError: {exc.reason}'\n"
        "except Exception as exc:\n"
        "    payload['error'] = f'{type(exc).__name__}: {exc}'\n"
        "print(json.dumps(payload))\n"
        "sys.exit(1)\n"
        "PY"
    )
    result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=10)
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    payload: dict[str, Any] = {"ready": False, "raw": _trim_status_text(output, limit=1500)}
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    return result.returncode == 0, payload


def _verify_runtime_expectations(runtime: ContainerRuntime, compose_args: list[str], scenario: dict[str, Any]) -> tuple[bool, str]:
    setup = scenario.get("setup", {}) or {}
    expected_runtime = setup.get("expected_mcp_runtime")
    expected_runtime_mode = setup.get("expected_mcp_runtime_mode")
    if not expected_runtime and not expected_runtime_mode:
        return True, "no runtime expectation configured"

    token = _benchmark_token(runtime, compose_args)
    payload: dict[str, Any] = {}
    ready = False
    last_detail = "runtime probe failed"
    deadline = time.time() + 15
    while time.time() < deadline:
        ready, payload = _mcp_runtime_probe(compose_args, token)
        if ready:
            break
        last_detail = payload.get("error") or payload.get("raw") or last_detail
        time.sleep(1)
    if not ready:
        return False, f"runtime probe failed: {last_detail}"

    health_headers = {str(key).lower(): str(value) for key, value in (payload.get("health_headers") or {}).items()}
    health_body = payload.get("health_body") or {}
    mcp_headers = {str(key).lower(): str(value) for key, value in (payload.get("mcp_headers") or {}).items()}
    actual_runtime = mcp_headers.get("x-contextforge-mcp-runtime") or ""
    actual_mode = health_headers.get("x-contextforge-mcp-runtime-mode") or str((health_body.get("mcp_runtime") or {}).get("mode") or "")

    mismatches: list[str] = []
    if expected_runtime and actual_runtime != expected_runtime:
        mismatches.append(f"expected MCP runtime header {expected_runtime!r}, got {actual_runtime!r}")
    if expected_runtime_mode and actual_mode != expected_runtime_mode:
        mismatches.append(f"expected runtime mode {expected_runtime_mode!r}, got {actual_mode!r}")
    if mismatches:
        return False, "; ".join(mismatches)
    return True, f"runtime={actual_runtime or 'unknown'}, mode={actual_mode or 'unknown'}"


def _a2a_runtime_probe(compose_args: list[str]) -> tuple[bool, dict[str, Any]]:
    command = (
        "python3 - <<'PY'\n"
        "import json, sys\n"
        "payload = {'ready': True, 'runtime': 'python'}\n"
        "try:\n"
        "    from gateway_rs import a2a_service as rust_a2a\n"
        "except ImportError as exc:\n"
        "    payload['detail'] = f'python fallback ({exc})'\n"
        "    print(json.dumps(payload))\n"
        "    sys.exit(0)\n"
        "payload['runtime'] = 'rust' if hasattr(rust_a2a, 'try_submit_invoke') else 'python'\n"
        "payload['detail'] = 'gateway_rs.a2a_service available' if payload['runtime'] == 'rust' else 'gateway_rs missing try_submit_invoke'\n"
        "print(json.dumps(payload))\n"
        "sys.exit(0)\n"
        "PY"
    )
    result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=10)
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    payload: dict[str, Any] = {"ready": False, "raw": _trim_status_text(output, limit=1500)}
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    return result.returncode == 0, payload


def _verify_a2a_runtime_expectations(compose_args: list[str], scenario: dict[str, Any]) -> tuple[bool, str]:
    expected_runtime = (scenario.get("setup", {}) or {}).get("expected_a2a_runtime")
    if not expected_runtime:
        return True, "no A2A runtime expectation configured"

    ready, payload = _a2a_runtime_probe(compose_args)
    if not ready:
        return False, payload.get("error") or payload.get("raw") or "A2A runtime probe failed"
    actual_runtime = str(payload.get("runtime", "") or "")
    if actual_runtime != expected_runtime:
        return False, f"expected A2A runtime {expected_runtime!r}, got {actual_runtime!r}"
    return True, f"runtime={actual_runtime}"


def _wait_for_compose_service(runtime: ContainerRuntime, compose_args: list[str], service: str, timeout_seconds: int = 45) -> bool:
    deadline = time.time() + timeout_seconds
    started_at = time.time()
    last_reported_second = -1
    while time.time() < deadline:
        try:
            container_id = _service_container_id(compose_args, service, timeout=10)
        except RuntimeError:
            elapsed = int(time.time() - started_at)
            if elapsed != last_reported_second and elapsed % 5 == 0:
                last_reported_second = elapsed
                _emit_progress(f"{service}: waiting for container to appear ({elapsed}s/{timeout_seconds}s)")
            time.sleep(1)
            continue
        result = _run_command([runtime.engine, "inspect", container_id, "--format", "{{json .State}}"], check=False, timeout=10)
        if result.returncode == 0:
            try:
                payload = json.loads((result.stdout or "").strip() or "{}")
            except json.JSONDecodeError:
                payload = {}
            health = payload.get("Health") or {}
            health_status = health.get("Status")
            if health_status == "healthy":
                return True
            if payload.get("Running") and not health_status:
                return True
            elapsed = int(time.time() - started_at)
            if elapsed != last_reported_second and elapsed % 5 == 0:
                last_reported_second = elapsed
                status_text = health_status or ("running" if payload.get("Running") else payload.get("Status") or "unknown")
                error_text = _trim_status_text(str(payload.get("Error") or ""))
                suffix = f", error={error_text}" if error_text else ""
                _emit_progress(f"{service}: waiting for healthy state ({elapsed}s/{timeout_seconds}s) - status={status_text}{suffix}")
        else:
            elapsed = int(time.time() - started_at)
            if elapsed != last_reported_second and elapsed % 5 == 0:
                last_reported_second = elapsed
                detail = _trim_status_text((result.stderr or result.stdout or "inspect failed").strip())
                _emit_progress(f"{service}: inspect not ready ({elapsed}s/{timeout_seconds}s) - {detail}")
        time.sleep(1)
    return False


def _wait_for_compose_job(runtime: ContainerRuntime, compose_args: list[str], service: str, timeout_seconds: int = 60) -> tuple[bool, str]:
    deadline = time.time() + timeout_seconds
    started_at = time.time()
    last_reported_second = -1
    last_status = "unknown"
    while time.time() < deadline:
        try:
            container_id = _service_container_id(compose_args, service, timeout=10)
        except RuntimeError:
            elapsed = int(time.time() - started_at)
            if elapsed != last_reported_second and elapsed % 5 == 0:
                last_reported_second = elapsed
                _emit_progress(f"{service}: waiting for job container to appear ({elapsed}s/{timeout_seconds}s)")
            time.sleep(1)
            continue
        result = _run_command([runtime.engine, "inspect", container_id, "--format", "{{json .State}}"], check=False, timeout=10)
        if result.returncode != 0:
            elapsed = int(time.time() - started_at)
            if elapsed != last_reported_second and elapsed % 5 == 0:
                last_reported_second = elapsed
                detail = _trim_status_text((result.stderr or result.stdout or "inspect failed").strip())
                _emit_progress(f"{service}: waiting for job state ({elapsed}s/{timeout_seconds}s) - {detail}")
            time.sleep(1)
            continue
        try:
            payload = json.loads((result.stdout or "").strip() or "{}")
        except json.JSONDecodeError:
            payload = {}
        status = str(payload.get("Status") or "unknown")
        last_status = status
        if status == "exited":
            exit_code = int(payload.get("ExitCode", 1) or 1)
            if exit_code == 0:
                return True, "completed successfully"
            log_result = _run_compose(compose_args, ["logs", "--no-color", service], check=False, timeout=20)
            if log_result.returncode != 0:
                log_result = _run_compose(compose_args, ["logs", service], check=False, timeout=20)
            log_tail = _trim_status_text(((log_result.stdout or "") + ("\n" + log_result.stderr if log_result.stderr else "")).strip(), limit=1500)
            error_text = _trim_status_text(str(payload.get("Error") or f"exited with code {exit_code}"))
            if log_tail:
                return False, f"{error_text}; logs: {log_tail}"
            return False, error_text
        elapsed = int(time.time() - started_at)
        if elapsed != last_reported_second and elapsed % 5 == 0:
            last_reported_second = elapsed
            _emit_progress(f"{service}: waiting for registration job ({elapsed}s/{timeout_seconds}s) - status={status}")
        time.sleep(1)
    return False, f"timed out while waiting for job completion (last_status={last_status})"


def _start_docker_stack(runtime: ContainerRuntime, scenario: dict[str, Any], scenario_dir: Path) -> tuple[list[str], str]:
    source = _ensure_scenario_source(scenario)
    image_name = _ensure_benchmark_image(runtime, scenario)
    nginx_image_name = _ensure_benchmark_nginx_image(runtime, scenario)
    a2a_echo_image_name = _ensure_benchmark_a2a_echo_image(runtime, scenario) if _scenario_uses_a2a_fixture(scenario) else ""
    reuse_stack = bool((scenario.get("execution", {}) or {}).get("reuse_stack", False))
    if reuse_stack:
        signature_payload = {
            "image_name": image_name,
            "build": scenario.get("build", {}) or {},
            "runtime": scenario.get("runtime", {}) or {},
            "setup": scenario.get("setup", {}) or {},
            "gateway": scenario.get("gateway", {}) or {},
            "plugins": scenario.get("plugins", {}) or {},
            "load": scenario.get("load", {}) or {},
            "target_service": (scenario.get("load", {}) or {}).get("target_service", "nginx"),
        }
        signature = hashlib.sha256(_stable_json(signature_payload).encode("utf-8")).hexdigest()
        mount_dir = RUNTIME_STAGING_ROOT / "shared_stacks" / signature[:24]
        mount_dir.mkdir(parents=True, exist_ok=True)
        for transient_path in (
            mount_dir / "plugin_timing",
            mount_dir / "pyspy",
            mount_dir / "memray",
            mount_dir / "plugin_timing_live.json",
        ):
            if transient_path.is_dir():
                shutil.rmtree(transient_path, ignore_errors=True)
            elif transient_path.exists():
                transient_path.unlink(missing_ok=True)
        _render_plugin_config_for_scenario(scenario, mount_dir / "plugins.yaml", validate_only=False)
        project_name = f"bench-shared-{signature[:12]}"
    else:
        mount_dir = scenario_dir
        project_name = f"bench-{_slugify(scenario['name'])}-{int(time.time())}"
    override_path = _write_compose_override(scenario, mount_dir, image_name, nginx_image_name, a2a_echo_image_name, source.repo_root)
    compose_args = _compose_base_args(runtime, project_name, override_path)
    requires_fast_time = _scenario_uses_fast_time_fixture(scenario)
    requires_a2a = _scenario_uses_a2a_fixture(scenario)
    if reuse_stack:
        shared_services = ["postgres", "redis", "pgbouncer", "gateway"]
        if scenario.get("load", {}).get("target_service", "nginx") == "nginx":
            shared_services.append("nginx")
        if requires_fast_time:
            shared_services.append("fast_time_server")
        if requires_a2a:
            shared_services.append("a2a_echo_agent")
        containers_present = False
        for service in shared_services:
            try:
                _service_container_id(compose_args, service)
                containers_present = True
                break
            except RuntimeError:
                continue
        if containers_present:
            services_ready = all(_wait_for_compose_service(runtime, compose_args, service, timeout_seconds=2) for service in shared_services)
            gateway_ready = _wait_for_gateway_health(compose_args, timeout_seconds=2)
            registration_ready = True
            if requires_fast_time:
                registration_ready, _ = _wait_for_benchmark_registration(runtime, compose_args, timeout_seconds=2)
            if registration_ready and requires_a2a:
                registration_ready, _ = _wait_for_a2a_registration(runtime, compose_args, timeout_seconds=2)
            runtime_ready = False
            runtime_detail = "runtime verification skipped"
            a2a_runtime_ready = False
            a2a_runtime_detail = "A2A runtime verification skipped"
            if services_ready and gateway_ready and registration_ready and requires_fast_time:
                runtime_ready, runtime_detail = _verify_runtime_expectations(runtime, compose_args, scenario)
            else:
                runtime_ready = True
            if services_ready and gateway_ready and registration_ready and requires_a2a:
                a2a_runtime_ready, a2a_runtime_detail = _verify_a2a_runtime_expectations(compose_args, scenario)
            else:
                a2a_runtime_ready = True
            if services_ready and gateway_ready and registration_ready and runtime_ready and a2a_runtime_ready:
                _emit_progress(f"{scenario['name']}: reusing persistent benchmark stack {project_name}")
                return compose_args, project_name
            if services_ready and gateway_ready and registration_ready and not runtime_ready:
                _emit_progress(f"{scenario['name']}: existing persistent stack {project_name} failed MCP runtime verification ({runtime_detail}), recreating it")
            elif services_ready and gateway_ready and registration_ready and not a2a_runtime_ready:
                _emit_progress(f"{scenario['name']}: existing persistent stack {project_name} failed A2A runtime verification ({a2a_runtime_detail}), recreating it")
            else:
                _emit_progress(f"{scenario['name']}: existing persistent stack {project_name} is not reusable, recreating it")
            _stop_docker_stack(compose_args)
    env = os.environ.copy()
    env["IMAGE_LOCAL"] = image_name
    env["HOST_UID"] = str(os.getuid())
    env["HOST_GID"] = str(os.getgid())
    try:
        _run_compose(compose_args, ["up", "-d", "--no-build", "postgres", "redis"], env=env)
        _emit_progress(f"{scenario['name']}: waiting for postgres to become healthy")
        if not _wait_for_compose_service(runtime, compose_args, "postgres", timeout_seconds=90):
            _capture_logs(compose_args, scenario_dir, 0)
            raise RuntimeError(f"Benchmark postgres failed to become healthy for scenario '{scenario['name']}'")
        _emit_progress(f"{scenario['name']}: postgres is healthy")
        _emit_progress(f"{scenario['name']}: waiting for redis to start")
        if not _wait_for_compose_service(runtime, compose_args, "redis", timeout_seconds=30):
            _capture_logs(compose_args, scenario_dir, 0)
            raise RuntimeError(f"Benchmark redis failed to start for scenario '{scenario['name']}'")
        _emit_progress(f"{scenario['name']}: redis is ready")
        _run_compose(compose_args, ["up", "-d", "--no-build", "pgbouncer"], env=env)
        _emit_progress(f"{scenario['name']}: waiting for pgbouncer to become healthy")
        if not _wait_for_compose_service(runtime, compose_args, "pgbouncer", timeout_seconds=60):
            _capture_logs(compose_args, scenario_dir, 0)
            raise RuntimeError(f"Benchmark pgbouncer failed to become healthy for scenario '{scenario['name']}'")
        _emit_progress(f"{scenario['name']}: pgbouncer is healthy")
        _run_compose(compose_args, ["up", "-d", "--no-build", "gateway"], env=env)
        _emit_progress(f"{scenario['name']}: waiting for gateway /health")
        if not _wait_for_gateway_health(compose_args, timeout_seconds=120):
            _capture_logs(compose_args, scenario_dir, 0)
            raise RuntimeError(f"Docker benchmark stack failed health check for scenario '{scenario['name']}'")
        _emit_progress(f"{scenario['name']}: gateway is healthy")
        if requires_fast_time:
            _run_compose(compose_args, ["up", "-d", "--no-build", "fast_time_server"], env=env)
            _emit_progress(f"{scenario['name']}: waiting for fast_time_server to start")
            if not _wait_for_compose_service(runtime, compose_args, "fast_time_server", timeout_seconds=45):
                _capture_logs(compose_args, scenario_dir, 0)
                raise RuntimeError(f"Benchmark fast_time_server failed to start for scenario '{scenario['name']}'")
            _emit_progress(f"{scenario['name']}: fast_time_server is ready")
            _emit_progress(f"{scenario['name']}: waiting for fast_time registration to complete")
            _run_compose(compose_args, ["up", "-d", "--no-build", "register_fast_time"], env=env)
            registration_ok, registration_detail = _wait_for_benchmark_registration(runtime, compose_args, timeout_seconds=90)
            if not registration_ok:
                job_ok, job_detail = _wait_for_compose_job(runtime, compose_args, "register_fast_time", timeout_seconds=5)
                _capture_logs(compose_args, scenario_dir, 0)
                if not job_ok:
                    raise RuntimeError(f"Benchmark fast_time registration failed for scenario '{scenario['name']}': {job_detail}")
                raise RuntimeError(f"Benchmark fast_time registration did not become ready for scenario '{scenario['name']}': {registration_detail}")
            _emit_progress(f"{scenario['name']}: fast_time registration completed")
            runtime_ok, runtime_detail = _verify_runtime_expectations(runtime, compose_args, scenario)
            if not runtime_ok:
                _capture_logs(compose_args, scenario_dir, 0)
                raise RuntimeError(
                    "Benchmark MCP runtime verification failed for "
                    f"scenario '{scenario['name']}': {runtime_detail} "
                    f"(see logs under {scenario_dir}/attempt_0)"
                )
            _emit_progress(f"{scenario['name']}: verified MCP runtime expectation ({runtime_detail})")
        if requires_a2a:
            _run_compose(compose_args, ["up", "-d", "--no-build", "a2a_echo_agent"], env=env)
            _emit_progress(f"{scenario['name']}: waiting for a2a_echo_agent to start")
            if not _wait_for_compose_service(runtime, compose_args, "a2a_echo_agent", timeout_seconds=45):
                _capture_logs(compose_args, scenario_dir, 0)
                raise RuntimeError(f"Benchmark a2a_echo_agent failed to start for scenario '{scenario['name']}'")
            _emit_progress(f"{scenario['name']}: a2a_echo_agent is ready")
            _emit_progress(f"{scenario['name']}: waiting for A2A registration to complete")
            _run_compose(compose_args, ["up", "-d", "--no-build", "register_a2a_echo"], env=env)
            a2a_registration_ok, a2a_registration_detail = _wait_for_a2a_registration(runtime, compose_args, timeout_seconds=90)
            if not a2a_registration_ok:
                job_ok, job_detail = _wait_for_compose_job(runtime, compose_args, "register_a2a_echo", timeout_seconds=5)
                _capture_logs(compose_args, scenario_dir, 0)
                if not job_ok:
                    raise RuntimeError(f"Benchmark A2A registration failed for scenario '{scenario['name']}': {job_detail}")
                raise RuntimeError(f"Benchmark A2A registration did not become ready for scenario '{scenario['name']}': {a2a_registration_detail}")
            _emit_progress(f"{scenario['name']}: A2A registration completed")
            a2a_runtime_ok, a2a_runtime_detail = _verify_a2a_runtime_expectations(compose_args, scenario)
            if not a2a_runtime_ok:
                _capture_logs(compose_args, scenario_dir, 0)
                raise RuntimeError(f"Benchmark A2A runtime verification failed for scenario '{scenario['name']}': {a2a_runtime_detail}")
            _emit_progress(f"{scenario['name']}: verified A2A runtime expectation ({a2a_runtime_detail})")
        if scenario.get("load", {}).get("target_service", "nginx") == "nginx":
            _run_compose(compose_args, ["up", "-d", "--no-build", "nginx"], env=env)
            _emit_progress(f"{scenario['name']}: waiting for nginx to become healthy")
            if not _wait_for_compose_service(runtime, compose_args, "nginx", timeout_seconds=60):
                _capture_logs(compose_args, scenario_dir, 0)
                raise RuntimeError(f"Benchmark nginx failed to become healthy for scenario '{scenario['name']}'")
            _emit_progress(f"{scenario['name']}: nginx is healthy")
    except Exception:
        _stop_docker_stack(compose_args)
        raise
    return compose_args, project_name


def _stop_docker_stack(compose_args: list[str]) -> None:
    _run_compose(compose_args, ["down", "--remove-orphans"], check=False)


def _compose_project_name(compose_args: list[str]) -> str:
    for index, value in enumerate(compose_args):
        if value == "-p" and index + 1 < len(compose_args):
            return compose_args[index + 1]
    raise RuntimeError("Compose project name was not provided")


def _service_container_id(compose_args: list[str], service: str, timeout: float | None = None) -> str:
    result = _run_compose(compose_args, ["ps", "-q", service], check=False, timeout=timeout)
    container_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if container_ids:
        return container_ids[-1]
    if shutil.which("podman") is not None and compose_args and (compose_args[0] == "podman-compose" or compose_args[:2] in (["podman", "compose"], ["docker", "compose"])):
        project_name = _compose_project_name(compose_args)
        result = _run_command(
            [
                "podman",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.ID}}",
            ],
            check=False,
            timeout=15,
        )
        container_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if container_ids:
            return container_ids[-1]
    raise RuntimeError(f"Could not resolve container ID for service '{service}'")


def _benchmark_token(runtime: ContainerRuntime, compose_args: list[str]) -> str:
    del runtime
    command = (
        "python3 -m mcpgateway.utils.create_jwt_token "
        "--username admin@example.com "
        "--admin "
        "--full-name 'Benchmark Admin' "
        "--exp 10080 "
        "--secret my-test-key "
        "--algo HS256"
    )
    result = _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", command], check=False, timeout=20)
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate benchmark JWT in gateway container: {output[-2000:]}")

    token_match = re.search(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+", output)
    if token_match:
        return token_match.group(0)
    raise RuntimeError(f"Benchmark JWT generation did not emit a token: {output[-2000:]}")


def _target_host(load: dict[str, Any]) -> str:
    if load.get("host"):
        return str(load["host"])
    return "http://nginx:80" if load.get("target_service", "nginx") == "nginx" else "http://gateway:4444"


def _locust_run_command(runtime: ContainerRuntime, compose_args: list[str], project_name: str, scenario: dict[str, Any], scenario_dir: Path, artifact_prefix: str) -> list[str]:
    load = scenario.get("load", {}) or {}
    locust_image = _ensure_locust_image(runtime)
    locustfile = load.get("locustfile")
    if not locustfile:
        raise RuntimeError("Missing locustfile")
    locustfile_host_path = _resolve_scenario_relative_path(scenario, str(locustfile)).resolve()
    if not locustfile_host_path.is_relative_to(REPO_ROOT):
        raise RuntimeError(f"Scenario '{scenario['name']}' locustfile must live inside the repository: {locustfile_host_path}")
    locustfile_path = Path("/mnt/repo") / locustfile_host_path.relative_to(REPO_ROOT)
    workdir = locustfile_path.parent
    command = [
        runtime.engine,
        "run",
        "--rm",
        "--network",
        f"{project_name}_mcpnet",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--workdir",
        str(workdir),
        "-v",
        f"{REPO_ROOT.resolve()}:/mnt/repo:ro",
        "-v",
        f"{scenario_dir.resolve()}:/mnt/bench",
        "-e",
        "HOME=/tmp",
    ]
    token = _benchmark_token(runtime, compose_args)
    if token:
        command.extend(["-e", f"MCPGATEWAY_BEARER_TOKEN={token}"])
    for key, value in sorted(_scenario_env(scenario).items()):
        command.extend(["-e", f"{key}={value}"])
    command.extend(
        [
            locust_image,
            "-f",
            str(locustfile_path),
            f"--host={_target_host(load)}",
            f"--users={int(load.get('users', 1))}",
            f"--spawn-rate={int(load.get('spawn_rate', 1))}",
            f"--csv=/mnt/bench/{artifact_prefix}",
            "--exit-code-on-error=0",
        ]
    )
    if load.get("html_report", True):
        command.append(f"--html=/mnt/bench/{artifact_prefix}_report.html")
    if load.get("run_time"):
        command.append(f"--run-time={str(load['run_time'])}")
    command.append("--headless" if load.get("headless", True) else "--class-picker")
    if load.get("only_summary", True):
        command.append("--only-summary")
    if load.get("user_class"):
        command.append(str(load["user_class"]))
    for tag in load.get("tags", []) or []:
        command.extend(["--tags", str(tag)])
    for tag in load.get("exclude_tags", []) or []:
        command.extend(["--exclude-tags", str(tag)])
    for arg in load.get("extra_args", []) or []:
        command.append(str(arg))
    return command


def _run_docker_locust(runtime: ContainerRuntime, compose_args: list[str], project_name: str, scenario: dict[str, Any], scenario_dir: Path, artifact_prefix: str) -> dict[str, Any]:
    load = scenario.get("load", {}) or {}
    fallback = {
        "csv_prefix": str(scenario_dir / artifact_prefix),
        "html_report": str(scenario_dir / f"{artifact_prefix}_report.html") if load.get("html_report", True) else None,
        "locustfile": scenario.get("load", {}).get("locustfile"),
        "target_service": scenario.get("load", {}).get("target_service", "nginx"),
    }
    try:
        command = _locust_run_command(runtime, compose_args, project_name, scenario, scenario_dir, artifact_prefix)
    except RuntimeError as exc:
        return {"status": "unavailable", "reason": str(exc), **fallback}
    run_seconds = _parse_run_time_seconds(load.get("run_time"))
    timeout = (run_seconds + 120) if run_seconds else 300
    result = _run_command(command, env=os.environ.copy(), check=False, timeout=timeout)
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-4000:],
        "stderr": (result.stderr or "")[-4000:],
        **fallback,
    }


def _start_docker_locust_background(runtime: ContainerRuntime, compose_args: list[str], project_name: str, scenario: dict[str, Any], scenario_dir: Path, artifact_prefix: str) -> subprocess.Popen[str]:
    command = _locust_run_command(runtime, compose_args, project_name, scenario, scenario_dir, artifact_prefix)
    return subprocess.Popen(command, cwd=str(REPO_ROOT), env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _parse_history_rows(history_path: Path) -> list[tuple[float, dict[str, str]]]:
    if not history_path.exists():
        return []
    import csv

    rows: list[tuple[float, dict[str, str]]] = []
    with history_path.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp_raw = (row.get("Timestamp") or row.get("timestamp") or "").strip()
            if not timestamp_raw:
                continue
            try:
                if timestamp_raw.isdigit():
                    ts = float(timestamp_raw)
                else:
                    ts = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            rows.append((ts, row))
    return rows


def _measurement_window_summary(csv_prefix: str, measurement: dict[str, Any]) -> dict[str, Any]:
    history_path = Path(f"{csv_prefix}_stats_history.csv")
    rows = _parse_history_rows(history_path)
    if not rows:
        return {"status": "unavailable", "reason": "Locust stats history CSV not found"}

    warmup = max(0, int(measurement.get("warmup_seconds", 0) or 0))
    measure_seconds = int(measurement.get("measure_seconds", 0) or 0)
    cooldown = max(0, int(measurement.get("cooldown_seconds", 0) or 0))
    start_ts = rows[0][0] + warmup
    end_ts = rows[-1][0] - cooldown
    if measure_seconds:
        end_ts = min(end_ts, start_ts + measure_seconds)
    window = [row for ts, row in rows if start_ts <= ts <= end_ts]
    if not window:
        return {"status": "unavailable", "reason": "Measurement window did not overlap with Locust stats history"}

    first = window[0]
    last = window[-1]
    requests_delta = _numeric(last.get("Total Request Count")) - _numeric(first.get("Total Request Count"))
    failures_delta = _numeric(last.get("Total Failure Count")) - _numeric(first.get("Total Failure Count"))
    rps_samples = [_numeric(row.get("Requests/s") or row.get("Total RPS") or row.get("Current RPS")) for row in window]
    avg_samples = [_numeric(row.get("Total Average Response Time") or row.get("Average Response Time")) for row in window]
    p50_samples = [_numeric(row.get("Total Median Response Time") or row.get("50%")) for row in window]
    p95_samples = [_numeric(row.get("95%")) for row in window]
    p99_samples = [_numeric(row.get("99%")) for row in window]
    return {
        "status": "ok",
        "source": "locust_stats_history_window",
        "warmup_seconds": warmup,
        "measure_seconds": measure_seconds,
        "cooldown_seconds": cooldown,
        "samples": len(window),
        "aggregated": {
            "Request Count": requests_delta,
            "Failure Count": failures_delta,
            "Requests/s": sum(rps_samples) / len(rps_samples) if rps_samples else 0,
            "Average Response Time": sum(avg_samples) / len(avg_samples) if avg_samples else 0,
            "50%": p50_samples[-1] if p50_samples else 0,
            "95%": max(p95_samples) if p95_samples else 0,
            "99%": max(p99_samples) if p99_samples else 0,
        },
    }


def _collect_endpoint_metrics(csv_prefix: str, measurement: dict[str, Any]) -> dict[str, Any]:
    stats_path = Path(f"{csv_prefix}_stats.csv")
    if not stats_path.exists():
        return {"status": "unavailable", "reason": "Locust stats CSV not found"}

    import csv

    with stats_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    aggregated = next((row for row in rows if row.get("Name") == "Aggregated"), {})
    endpoints = [row for row in rows if row.get("Name") != "Aggregated"]
    measurement_window = _measurement_window_summary(csv_prefix, measurement)
    effective_aggregated: dict[str, Any] = aggregated
    if measurement_window.get("status") == "ok":
        effective_aggregated = {**aggregated, **measurement_window["aggregated"]}
    return {
        "status": "ok",
        "aggregated": effective_aggregated,
        "aggregated_source": measurement_window.get("source", "locust_stats_csv"),
        "measurement_window": measurement_window,
        "endpoints": endpoints,
        "top_slowest": sorted(endpoints, key=lambda row: _numeric(row.get("95%")), reverse=True)[:SUMMARY_LIMIT],
        "top_hottest": sorted(endpoints, key=lambda row: _numeric(row.get("Request Count")), reverse=True)[:SUMMARY_LIMIT],
        "top_failures": sorted(endpoints, key=lambda row: _numeric(row.get("Failure Count")), reverse=True)[:SUMMARY_LIMIT],
    }


def _collect_plugin_timing(scenario_dir: Path) -> dict[str, Any]:
    timing_dir = scenario_dir / "plugin_timing"
    legacy_file = scenario_dir / "plugin_timing_live.json"
    if not timing_dir.exists():
        if legacy_file.exists():
            return {"status": "ok", "timings": json.loads(legacy_file.read_text(encoding="utf-8")), "files": [str(legacy_file)]}
        return {"status": "unavailable", "reason": "No live plugin timing file emitted"}

    merged: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    counts: dict[str, int] = defaultdict(int)
    files = sorted(timing_dir.glob("*.json"))
    for file_path in files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        for plugin_name, hooks in payload.items():
            for hook_name, metrics in hooks.items():
                bucket = merged[plugin_name][hook_name]
                bucket["count"] += _numeric(metrics.get("count"))
                bucket["total_ms"] += _numeric(metrics.get("total_ms"))
                bucket["min_ms"] = min(bucket.get("min_ms", float("inf")), _numeric(metrics.get("min_ms")))
                bucket["max_ms"] = max(bucket.get("max_ms", 0), _numeric(metrics.get("max_ms")))
                bucket["p95_ms"] = max(bucket.get("p95_ms", 0), _numeric(metrics.get("p95_ms")))
                bucket["p99_ms"] = max(bucket.get("p99_ms", 0), _numeric(metrics.get("p99_ms")))
                counts[f"{plugin_name}:{hook_name}"] += 1

    normalized: dict[str, Any] = {}
    for plugin_name, hooks in merged.items():
        normalized[plugin_name] = {}
        for hook_name, metrics in hooks.items():
            total_count = metrics.get("count", 0)
            total_ms = metrics.get("total_ms", 0)
            normalized[plugin_name][hook_name] = {
                "count": int(total_count),
                "avg_ms": (total_ms / total_count) if total_count else 0,
                "min_ms": 0 if metrics.get("min_ms", float("inf")) == float("inf") else metrics.get("min_ms", 0),
                "max_ms": metrics.get("max_ms", 0),
                "p95_ms": metrics.get("p95_ms", 0),
                "p99_ms": metrics.get("p99_ms", 0),
                "total_ms": total_ms,
                "process_files": counts[f"{plugin_name}:{hook_name}"],
            }
    return {"status": "ok", "timings": normalized, "files": [str(path) for path in files]}


def _collect_database_metrics(compose_args: list[str]) -> dict[str, Any]:
    command = (
        "PGPASSWORD=\"${POSTGRES_PASSWORD:-mysecretpassword}\" "
        "psql -U postgres -d mcp -t -A -c "
        "\"select json_build_object("
        "'num_backends', numbackends,"
        "'xact_commit', xact_commit,"
        "'xact_rollback', xact_rollback,"
        "'blks_read', blks_read,"
        "'blks_hit', blks_hit,"
        "'tup_returned', tup_returned,"
        "'tup_fetched', tup_fetched,"
        "'temp_files', temp_files,"
        "'deadlocks', deadlocks"
        ") from pg_stat_database where datname = 'mcp';\""
    )
    result = _run_compose(compose_args, ["exec", "-T", "postgres", "sh", "-lc", command], check=False)
    output = (result.stdout or "").strip()
    if result.returncode != 0 or not output:
        return {
            "status": "unavailable",
            "reason": "Unable to query postgres runtime metrics",
            "stderr": (result.stderr or result.stdout or "")[-2000:],
        }
    try:
        return {"status": "ok", "stats": json.loads(output.splitlines()[-1])}
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "Postgres runtime metrics were not valid JSON", "raw": output[-2000:]}


def _collect_system_metrics(compose_args: list[str]) -> dict[str, Any]:
    proc_probe = (
        "if [ -r /proc/1/status ]; then "
        "cat /proc/1/status; "
        "elif command -v ps >/dev/null 2>&1; then "
        "ps -o pid=,rss=,vsz=,comm= 1; "
        "else "
        "exit 127; "
        "fi"
    )
    process_table_probe = "if command -v ps >/dev/null 2>&1; then ps -e -o rss=,vsz=,comm=; else exit 127; fi"
    service_metrics: dict[str, Any] = {}
    for service in ("gateway", "nginx", "postgres", "redis", "pgbouncer"):
        result = _run_compose(compose_args, ["exec", "-T", service, "sh", "-lc", proc_probe], check=False)
        snapshot = (result.stdout or "").strip() or (result.stderr or "").strip()
        process_table_result = _run_compose(compose_args, ["exec", "-T", service, "sh", "-lc", process_table_probe], check=False)
        process_table = (process_table_result.stdout or "").strip() or (process_table_result.stderr or "").strip()
        if result.returncode == 0:
            source = "procfs" if "Name:" in snapshot and "VmRSS:" in snapshot else "ps"
            payload: dict[str, Any] = {"status": "ok", "snapshot": snapshot, "source": source}
            if process_table_result.returncode == 0:
                payload["process_table"] = process_table
                process_totals = _parse_process_table_memory_mb(process_table)
                if process_totals:
                    payload["process_totals"] = process_totals
            elif process_table:
                payload["process_table"] = process_table
            service_metrics[service] = payload
        else:
            service_metrics[service] = {"status": "unavailable", "snapshot": snapshot}
    return {"status": "ok", "services": service_metrics}


def _parse_procfs_memory_mb(snapshot: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in snapshot.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().lower()
        if key == "VmRSS":
            parts = value.split()
            if parts:
                metrics["rss_mb"] = round(float(parts[0]) / 1024.0, 2)
        elif key == "VmSize":
            parts = value.split()
            if parts:
                metrics["vms_mb"] = round(float(parts[0]) / 1024.0, 2)
    return metrics


def _parse_ps_memory_mb(snapshot: str) -> dict[str, float]:
    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if not lines:
        return {}
    fields = lines[-1].split()
    if len(fields) < 3:
        return {}
    try:
        return {
            "rss_mb": round(float(fields[1]) / 1024.0, 2),
            "vms_mb": round(float(fields[2]) / 1024.0, 2),
        }
    except ValueError:
        return {}


def _parse_process_table_memory_mb(snapshot: str) -> dict[str, float]:
    total_rss_kb = 0.0
    total_vsz_kb = 0.0
    process_count = 0
    for line in snapshot.splitlines():
        fields = line.split(None, 2)
        if len(fields) < 2:
            continue
        try:
            total_rss_kb += float(fields[0])
            total_vsz_kb += float(fields[1])
        except ValueError:
            continue
        process_count += 1
    if process_count == 0:
        return {}
    return {
        "rss_mb": round(total_rss_kb / 1024.0, 2),
        "vms_mb": round(total_vsz_kb / 1024.0, 2),
        "process_count": float(process_count),
    }


def _parse_process_stats_memory_mb(snapshot: str) -> dict[str, float]:
    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}
    header = lines[0].lower().split()
    values = lines[-1].split(None, len(header) - 1)
    if len(values) < len(header):
        return {}
    row = dict(zip(header, values))
    metrics: dict[str, float] = {}
    rss_value = row.get("rss")
    vsz_value = row.get("vsz")
    if rss_value:
        try:
            metrics["rss_mb"] = round(float(rss_value) / 1024.0, 2)
        except ValueError:
            pass
    if vsz_value:
        try:
            metrics["vms_mb"] = round(float(vsz_value) / 1024.0, 2)
        except ValueError:
            pass
    return metrics


def _scenario_memory_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    process_stats = summary.get("process_stats", {}) or {}
    if process_stats.get("status") == "ok":
        parsed = _parse_process_stats_memory_mb(str(process_stats.get("snapshot", "")))
        if parsed:
            return {"status": "ok", "source": "process_stats", **parsed}

    gateway_service = ((summary.get("system_metrics", {}) or {}).get("services", {}) or {}).get("gateway", {}) or {}
    process_totals = gateway_service.get("process_totals")
    if isinstance(process_totals, dict) and any(_numeric(process_totals.get(key)) > 0 for key in ("rss_mb", "vms_mb")):
        return {"status": "ok", "source": "system_metrics.process_table", **process_totals}
    if gateway_service.get("status") == "ok":
        snapshot = str(gateway_service.get("snapshot", ""))
        source = gateway_service.get("source", "unknown")
        parsed = _parse_procfs_memory_mb(snapshot) if source == "procfs" else _parse_ps_memory_mb(snapshot)
        if parsed:
            return {"status": "ok", "source": f"system_metrics.{source}", **parsed}

    return {"status": "unavailable"}


def _hook_delta(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, float]:
    left_metrics = left or {}
    right_metrics = right or {}
    return {
        "avg_ms_delta": _numeric(right_metrics.get("avg_ms")) - _numeric(left_metrics.get("avg_ms")),
        "p95_ms_delta": _numeric(right_metrics.get("p95_ms")) - _numeric(left_metrics.get("p95_ms")),
        "total_ms_delta": _numeric(right_metrics.get("total_ms")) - _numeric(left_metrics.get("total_ms")),
        "count_delta": _numeric(right_metrics.get("count")) - _numeric(left_metrics.get("count")),
    }


def _metric_payload(left_value: Any, right_value: Any, *, higher_is_better: bool) -> dict[str, Any]:
    left_num = _numeric(left_value)
    right_num = _numeric(right_value)
    delta = right_num - left_num
    percent_delta = _safe_percent_delta(left_num, right_num)

    winner = "tie"
    if right_num != left_num:
        if higher_is_better:
            winner = "right" if right_num > left_num else "left"
        else:
            winner = "right" if right_num < left_num else "left"

    return {
        "left": left_num,
        "right": right_num,
        "delta": delta,
        "percent_delta": _round_metric(percent_delta),
        "winner": winner,
        "higher_is_better": higher_is_better,
    }


def _scenario_core_metrics(summary: dict[str, Any]) -> dict[str, float]:
    aggregated = summary.get("endpoint_metrics", {}).get("aggregated", {}) or {}
    memory = _scenario_memory_metrics(summary)
    return {
        "requests": _numeric(aggregated.get("Request Count")),
        "rps": _numeric(aggregated.get("Requests/s")),
        "avg_latency_ms": _numeric(aggregated.get("Average Response Time")),
        "p50_latency_ms": _numeric(aggregated.get("50%") or aggregated.get("Median Response Time")),
        "p95_latency_ms": _numeric(aggregated.get("95%")),
        "p99_latency_ms": _numeric(aggregated.get("99%")),
        "max_latency_ms": _numeric(aggregated.get("Max Response Time")),
        "failures": _numeric(aggregated.get("Failure Count")),
        "rss_mb": _numeric(memory.get("rss_mb")),
        "vms_mb": _numeric(memory.get("vms_mb")),
    }


def _scenario_failure_rate(summary: dict[str, Any]) -> float:
    metrics = _scenario_core_metrics(summary)
    total_requests = metrics["requests"]
    if total_requests <= 0:
        return 0.0
    return metrics["failures"] / total_requests


def _scenario_efficiency_score(summary: dict[str, Any]) -> float:
    metrics = _scenario_core_metrics(summary)
    p95 = metrics["p95_latency_ms"] or 1.0
    success_factor = max(0.0, 1.0 - _scenario_failure_rate(summary))
    return metrics["rps"] * success_factor / p95


def _normalize_endpoint_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("Name", "unknown"),
        "request_count": _numeric(row.get("Request Count")),
        "failure_count": _numeric(row.get("Failure Count")),
        "rps": _numeric(row.get("Requests/s")),
        "avg_latency_ms": _numeric(row.get("Average Response Time")),
        "p50_latency_ms": _numeric(row.get("50%") or row.get("Median Response Time")),
        "p95_latency_ms": _numeric(row.get("95%")),
        "p99_latency_ms": _numeric(row.get("99%")),
        "max_latency_ms": _numeric(row.get("Max Response Time")),
    }


def _normalize_plugin_timings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    timings = summary.get("plugin_timing", {}).get("timings", {}) or {}
    normalized = []
    for plugin_name, hooks in sorted(timings.items()):
        hook_payloads = []
        total_ms = 0.0
        for hook_name, value in sorted((hooks or {}).items()):
            if isinstance(value, dict):
                latency_ms = _numeric(value.get("avg_ms") or value.get("total_ms"))
            else:
                latency_ms = _numeric(value)
            total_ms += latency_ms
            hook_payloads.append({"hook": hook_name, "latency_ms": latency_ms})
        normalized.append({"plugin": plugin_name, "total_latency_ms": total_ms, "hooks": hook_payloads})
    return sorted(normalized, key=lambda item: item["total_latency_ms"], reverse=True)


def _relative_href(run_dir: Path, path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if path.is_absolute():
        try:
            return str(path.relative_to(run_dir))
        except ValueError:
            return str(path)
    return str(path)


def _artifact_href(run_dir: Path, path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if path.is_absolute():
        return _relative_href(run_dir, path_value) if path.exists() else ""
    candidate = run_dir / path
    return str(path) if candidate.exists() else ""


def _normalize_scenario(summary: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    metrics = _scenario_core_metrics(summary)
    memory = _scenario_memory_metrics(summary)
    endpoint_metrics = summary.get("endpoint_metrics", {}) or {}
    scenario_dir = run_dir / "scenarios" / summary["scenario"]
    error_message = (
        summary.get("error", {}).get("message")
        or summary.get("locust", {}).get("reason")
        or endpoint_metrics.get("reason")
        or summary.get("flamegraph_run", {}).get("reason")
        or ""
    )
    artifacts = {
        "scenario_summary_json": str((scenario_dir / "summary.json").relative_to(run_dir)),
        "scenario_summary_md": str((scenario_dir / "summary.md").relative_to(run_dir)),
        "locust_html": summary.get("locust", {}).get("html_report"),
        "profiling_locust_html": summary.get("flamegraph_run", {}).get("html_report"),
        "pyspy_flamegraph": summary.get("pyspy", {}).get("flamegraph"),
        "memray_flamegraph": summary.get("memray", {}).get("flamegraph"),
    }
    return {
        "name": summary["scenario"],
        "description": summary.get("description", ""),
        "scenario_type": summary.get("scenario_type", ""),
        "status": summary.get("status", "unknown"),
        "runtime": summary.get("runtime", {}),
        "load": summary.get("load", {}),
        "measurement": summary.get("measurement", {}),
        "requests": summary.get("requests", {}),
        "plugin_modes": summary.get("plugin_modes", {}),
        "profiling_tools": summary.get("profiling_tools", []),
        "core_metrics": metrics,
        "memory": memory,
        "failure_rate": _scenario_failure_rate(summary),
        "efficiency_score": _scenario_efficiency_score(summary),
        "endpoint_rollups": {
            "top_slowest": [_normalize_endpoint_row(row) for row in endpoint_metrics.get("top_slowest", []) or []],
            "top_hottest": [_normalize_endpoint_row(row) for row in endpoint_metrics.get("top_hottest", []) or []],
            "top_failures": [_normalize_endpoint_row(row) for row in endpoint_metrics.get("top_failures", []) or []],
            "all_endpoints": [_normalize_endpoint_row(row) for row in endpoint_metrics.get("endpoints", []) or []],
        },
        "plugin_rollups": _normalize_plugin_timings(summary),
        "plugin_timing_status": summary.get("plugin_timing", {}).get("status", "unavailable"),
        "profiling": {"pyspy": summary.get("pyspy", {}), "memray": summary.get("memray", {}), "process_stats": summary.get("process_stats", {})},
        "artifacts": artifacts,
        "error_message": error_message,
        "raw_summary": summary,
    }


def _scenario_insight_labels(scenarios: list[dict[str, Any]]) -> dict[str, list[str]]:
    insights: dict[str, list[str]] = {scenario["name"]: [] for scenario in scenarios}
    meaningful = [scenario for scenario in scenarios if scenario["status"] == "ok" and (scenario["core_metrics"]["rps"] > 0 or scenario["core_metrics"]["p95_latency_ms"] > 0)]
    if not meaningful:
        return insights

    best_throughput = max(meaningful, key=lambda item: item["core_metrics"]["rps"])
    lowest_p95 = min(meaningful, key=lambda item: item["core_metrics"]["p95_latency_ms"] or float("inf"))
    lowest_error = min(meaningful, key=lambda item: item["failure_rate"])
    best_efficiency = max(meaningful, key=lambda item: item["efficiency_score"])
    lowest_memory = min(
        meaningful,
        key=lambda item: item["core_metrics"]["rss_mb"] if item["core_metrics"]["rss_mb"] > 0 else float("inf"),
    )
    insights[best_throughput["name"]].append("Best throughput")
    insights[lowest_p95["name"]].append("Lowest p95 latency")
    insights[lowest_error["name"]].append("Lowest error rate")
    insights[best_efficiency["name"]].append("Best efficiency")
    if lowest_memory["core_metrics"]["rss_mb"] > 0:
        insights[lowest_memory["name"]].append("Lowest gateway RSS")

    p95_values = [item["core_metrics"]["p95_latency_ms"] for item in meaningful if item["core_metrics"]["p95_latency_ms"] > 0]
    baseline_p95 = sum(p95_values) / len(p95_values) if p95_values else 0.0
    for scenario in meaningful:
        if scenario["failure_rate"] > 0.0 or (baseline_p95 and scenario["core_metrics"]["p95_latency_ms"] > baseline_p95 * 1.5):
            insights[scenario["name"]].append("Most likely overloaded")
    return insights


def _report_overview(scenarios: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    meaningful = [scenario for scenario in scenarios if scenario["status"] == "ok" and (scenario["core_metrics"]["rps"] > 0 or scenario["core_metrics"]["p95_latency_ms"] > 0)]
    best_throughput = max(meaningful, key=lambda item: item["core_metrics"]["rps"]) if meaningful else None
    lowest_p95 = min(meaningful, key=lambda item: item["core_metrics"]["p95_latency_ms"] or float("inf")) if meaningful else None
    lowest_error = min(meaningful, key=lambda item: item["failure_rate"]) if meaningful else None
    memory_candidates = [item for item in meaningful if item["core_metrics"]["rss_mb"] > 0]
    lowest_memory = min(memory_candidates, key=lambda item: item["core_metrics"]["rss_mb"]) if memory_candidates else None
    most_overloaded = max(meaningful, key=lambda item: (item["failure_rate"], item["core_metrics"]["p95_latency_ms"])) if meaningful else None
    return {
        "scenario_count": len(scenarios),
        "comparison_count": len(comparisons),
        "successful_scenarios": len(meaningful),
        "best_throughput": best_throughput["name"] if best_throughput else None,
        "lowest_p95": lowest_p95["name"] if lowest_p95 else None,
        "lowest_error_rate": lowest_error["name"] if lowest_error else None,
        "lowest_gateway_rss": lowest_memory["name"] if lowest_memory else None,
        "most_overloaded": most_overloaded["name"] if most_overloaded else None,
    }


def _comparison_interpretation(metric_details: dict[str, Any], fairness_warnings: list[str]) -> list[str]:
    notes = []
    rps = metric_details["rps"]
    p95 = metric_details["p95_latency_ms"]
    failures = metric_details["failures"]
    if rps["delta"] > 0 and p95["delta"] < 0:
        notes.append("Right scenario improved throughput and tail latency.")
    elif rps["delta"] > 0 and p95["delta"] > 0:
        notes.append("Right scenario gained throughput but increased tail latency.")
    elif rps["delta"] < 0 and p95["delta"] < 0:
        notes.append("Right scenario traded throughput for lower tail latency.")
    elif rps["delta"] < 0 and p95["delta"] > 0:
        notes.append("Right scenario regressed on both throughput and tail latency.")
    if failures["delta"] > 0:
        notes.append("Right scenario introduced more failures.")
    elif failures["delta"] < 0:
        notes.append("Right scenario reduced failures.")
    if fairness_warnings:
        notes.append("Comparison is directional, not a strict apples-to-apples benchmark.")
    return notes


def _changed_dimensions(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    if left.get("runtime", {}).get("http_server") != right.get("runtime", {}).get("http_server"):
        changed.append("runtime.http_server")
    if left.get("load", {}).get("locustfile") != right.get("load", {}).get("locustfile"):
        changed.append("load.locustfile")
    if left.get("load", {}).get("target_service") != right.get("load", {}).get("target_service"):
        changed.append("load.target_service")
    if left.get("setup", {}).get("auth_mode") != right.get("setup", {}).get("auth_mode"):
        changed.append("setup.auth_mode")
    if left.get("plugin_modes") != right.get("plugin_modes"):
        changed.append("plugins.mode")
    if left.get("requests") != right.get("requests"):
        changed.append("requests")
    return changed


def compare_scenarios(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    metrics_status = "ok"
    left_endpoint = left.get("endpoint_metrics", {})
    right_endpoint = right.get("endpoint_metrics", {})
    if left_endpoint.get("status") != "ok" or right_endpoint.get("status") != "ok":
        metrics_status = "unavailable"
    left_agg = left_endpoint.get("aggregated", {})
    right_agg = right_endpoint.get("aggregated", {})

    plugin_deltas = {}
    left_plugins = left.get("plugin_timing", {}).get("timings", {}) or {}
    right_plugins = right.get("plugin_timing", {}).get("timings", {}) or {}
    for plugin_name in sorted(set(left_plugins) | set(right_plugins)):
        left_hooks = left_plugins.get(plugin_name, {})
        right_hooks = right_plugins.get(plugin_name, {})
        plugin_deltas[plugin_name] = {
            hook: {
                "left": left_hooks.get(hook),
                "right": right_hooks.get(hook),
                **_hook_delta(left_hooks.get(hook), right_hooks.get(hook)),
            }
            for hook in sorted(set(left_hooks) | set(right_hooks))
        }

    fairness = {
        "same_request_mix": left.get("requests") == right.get("requests"),
        "same_measurement": left.get("measurement") == right.get("measurement"),
        "same_runtime": left.get("runtime", {}).get("http_server") == right.get("runtime", {}).get("http_server"),
        "same_target_service": left.get("load", {}).get("target_service") == right.get("load", {}).get("target_service"),
        "same_locustfile": left.get("load", {}).get("locustfile") == right.get("load", {}).get("locustfile"),
    }
    fairness_warnings = []
    if not fairness["same_request_mix"]:
        fairness_warnings.append("Request mix differs between scenarios.")
    if not fairness["same_measurement"]:
        fairness_warnings.append("Measurement windows differ between scenarios.")
    if not fairness["same_runtime"]:
        fairness_warnings.append("HTTP runtime differs between scenarios.")
    if not fairness["same_target_service"]:
        fairness_warnings.append("Target service differs between scenarios.")
    if not fairness["same_locustfile"]:
        fairness_warnings.append("Locust workload file differs between scenarios.")

    metric_details = {
        "requests": _metric_payload(left_agg.get("Request Count"), right_agg.get("Request Count"), higher_is_better=True),
        "rps": _metric_payload(left_agg.get("Requests/s"), right_agg.get("Requests/s"), higher_is_better=True),
        "avg_latency_ms": _metric_payload(left_agg.get("Average Response Time"), right_agg.get("Average Response Time"), higher_is_better=False),
        "p50_latency_ms": _metric_payload(left_agg.get("50%") or left_agg.get("Median Response Time"), right_agg.get("50%") or right_agg.get("Median Response Time"), higher_is_better=False),
        "p95_latency_ms": _metric_payload(left_agg.get("95%"), right_agg.get("95%"), higher_is_better=False),
        "p99_latency_ms": _metric_payload(left_agg.get("99%"), right_agg.get("99%"), higher_is_better=False),
        "max_latency_ms": _metric_payload(left_agg.get("Max Response Time"), right_agg.get("Max Response Time"), higher_is_better=False),
        "failures": _metric_payload(left_agg.get("Failure Count"), right_agg.get("Failure Count"), higher_is_better=False),
        "rss_mb": _metric_payload(_scenario_memory_metrics(left).get("rss_mb"), _scenario_memory_metrics(right).get("rss_mb"), higher_is_better=False),
    }

    metrics: dict[str, Any]
    if metrics_status == "ok":
        metrics = {
            "status": "ok",
            "requests_delta": metric_details["requests"]["delta"],
            "rps_delta": metric_details["rps"]["delta"],
            "p95_delta": metric_details["p95_latency_ms"]["delta"],
            "p99_delta": metric_details["p99_latency_ms"]["delta"],
            "failure_delta": metric_details["failures"]["delta"],
        }
    else:
        metrics = {"status": "unavailable", "reason": "One or both scenarios do not contain executable performance metrics"}

    return {
        "left": left["scenario"],
        "right": right["scenario"],
        "metrics": metrics,
        "metric_details": metric_details,
        "plugin_deltas": plugin_deltas,
        "artifacts": {
            "left_flamegraph": left.get("pyspy", {}).get("flamegraph"),
            "right_flamegraph": right.get("pyspy", {}).get("flamegraph"),
            "left_memray": left.get("memray", {}).get("flamegraph"),
            "right_memray": right.get("memray", {}).get("flamegraph"),
        },
        "integrity": fairness,
        "fairness": {**fairness, "is_apples_to_apples": all(fairness.values()), "warnings": fairness_warnings},
        "changed_dimensions": _changed_dimensions(left, right),
        "interpretation": _comparison_interpretation(metric_details, fairness_warnings),
    }


def _scenario_markdown(summary: dict[str, Any]) -> str:
    endpoint_section = summary["endpoint_metrics"]
    aggregated = endpoint_section.get("aggregated", {})
    measurement_window = endpoint_section.get("measurement_window", {})
    return "\n".join(
        [
            f"# Scenario: {summary['scenario']}",
            "",
            f"- Status: `{summary['status']}`",
            f"- Runtime: `{summary['runtime'].get('http_server', 'unknown')}`",
            f"- Target: `{summary['load'].get('target_service', 'nginx')}`",
            f"- Auth: `{summary['setup'].get('auth_mode', 'none')}`",
            f"- Requests: `{aggregated.get('Request Count', 'n/a')}`",
            f"- RPS: `{aggregated.get('Requests/s', 'n/a')}`",
            f"- p95: `{aggregated.get('95%', 'n/a')}`",
            f"- Failures: `{aggregated.get('Failure Count', 'n/a')}`",
            f"- Gateway RSS MB: `{_scenario_memory_metrics(summary).get('rss_mb', 'n/a')}`",
            f"- Error: `{summary.get('error', {}).get('message', 'none')}`",
            "",
            "## Measurement",
            f"- Endpoint metrics status: `{endpoint_section.get('status')}`",
            f"- Aggregated source: `{endpoint_section.get('aggregated_source', 'n/a')}`",
            f"- Measurement window status: `{measurement_window.get('status', 'n/a')}`",
            "",
            "## Plugin Timing",
            f"- Status: `{summary['plugin_timing'].get('status', 'n/a')}`",
            "",
            "## Profiling",
            f"- Flamegraph run: `{summary['flamegraph_run'].get('status', 'n/a')}`",
            f"- Py-spy: `{summary['pyspy'].get('status', 'n/a')}`",
            f"- Memray: `{summary['memray'].get('status', 'n/a')}`",
            "",
            "## Runtime Metrics",
            f"- Process stats: `{summary['process_stats'].get('status', 'n/a')}`",
            f"- Database metrics: `{summary['database_metrics'].get('status', 'n/a')}`",
            f"- System metrics: `{summary['system_metrics'].get('status', 'n/a')}`",
        ]
    )


def _comparison_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Comparison: {payload['left']} vs {payload['right']}",
            "",
            f"- Changed dimensions: `{', '.join(payload['changed_dimensions']) or 'none'}`",
            f"- Metrics status: `{payload['metrics'].get('status', 'n/a')}`",
            "",
            "## Integrity",
            *(f"- {key}: `{value}`" for key, value in payload["integrity"].items()),
            "",
            "## Interpretation",
            *(f"- {item}" for item in payload.get("interpretation", [])),
            "",
            "## Metrics",
            *(f"- {key}: `{value}`" for key, value in payload["metrics"].items() if key != "status"),
        ]
    )


def _load_scenario_summaries(run_dir: Path) -> list[dict[str, Any]]:
    scenarios_dir = run_dir / "scenarios"
    if not scenarios_dir.exists():
        raise FileNotFoundError(f"No scenarios directory found in {run_dir}")
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(scenarios_dir.glob("*/summary.json"))]
    if not summaries:
        raise FileNotFoundError(f"No scenario summaries found in {scenarios_dir}")
    return summaries


def _build_run_summary(run_dir: Path, scenario_summaries: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    scenarios = []
    for summary in scenario_summaries:
        aggregated = summary.get("endpoint_metrics", {}).get("aggregated", {})
        scenarios.append(
            {
                "scenario": summary["scenario"],
                "status": summary["status"],
                "runtime": summary.get("runtime", {}).get("http_server"),
                "target_service": summary.get("load", {}).get("target_service", "nginx"),
                "auth_mode": summary.get("setup", {}).get("auth_mode", "none"),
                "users": summary.get("load", {}).get("users"),
                "run_time": summary.get("load", {}).get("run_time"),
                "requests": aggregated.get("Request Count"),
                "rps": aggregated.get("Requests/s"),
                "p95": aggregated.get("95%"),
                "failures": aggregated.get("Failure Count"),
                "gateway_rss_mb": _scenario_memory_metrics(summary).get("rss_mb"),
                "scenario_dir": str(run_dir / "scenarios" / summary["scenario"]),
            }
        )
    return {
        "metadata": metadata or {},
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "statuses": {status: sum(1 for item in scenarios if item["status"] == status) for status in sorted({item["status"] for item in scenarios})},
    }


def _run_summary_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Benchmark Run Summary", ""]
    for scenario in payload.get("scenarios", []):
        lines.append(
            f"- `{scenario['scenario']}`: status={scenario['status']}, runtime={scenario['runtime']}, target={scenario['target_service']}, "
            f"rps={scenario['rps']}, p95={scenario['p95']}, failures={scenario['failures']}, gateway_rss_mb={scenario.get('gateway_rss_mb')}"
        )
    return "\n".join(lines)


def _baseline_thresholds(suite_meta: dict[str, Any]) -> dict[str, float]:
    return {
        "rps_drop_pct": float(suite_meta.get("baseline_rps_drop_pct", 10) or 10),
        "p95_regression_pct": float(suite_meta.get("baseline_p95_regression_pct", 15) or 15),
        "failure_increase": float(suite_meta.get("baseline_failure_increase", 0) or 0),
    }


def _load_baseline_run(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_against_baseline(run_summary: dict[str, Any], baseline_summary: dict[str, Any], suite_meta: dict[str, Any]) -> dict[str, Any]:
    thresholds = _baseline_thresholds(suite_meta)
    baseline_by_scenario = {item["scenario"]: item for item in baseline_summary.get("scenarios", [])}
    comparisons = []
    for scenario in run_summary.get("scenarios", []):
        baseline = baseline_by_scenario.get(scenario["scenario"])
        if not baseline:
            comparisons.append({"scenario": scenario["scenario"], "status": "missing_baseline"})
            continue
        baseline_rps = _numeric(baseline.get("rps"))
        baseline_p95 = _numeric(baseline.get("p95"))
        baseline_failures = _numeric(baseline.get("failures"))
        current_rps = _numeric(scenario.get("rps"))
        current_p95 = _numeric(scenario.get("p95"))
        current_failures = _numeric(scenario.get("failures"))
        rps_drop_pct = ((baseline_rps - current_rps) / baseline_rps * 100) if baseline_rps else 0
        p95_regression_pct = ((current_p95 - baseline_p95) / baseline_p95 * 100) if baseline_p95 else 0
        failure_increase = current_failures - baseline_failures
        passed = (
            rps_drop_pct <= thresholds["rps_drop_pct"]
            and p95_regression_pct <= thresholds["p95_regression_pct"]
            and failure_increase <= thresholds["failure_increase"]
        )
        comparisons.append(
            {
                "scenario": scenario["scenario"],
                "status": "pass" if passed else "fail",
                "rps_drop_pct": rps_drop_pct,
                "p95_regression_pct": p95_regression_pct,
                "failure_increase": failure_increase,
            }
        )
    return {"thresholds": thresholds, "comparisons": comparisons}


def _baseline_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Baseline Comparison", ""]
    for item in payload.get("comparisons", []):
        lines.append(
            f"- `{item['scenario']}`: status={item['status']}, rps_drop_pct={item.get('rps_drop_pct')}, "
            f"p95_regression_pct={item.get('p95_regression_pct')}, failure_increase={item.get('failure_increase')}"
        )
    return "\n".join(lines)


def _build_unified_report(run_dir: Path, scenario_summaries: list[dict[str, Any]], comparison_pairs: list[dict[str, Any]], suite_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    scenarios = [_normalize_scenario(summary, run_dir) for summary in scenario_summaries]
    insight_labels = _scenario_insight_labels(scenarios)
    for scenario in scenarios:
        scenario["insights"] = insight_labels.get(scenario["name"], [])

    meaningful = [scenario for scenario in scenarios if scenario["status"] == "ok" and (scenario["core_metrics"]["rps"] > 0 or scenario["core_metrics"]["p95_latency_ms"] > 0)]
    recommendations = []
    best_throughput = max(meaningful, key=lambda item: item["core_metrics"]["rps"]) if meaningful else None
    lowest_p95 = min(meaningful, key=lambda item: item["core_metrics"]["p95_latency_ms"] or float("inf")) if meaningful else None
    overloaded = [scenario for scenario in meaningful if "Most likely overloaded" in scenario.get("insights", [])]
    if best_throughput:
        recommendations.append(f"Use {best_throughput['name']} when raw throughput is the priority.")
    if lowest_p95:
        recommendations.append(f"Use {lowest_p95['name']} when predictable tail latency matters most.")
    memory_candidates = [scenario for scenario in meaningful if scenario["core_metrics"]["rss_mb"] > 0]
    if memory_candidates:
        lowest_memory = min(memory_candidates, key=lambda item: item["core_metrics"]["rss_mb"])
        recommendations.append(f"Use {lowest_memory['name']} when minimizing gateway RSS matters most.")
    if overloaded:
        recommendations.append(f"Review load, worker count, or plugin overhead for {', '.join(item['name'] for item in overloaded)}.")
    if not meaningful:
        recommendations.append("No scenario completed successfully; fix the reported setup/runtime errors before comparing performance.")

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "suite_summary": suite_summary or {},
        "overview": _report_overview(scenarios, comparison_pairs),
        "scenarios": scenarios,
        "comparisons": comparison_pairs,
        "recommendations": recommendations,
    }


def _metric_cell(metric: float | None, suffix: str = "") -> str:
    if metric is None:
        return "n/a"
    return f"{metric:,.2f}{suffix}"


def _markdown_table_cell(value: Any) -> str:
    text = str(value if value is not None else "n/a")
    return text.replace("|", "\\|").replace("\n", "<br>")


def _scenario_comparison_report_markdown(report: dict[str, Any]) -> str:
    lines = ["# Scenario Comparison Report", ""]
    overview = report["overview"]
    lines.extend(
        [
            f"- Scenarios: `{overview['scenario_count']}`",
            f"- Pairwise comparisons: `{overview['comparison_count']}`",
            f"- Best throughput: `{overview.get('best_throughput') or 'n/a'}`",
            f"- Lowest p95: `{overview.get('lowest_p95') or 'n/a'}`",
            f"- Lowest gateway RSS: `{overview.get('lowest_gateway_rss') or 'n/a'}`",
            "",
            "## Recommendations",
        ]
    )
    lines.extend(f"- {item}" for item in report["recommendations"])
    lines.extend(
        [
            "",
            "## Scenario Highlights",
            "",
            "| Scenario | Status | Runtime | RPS | p95 | Gateway RSS | Gateway VMS | Failures | Insights | Error |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for scenario in report["scenarios"]:
        metrics = scenario["core_metrics"]
        labels = ", ".join(scenario.get("insights", [])) or "no standout signal"
        failure = scenario.get("error_message") or "none"
        lines.append(
            f"| `{_markdown_table_cell(scenario['name'])}` | `{_markdown_table_cell(scenario['status'])}` | `{_markdown_table_cell(scenario['runtime'].get('http_server', 'unknown'))}` | "
            f"{_markdown_table_cell(_metric_cell(metrics['rps']))} | {_markdown_table_cell(_metric_cell(metrics['p95_latency_ms'], ' ms'))} | "
            f"{_markdown_table_cell(_metric_cell(metrics['rss_mb'], ' MB'))} | {_markdown_table_cell(_metric_cell(metrics['vms_mb'], ' MB'))} | "
            f"{_markdown_table_cell(_metric_cell(metrics['failures']))} | {_markdown_table_cell(labels)} | {_markdown_table_cell(failure)} |"
        )
    lines.extend(
        [
            "",
            "## Pairwise Deltas",
            "",
            "| Left | Right | RPS Delta | p95 Delta | Gateway RSS Delta | Fair | Notes |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in report["comparisons"]:
        metric_details = item.get("metric_details", {})
        fairness_warnings = item.get("fairness", {}).get("warnings", [])
        notes = "; ".join(item.get("interpretation", []) + fairness_warnings) or "none"
        lines.append(
            f"| `{_markdown_table_cell(item['left'])}` | `{_markdown_table_cell(item['right'])}` | "
            f"{_markdown_table_cell(_metric_cell(_numeric(metric_details.get('rps', {}).get('delta'))))} | "
            f"{_markdown_table_cell(_metric_cell(_numeric(metric_details.get('p95_latency_ms', {}).get('delta')), ' ms'))} | "
            f"{_markdown_table_cell(_metric_cell(_numeric(metric_details.get('rss_mb', {}).get('delta')), ' MB'))} | "
            f"{_markdown_table_cell('yes' if item.get('fairness', {}).get('is_apples_to_apples') else 'no')} | {_markdown_table_cell(notes)} |"
        )
    return "\n".join(lines)


def _scenario_comparison_report_html(report: dict[str, Any], run_dir: Path) -> str:
    overview = report["overview"]
    rows = []
    sections = []
    for scenario in report["scenarios"]:
        metrics = scenario["core_metrics"]
        tags = "".join(f'<span class="pill">{escape(tag)}</span>' for tag in scenario.get("insights", []))
        rows.append(
            """
            <tr>
              <td><strong>{name}</strong><div class="muted">{runtime}</div></td>
              <td><span class="status {badge}">{status}</span></td>
              <td>{rps}</td>
              <td>{p95}</td>
              <td>{rss}</td>
              <td>{failures}</td>
              <td>{efficiency:.4f}</td>
              <td>{insights}</td>
              <td>{error}</td>
            </tr>
            """.format(
                name=escape(scenario["name"]),
                runtime=escape(scenario["runtime"].get("http_server", "unknown")),
                badge=_status_badge(scenario["status"]),
                status=escape(scenario["status"]),
                rps=escape(_metric_cell(metrics["rps"])),
                p95=escape(_metric_cell(metrics["p95_latency_ms"], " ms")),
                rss=escape(_metric_cell(metrics["rss_mb"], " MB")),
                failures=escape(_metric_cell(metrics["failures"])),
                efficiency=scenario["efficiency_score"],
                insights=tags or '<span class="muted">No standout signal</span>',
                error=escape(scenario.get("error_message") or "none"),
            )
        )
        artifact_links = []
        for label, value in (
            ("Summary JSON", scenario["artifacts"]["scenario_summary_json"]),
            ("Summary Markdown", scenario["artifacts"]["scenario_summary_md"]),
            ("Locust HTML", _artifact_href(run_dir, scenario["artifacts"].get("locust_html"))),
            ("Profiling Locust HTML", _artifact_href(run_dir, scenario["artifacts"].get("profiling_locust_html"))),
            ("py-spy Flamegraph", _artifact_href(run_dir, scenario["artifacts"].get("pyspy_flamegraph"))),
            ("Memray Flamegraph", _artifact_href(run_dir, scenario["artifacts"].get("memray_flamegraph"))),
        ):
            if value:
                artifact_links.append(f'<a href="{escape(value)}">{escape(label)}</a>')
        slowest = "".join(
            f"<li><code>{escape(item['name'])}</code> <span>{escape(_metric_cell(item['p95_latency_ms'], ' ms'))}</span></li>"
            for item in scenario["endpoint_rollups"]["top_slowest"][:5]
        ) or "<li class='muted'>No endpoint data</li>"
        sections.append(
            """
            <section class="scenario-card">
              <h2>{name}</h2>
              <p class="muted">status={status} runtime={runtime} target={target}</p>
              <p class="muted">gateway memory rss={rss} | gateway memory vms={vms}</p>
              <p>{error}</p>
              <p class="artifact-links">{artifacts}</p>
              <h3>Top slowest endpoints</h3>
              <ul>{slowest}</ul>
            </section>
            """.format(
                name=escape(scenario["name"]),
                status=escape(scenario["status"]),
                runtime=escape(scenario["runtime"].get("http_server", "unknown")),
                target=escape(scenario["load"].get("target_service", "nginx")),
                rss=escape(_metric_cell(metrics["rss_mb"], " MB")),
                vms=escape(_metric_cell(metrics["vms_mb"], " MB")),
                error=escape(scenario.get("error_message") or "No explicit error."),
                artifacts=" | ".join(artifact_links) if artifact_links else "<span class='muted'>No linked artifacts</span>",
                slowest=slowest,
            )
        )

    comparisons_html = []
    for item in report["comparisons"]:
        fairness_warnings = item.get("fairness", {}).get("warnings", [])
        comparisons_html.append(
            """
            <tr>
              <td>{left}</td>
              <td>{right}</td>
              <td>{rps}</td>
              <td>{p95}</td>
              <td>{rss}</td>
              <td>{fair}</td>
              <td>{notes}</td>
            </tr>
            """.format(
                left=escape(item["left"]),
                right=escape(item["right"]),
                rps=escape(_metric_cell(item.get("metric_details", {}).get("rps", {}).get("delta", 0))),
                p95=escape(_metric_cell(item.get("metric_details", {}).get("p95_latency_ms", {}).get("delta", 0), " ms")),
                rss=escape(_metric_cell(item.get("metric_details", {}).get("rss_mb", {}).get("delta", 0), " MB")),
                fair=escape("yes" if item.get("fairness", {}).get("is_apples_to_apples") else "no"),
                notes=escape("; ".join(item.get("interpretation", []) + fairness_warnings) or "none"),
            )
        )

    recommendations = "".join(f"<li>{escape(item)}</li>" for item in report["recommendations"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Unified Scenario Comparison Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --border: #334155;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --link: #7dd3fc;
      --pill: #1e3a5f;
      --good: #86efac;
      --bad: #fca5a5;
      --warn: #fcd34d;
      --neutral: #cbd5e1;
    }}
    body {{ font-family: sans-serif; margin: 2rem; color: var(--text); background: radial-gradient(circle at top, #172554 0%, var(--bg) 42%); }}
    a {{ color: var(--link); }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; background: rgba(17, 24, 39, 0.86); }}
    th, td {{ border: 1px solid var(--border); padding: 0.6rem; text-align: left; vertical-align: top; }}
    th {{ background: rgba(30, 41, 59, 0.96); }}
    .muted {{ color: var(--muted); }}
    .pill {{ display: inline-block; background: var(--pill); color: var(--text); padding: 0.1rem 0.5rem; border-radius: 999px; margin-right: 0.25rem; }}
    .status.good {{ color: var(--good); }}
    .status.bad {{ color: var(--bad); }}
    .status.warn {{ color: var(--warn); }}
    .status.neutral {{ color: var(--neutral); }}
    .scenario-card {{ border: 1px solid var(--border); background: rgba(17, 24, 39, 0.88); padding: 1rem; margin: 1rem 0; border-radius: 0.75rem; box-shadow: 0 12px 28px rgba(0, 0, 0, 0.28); }}
    .artifact-links a {{ margin-right: 0.75rem; }}
  </style>
</head>
<body>
  <h1>Unified Scenario Comparison Report</h1>
  <p>Scenarios: <strong>{overview['scenario_count']}</strong> | Pairwise comparisons: <strong>{overview['comparison_count']}</strong> | Successful scenarios: <strong>{overview['successful_scenarios']}</strong></p>
  <ul>{recommendations}</ul>
  <h2>Scenario Scoreboard</h2>
  <table>
    <thead><tr><th>Scenario</th><th>Status</th><th>RPS</th><th>p95</th><th>Gateway RSS</th><th>Failures</th><th>Efficiency</th><th>Insights</th><th>Error</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <h2>Pairwise Deltas</h2>
  <table>
    <thead><tr><th>Left</th><th>Right</th><th>RPS delta</th><th>p95 delta</th><th>Gateway RSS delta</th><th>Fair</th><th>Notes</th></tr></thead>
    <tbody>{''.join(comparisons_html) or '<tr><td colspan="7">No comparisons</td></tr>'}</tbody>
  </table>
  <h2>Scenario Details</h2>
  {''.join(sections)}
</body>
</html>"""


def _load_suite_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "suite_summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    resolved_path = run_dir / "resolved_suite.json"
    if resolved_path.exists():
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        suite = resolved.get("suite", {})
        scenarios = resolved.get("scenarios", [])
        return {"suite": suite, "scenario_order": [scenario.get("name") for scenario in scenarios], "scenario_count": len(scenarios)}
    return {}


def _write_comparisons(run_dir: Path, scenario_summaries: list[dict[str, Any]], suite_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    comparison_pairs = []
    for left, right in itertools.combinations(scenario_summaries, 2):
        comparison = compare_scenarios(left, right)
        pair_dir = run_dir / "comparisons" / f"{left['scenario']}__vs__{right['scenario']}"
        _write_json(pair_dir / "comparison.json", comparison)
        _write_markdown(pair_dir / "comparison.md", _comparison_markdown(comparison))
        comparison_pairs.append(comparison)
    matrix = {"scenarios": [summary["scenario"] for summary in scenario_summaries], "comparisons": comparison_pairs}
    _write_json(run_dir / "comparison_matrix.json", matrix)
    _write_markdown(
        run_dir / "comparison_matrix.md",
        "# Comparison Matrix\n\nPrimary entrypoint: `scenario_comparison_report.html`\n\n" + "\n".join(f"- `{item['left']}` vs `{item['right']}`" for item in comparison_pairs),
    )
    report = _build_unified_report(run_dir, scenario_summaries, comparison_pairs, suite_summary=suite_summary)
    _write_json(run_dir / "scenario_comparison_report.json", report)
    _write_markdown(run_dir / "scenario_comparison_report.md", _scenario_comparison_report_markdown(report))
    _write_markdown(run_dir / "scenario_comparison_report.html", _scenario_comparison_report_html(report, run_dir))
    return report


def regenerate_reports(run_dir: Path) -> Path:
    scenario_summaries = _load_scenario_summaries(run_dir)
    metadata = {}
    suite_meta: dict[str, Any] = {}
    metadata_path = run_dir / "run_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    resolved_suite_path = run_dir / "resolved_suite.json"
    if resolved_suite_path.exists():
        suite_meta = json.loads(resolved_suite_path.read_text(encoding="utf-8")).get("suite", {})
    for summary in scenario_summaries:
        scenario_dir = run_dir / "scenarios" / summary["scenario"]
        _write_markdown(scenario_dir / "summary.md", _scenario_markdown(summary))
    suite_summary = _load_suite_summary(run_dir)
    suite_summary.update({"scenario_order": [summary["scenario"] for summary in scenario_summaries], "scenario_count": len(scenario_summaries), "metadata": metadata})
    _write_comparisons(run_dir, scenario_summaries, suite_summary=suite_summary)
    run_summary = _build_run_summary(run_dir, scenario_summaries, metadata=metadata)
    _write_json(run_dir / "run_summary.json", run_summary)
    _write_markdown(run_dir / "run_summary.md", _run_summary_markdown(run_summary))
    baseline_run = suite_meta.get("baseline_run")
    if baseline_run:
        baseline_payload = _compare_against_baseline(run_summary, _load_baseline_run(Path(baseline_run)), suite_meta)
        _write_json(run_dir / "baseline_comparison.json", baseline_payload)
        _write_markdown(run_dir / "baseline_comparison.md", _baseline_markdown(baseline_payload))
    _write_json(run_dir / "suite_summary.json", suite_summary)
    _write_markdown(run_dir / "suite_summary.md", "# Suite Summary\n\nPrimary entrypoint: `scenario_comparison_report.html`\n\n" + "\n".join(f"- `{summary['scenario']}`" for summary in scenario_summaries))
    return run_dir


def _compose_ps(compose_args: list[str], shell_command: str) -> subprocess.CompletedProcess[str]:
    return _run_compose(compose_args, ["exec", "-T", "gateway", "sh", "-lc", shell_command], check=False)


def _resolve_profile_pid(compose_args: list[str]) -> dict[str, Any]:
    command = (
        "python3 - <<'PY'\n"
        "import json, subprocess\n"
        "out = subprocess.run(['ps', '-eo', 'pid=,pcpu=,comm=,args='], capture_output=True, text=True, check=False).stdout.splitlines()\n"
        "rows = []\n"
        "for line in out:\n"
        "    parts = line.strip().split(None, 3)\n"
        "    if len(parts) < 4:\n"
        "        continue\n"
        "    pid, cpu, comm, args = parts\n"
        "    if not any(token in args for token in ('gunicorn', 'granian', 'uvicorn')):\n"
        "        continue\n"
        "    rows.append({'pid': int(pid), 'cpu': float(cpu), 'comm': comm, 'args': args})\n"
        "rows.sort(key=lambda row: (row['cpu'], row['pid']), reverse=True)\n"
        "print(json.dumps({'selected_pid': rows[0]['pid'] if rows else 1, 'candidates': rows[:10]}))\n"
        "PY"
    )
    result = _compose_ps(compose_args, command)
    if result.returncode != 0 or not (result.stdout or "").strip():
        return {"selected_pid": 1, "candidates": [], "status": "failed", "stderr": (result.stderr or "")[-2000:]}
    payload = json.loads((result.stdout or "").strip().splitlines()[-1])
    payload["status"] = "ok"
    return payload


def _docker_exec_background(runtime: ContainerRuntime, compose_args: list[str], shell_command: str) -> subprocess.Popen[str]:
    container_id = _service_container_id(compose_args, "gateway")
    return subprocess.Popen(
        [runtime.engine, "exec", container_id, "sh", "-lc", shell_command],
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _capture_logs(compose_args: list[str], scenario_dir: Path, attempt: int) -> list[str]:
    log_paths: list[str] = []
    for service in ("gateway", "nginx", "postgres", "redis", "pgbouncer", "fast_time_server", "register_fast_time", "a2a_echo_agent", "register_a2a_echo"):
        result = _run_compose(compose_args, ["logs", "--no-color", service], check=False)
        if result.returncode != 0:
            result = _run_compose(compose_args, ["logs", service], check=False)
        log_path = scenario_dir / f"attempt_{attempt}" / f"{service}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""), encoding="utf-8")
        log_paths.append(str(log_path))
    return log_paths


def _runtime_metadata(runtime: ContainerRuntime) -> dict[str, Any]:
    git_sha = _run_command(["git", "rev-parse", "HEAD"], check=False)
    compose_version = _run_command([*runtime.compose_cmd, "version"], check=False)
    engine_version = _run_command([runtime.engine, "--version"], check=False)
    locust_version = _run_command([sys.executable, "-m", "benchmarks.contextforge", "--list"], check=False)
    return {
        "git_sha": (git_sha.stdout or "").strip(),
        "container_runtime": runtime.engine,
        "compose_command": list(runtime.compose_cmd),
        "compose_version": (compose_version.stdout or compose_version.stderr or "").strip(),
        "engine_version": (engine_version.stdout or engine_version.stderr or "").strip(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "benchmark_runner_list_output": (locust_version.stdout or "").strip(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _image_metadata(runtime: ContainerRuntime, image_name: str) -> dict[str, Any]:
    inspect = _run_command([runtime.engine, "image", "inspect", image_name], check=False)
    if inspect.returncode != 0 or not (inspect.stdout or "").strip():
        return {"status": "missing", "image": image_name}
    try:
        payload = json.loads(inspect.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError):
        return {"status": "unknown", "image": image_name}
    return {
        "status": "ok",
        "image": image_name,
        "id": payload.get("Id"),
        "repo_tags": payload.get("RepoTags", []),
        "repo_digests": payload.get("RepoDigests", []),
    }


def _preflight_runtime(runtime: ContainerRuntime, suite: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    scenario_checks: list[dict[str, Any]] = []
    for scenario in suite["scenarios"]:
        build = scenario.get("build", {})
        profiling = scenario.get("profiling", {})
        image_name = _scenario_image_name(scenario)
        image_info = _image_metadata(runtime, image_name)
        profiling_tools_available = {"py_spy": None, "memray": None}
        if image_info.get("status") == "ok" and build.get("profiling_image", False):
            for tool in profiling_tools_available:
                probe = _run_command([runtime.engine, "run", "--rm", "--entrypoint", "sh", image_name, "-lc", f"command -v {tool}"], check=False)
                profiling_tools_available[tool] = probe.returncode == 0
        if profiling.get("enabled") and ("py_spy" in set(profiling.get("tools", []) or []) or profiling.get("py_spy")) and not build.get("profiling_image", False):
            warnings.append(f"Scenario '{scenario['name']}' enables profiling but build.profiling_image is false")
        if build.get("rebuild_policy", "never") == "never":
            if image_info.get("status") != "ok":
                warnings.append(f"Scenario '{scenario['name']}' expects prebuilt image '{image_name}'")
        scenario_checks.append(
            {
                "scenario": scenario["name"],
                "image": image_info,
                "profiling_tools_available": profiling_tools_available,
            }
        )
    token_check = _run_command([sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin@example.com", "--exp", "1", "--secret", "my-test-key"], check=False)
    return {
        **_runtime_metadata(runtime),
        "warnings": warnings,
        "scenario_checks": scenario_checks,
        "token_generation_available": token_check.returncode == 0,
        "token_generation_stderr": (token_check.stderr or "")[-1000:],
    }


def _profiling_tools(scenario: dict[str, Any]) -> set[str]:
    profiling = scenario.get("profiling", {}) or {}
    tools = set(profiling.get("tools", []) or [])
    if profiling.get("py_spy"):
        tools.add("py_spy")
    return tools


def _scenario_setup_for_summary(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "setup": scenario.get("setup", {}),
        "runtime": scenario.get("runtime", {}),
        "load": scenario.get("load", {}),
        "measurement": scenario.get("measurement", {}),
        "requests": scenario.get("requests", {}),
        "plugin_modes": {name: (cfg or {}).get("mode", "auto") for name, cfg in (scenario.get("plugins", {}) or {}).items()},
        "profiling_tools": sorted(_profiling_tools(scenario)),
    }


def _profiling_variant(scenario: dict[str, Any]) -> dict[str, Any]:
    profiling_scenario = deepcopy(scenario)
    profiling_scenario.setdefault("execution", {})["reuse_stack"] = False
    runtime = profiling_scenario.setdefault("runtime", {})
    runtime.setdefault("gunicorn", {})
    runtime.setdefault("granian", {})
    runtime.setdefault("uvicorn", {})
    runtime["gunicorn"]["workers"] = 1
    runtime["granian"]["workers"] = 1
    runtime["uvicorn"]["workers"] = 1
    return profiling_scenario


def _execute_single_attempt(runtime: ContainerRuntime, scenario: dict[str, Any], scenario_dir: Path, flamegraph_enabled: bool, capture_logs: bool, attempt: int) -> dict[str, Any]:
    compose_args: list[str] | None = None
    reuse_stack = bool((scenario.get("execution", {}) or {}).get("reuse_stack", False))
    status = "failed"
    locust_result: dict[str, Any] = {"status": "unavailable", "reason": "Attempt did not start"}
    endpoint_metrics: dict[str, Any] = {"status": "unavailable", "reason": "Attempt did not start"}
    log_paths: list[str] = []
    pyspy = {"status": "unavailable", "reason": "Suite flamegraph capture disabled"}
    flamegraph_run = {"status": "unavailable", "reason": "Suite flamegraph capture disabled"}
    memray = {"status": "unavailable", "reason": "Suite flamegraph capture disabled"}
    process_stats = {"status": "unavailable", "reason": "Suite flamegraph capture disabled"}
    database_metrics = {"status": "unavailable", "reason": "Compose stack was not available"}
    system_metrics = {"status": "unavailable", "reason": "Compose stack was not available"}
    try:
        _emit_progress(f"{scenario['name']}: starting services for attempt {attempt}")
        compose_args, project_name = _start_docker_stack(runtime, scenario, scenario_dir)
        load = scenario.get("load", {}) or {}
        run_time_str = str(load.get("run_time", "n/a"))
        _emit_progress(
            f"{scenario['name']}: running load against {load.get('target_service', 'nginx')} on {scenario.get('runtime', {}).get('http_server', 'unknown')} "
            f"(run_time={run_time_str}; no further output until load finishes)"
        )
        locust_result = _run_docker_locust(runtime, compose_args, project_name, scenario, scenario_dir, artifact_prefix="locust_metrics")
        endpoint_metrics = _collect_endpoint_metrics(locust_result["csv_prefix"], scenario.get("measurement", {}))
        status = locust_result.get("status", "unknown")
        _emit_progress(f"{scenario['name']}: load phase finished with status={status}")
    except Exception as exc:  # pragma: no cover - exercised via mocked integration tests
        status = "failed"
        locust_result = {"status": "failed", "reason": str(exc)}
        endpoint_metrics = {"status": "unavailable", "reason": str(exc)}
        flamegraph_run = {"status": "failed", "reason": str(exc)}
        _emit_progress(f"{scenario['name']}: attempt {attempt} failed during load/setup: {exc}")
    finally:
        if compose_args:
            database_metrics = _collect_database_metrics(compose_args)
            system_metrics = _collect_system_metrics(compose_args)
        if compose_args and capture_logs and status != "ok" and not log_paths:
            log_paths = _capture_logs(compose_args, scenario_dir, attempt)
            _emit_progress(f"{scenario['name']}: captured failure logs for attempt {attempt}")
        if compose_args:
            if reuse_stack and status == "ok":
                _emit_progress(f"{scenario['name']}: keeping persistent benchmark stack warm after attempt {attempt}")
            else:
                _stop_docker_stack(compose_args)
                _emit_progress(f"{scenario['name']}: stopped services for attempt {attempt}")

    if status == "ok" and flamegraph_enabled and scenario.get("profiling", {}).get("enabled") and _profiling_tools(scenario):
        profiling_compose_args: list[str] | None = None
        try:
            profiling_scenario = _profiling_variant(scenario)
            _emit_progress(f"{scenario['name']}: starting single-worker profiling pass")
            profiling_compose_args, profiling_project_name = _start_docker_stack(runtime, profiling_scenario, scenario_dir)
            flame_locust_process = _start_docker_locust_background(runtime, profiling_compose_args, profiling_project_name, profiling_scenario, scenario_dir, "locust_flamegraph")
            pid_info = _resolve_profile_pid(profiling_compose_args)
            gateway_pid = int(pid_info.get("selected_pid", 1) or 1)
            process_stats_result = _compose_ps(profiling_compose_args, f"ps -o pid=,%cpu=,%mem=,rss=,vsz=,command= -p {gateway_pid}")
            process_stats = {
                "status": "ok" if process_stats_result.returncode == 0 else "unavailable",
                "snapshot": (process_stats_result.stdout or "").strip() or (process_stats_result.stderr or "").strip(),
                "pid_candidates": pid_info.get("candidates", []),
                "selected_pid": gateway_pid,
                "profiling_workers": 1,
            }
            duration = int(scenario.get("profiling", {}).get("duration_seconds", 0) or scenario.get("measurement", {}).get("profile_seconds", 0) or 5)
            pyspy_proc = None
            memray_proc = None
            if "py_spy" in _profiling_tools(scenario):
                pyspy_cmd = f"mkdir -p /mnt/bench/pyspy && py-spy record -o /mnt/bench/pyspy/flamegraph.svg --pid {gateway_pid} -d {duration} --subprocesses"
                pyspy_proc = _docker_exec_background(runtime, profiling_compose_args, pyspy_cmd)
            if "memray" in _profiling_tools(scenario):
                memray_cmd = f"mkdir -p /mnt/bench/memray && timeout {duration} memray attach --aggregate {gateway_pid} -o /mnt/bench/memray/profile.bin || true"
                memray_proc = _docker_exec_background(runtime, profiling_compose_args, memray_cmd)
            flame_stdout, flame_stderr = flame_locust_process.communicate()
            if pyspy_proc is not None:
                _, pyspy_stderr = pyspy_proc.communicate(timeout=30)
                _compose_ps(profiling_compose_args, f"py-spy dump --pid {gateway_pid} > /mnt/bench/pyspy/dump.txt || true")
                pyspy = {
                    "status": "ok" if (scenario_dir / "pyspy" / "flamegraph.svg").exists() else "failed",
                    "flamegraph": str(scenario_dir / "pyspy" / "flamegraph.svg"),
                    "dump": str(scenario_dir / "pyspy" / "dump.txt"),
                    "stderr": (pyspy_stderr or "")[-2000:],
                    "profiling_workers": 1,
                }
            if memray_proc is not None:
                _, memray_stderr = memray_proc.communicate(timeout=30)
                if (scenario_dir / "memray" / "profile.bin").exists():
                    _compose_ps(profiling_compose_args, "memray flamegraph /mnt/bench/memray/profile.bin -o /mnt/bench/memray/flamegraph.html || true")
                    _compose_ps(profiling_compose_args, "memray stats /mnt/bench/memray/profile.bin > /mnt/bench/memray/stats.txt || true")
                    memray = {
                        "status": "ok",
                        "raw": str(scenario_dir / "memray" / "profile.bin"),
                        "flamegraph": str(scenario_dir / "memray" / "flamegraph.html"),
                        "stats": str(scenario_dir / "memray" / "stats.txt"),
                        "stderr": (memray_stderr or "")[-2000:],
                        "profiling_workers": 1,
                    }
            flamegraph_run = {
                "status": "ok" if flame_locust_process.returncode == 0 else "failed",
                "returncode": flame_locust_process.returncode,
                "stdout": (flame_stdout or "")[-4000:],
                "stderr": (flame_stderr or "")[-4000:],
                "html_report": str(scenario_dir / "locust_flamegraph_report.html"),
                "csv_prefix": str(scenario_dir / "locust_flamegraph"),
                "profiling_workers": 1,
            }
            _emit_progress(f"{scenario['name']}: profiling pass finished with status={flamegraph_run['status']}")
        except Exception as exc:  # pragma: no cover - exercised via mocked integration tests
            flamegraph_run = {"status": "failed", "reason": str(exc), "profiling_workers": 1}
            _emit_progress(f"{scenario['name']}: profiling pass failed: {exc}")
        finally:
            if profiling_compose_args and capture_logs and flamegraph_run.get("status") != "ok":
                log_paths.extend(_capture_logs(profiling_compose_args, scenario_dir, attempt))
                _emit_progress(f"{scenario['name']}: captured profiling logs for attempt {attempt}")
            if profiling_compose_args:
                _stop_docker_stack(profiling_compose_args)
                _emit_progress(f"{scenario['name']}: stopped profiling services")

    plugin_timing = _collect_plugin_timing(scenario_dir)
    return {
        "status": status,
        "locust": locust_result,
        "endpoint_metrics": endpoint_metrics,
        "plugin_timing": plugin_timing,
        "pyspy": pyspy,
        "memray": memray,
        "process_stats": process_stats,
        "flamegraph_run": flamegraph_run,
        "database_metrics": database_metrics,
        "system_metrics": system_metrics,
        "log_paths": log_paths,
    }


def execute_suite(profile: str, validate_only: bool = False, smoke: bool = False, output_root: Path | None = None, check_runtime_only: bool = False, run_all: bool = False) -> Path:
    scenario_label, scenario_paths, suite = resolve_scenario_collection(selection=profile, run_all=run_all, smoke=smoke)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    root = output_root or Path(suite["suite"].get("output_root") or DEFAULT_OUTPUT_ROOT)
    requested_run_dir = root / f"{scenario_label}_{timestamp}"
    if len(scenario_paths) == 1:
        _emit_progress(f"using scenario file {scenario_paths[0]}")
    else:
        _emit_progress(f"using {len(scenario_paths)} scenario files from {SCENARIO_DIR}")
    _emit_progress(f"preparing benchmark artifacts under {requested_run_dir}")
    if check_runtime_only or not validate_only:
        _emit_progress("detecting container runtime")
    runtime = _detect_runtime() if (check_runtime_only or not validate_only) else None
    run_dir = requested_run_dir
    if runtime is not None and not validate_only and not check_runtime_only and not _is_mountable_runtime_path(requested_run_dir):
        run_dir = RUNTIME_STAGING_ROOT / f"{scenario_label}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _emit_progress(f"writing benchmark artifacts under {requested_run_dir}")
    if run_dir != requested_run_dir:
        _emit_progress(f"using runtime staging directory {run_dir}")

    metadata = _preflight_runtime(runtime, suite) if runtime else {"mode": "validate", "generated_at": datetime.now(timezone.utc).isoformat()}
    metadata["scenario"] = profile
    metadata["scenario_files"] = [str(path) for path in scenario_paths]
    metadata["mode"] = "check-runtime" if check_runtime_only else ("validate" if validate_only else "execute")
    if run_dir != requested_run_dir:
        metadata["requested_output_dir"] = str(requested_run_dir)
        metadata["runtime_output_dir"] = str(run_dir)
    _write_json(run_dir / "run_metadata.json", metadata)
    _write_json(run_dir / "resolved_suite.json", suite)
    scenario_inputs_dir = run_dir / "scenario_inputs"
    scenario_inputs_dir.mkdir(parents=True, exist_ok=True)
    for path in scenario_paths:
        shutil.copy2(path, scenario_inputs_dir / path.name)
    if len(scenario_paths) == 1:
        shutil.copy2(scenario_paths[0], run_dir / "suite.toml")
    _write_json(run_dir / "inventory.json", _discover_rust_components(REPO_ROOT))
    if runtime:
        _emit_progress(f"detected container runtime {runtime.engine} via {' '.join(runtime.compose_cmd)}")
    if metadata.get("warnings"):
        _emit_progress(f"preflight completed with {len(metadata['warnings'])} warning(s)")
    else:
        _emit_progress("preflight completed without warnings")
    if check_runtime_only:
        _emit_progress(f"runtime check complete: {run_dir}")
        return run_dir

    scenario_summaries: list[dict[str, Any]] = []
    continue_on_failure = bool(suite["suite"].get("continue_on_failure", False))
    flamegraph_enabled = bool(suite["suite"].get("flamegraph_enabled", True))
    for scenario in suite["scenarios"]:
        scenario_dir = run_dir / "scenarios" / scenario["name"]
        scenario_dir.mkdir(parents=True, exist_ok=True)
        _emit_progress(
            f"scenario {scenario['name']}: runtime={scenario.get('runtime', {}).get('http_server', 'unknown')} "
            f"target={scenario.get('load', {}).get('target_service', 'nginx')} "
            f"users={scenario.get('load', {}).get('users', 'n/a')} "
            f"run_time={scenario.get('load', {}).get('run_time', 'n/a')}"
        )
        summary = {
            "scenario": scenario["name"],
            "description": scenario.get("description", ""),
            "scenario_type": scenario.get("scenario_type", ""),
            **_scenario_setup_for_summary(scenario),
            "inventory": {},
            "status": "validated" if validate_only else "pending",
        }
        try:
            source = _ensure_scenario_source(scenario)
            summary["inventory"] = _discover_rust_components(source.repo_root)
            summary["source"] = {
                "repo_root": str(source.repo_root),
                "commit": source.commit,
                "ref_label": source.ref_label,
                "content_fingerprint": source.content_fingerprint,
            }
            _render_plugin_config_for_scenario(scenario, scenario_dir / "plugins.yaml", validate_only=validate_only)
            _write_json(scenario_dir / "resolved_config.json", _json_safe(scenario))

            if validate_only:
                _emit_progress(f"scenario {scenario['name']}: validated only, skipping execution")
                summary.update(
                    {
                        "endpoint_metrics": {"status": "omitted", "reason": "Validation mode"},
                        "plugin_timing": {"status": "omitted", "reason": "Validation mode"},
                        "pyspy": {"status": "omitted", "reason": "Validation mode"},
                        "memray": {"status": "omitted", "reason": "Validation mode"},
                        "process_stats": {"status": "omitted", "reason": "Validation mode"},
                        "flamegraph_run": {"status": "omitted", "reason": "Validation mode"},
                        "database_metrics": {"status": "omitted", "reason": "Validation mode"},
                        "system_metrics": {"status": "omitted", "reason": "Validation mode"},
                    }
                )
            else:
                execution = scenario.get("execution", {})
                retry_enabled = bool(execution.get("retry_enabled", False))
                max_attempts = max(1, int(execution.get("max_attempts", 1) or 1))
                capture_logs = bool(execution.get("capture_logs", True))
                attempt_results = []
                for attempt in range(1, max_attempts + 1):
                    if runtime is None:
                        raise RuntimeError("Benchmark runtime is required for execution")
                    _emit_progress(f"scenario {scenario['name']}: attempt {attempt} of {max_attempts}")
                    result = _execute_single_attempt(runtime, scenario, scenario_dir, flamegraph_enabled, capture_logs, attempt)
                    result["attempt"] = attempt
                    attempt_results.append(result)
                    _emit_progress(f"scenario {scenario['name']}: attempt {attempt} finished with status={result['status']}")
                    if result["status"] == "ok" or not retry_enabled or attempt == max_attempts:
                        break
                    _emit_progress(f"scenario {scenario['name']}: retrying after failed attempt {attempt}")
                final_attempt = attempt_results[-1]
                summary.update(final_attempt)
                summary["attempts"] = attempt_results
        except Exception as exc:  # pylint: disable=broad-except
            summary["status"] = "failed"
            summary["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
            summary.update(_unavailable_sections(str(exc)))
            _emit_progress(f"scenario {scenario['name']}: failed with {exc.__class__.__name__}: {exc}")

        _write_json(scenario_dir / "summary.json", summary)
        _write_markdown(scenario_dir / "summary.md", _scenario_markdown(summary))
        scenario_summaries.append(summary)
        _emit_progress(f"scenario {scenario['name']}: completed with status={summary['status']}")
        if not validate_only and summary["status"] != "ok" and not continue_on_failure:
            _emit_progress("stopping suite after the first failed scenario because continue_on_failure=false")
            break

    suite_summary = {"suite": suite["suite"], "scenario_order": [scenario["name"] for scenario in suite["scenarios"]], "scenario_count": len(scenario_summaries)}
    _write_comparisons(run_dir, scenario_summaries, suite_summary=suite_summary)
    run_summary = _build_run_summary(run_dir, scenario_summaries, metadata=metadata)
    _write_json(run_dir / "run_summary.json", run_summary)
    _write_markdown(run_dir / "run_summary.md", _run_summary_markdown(run_summary))
    baseline_run = suite["suite"].get("baseline_run")
    if baseline_run:
        baseline_payload = _compare_against_baseline(run_summary, _load_baseline_run(Path(str(baseline_run))), suite["suite"])
        _write_json(run_dir / "baseline_comparison.json", baseline_payload)
        _write_markdown(run_dir / "baseline_comparison.md", _baseline_markdown(baseline_payload))
    _write_json(run_dir / "suite_summary.json", suite_summary)
    _write_markdown(run_dir / "suite_summary.md", "# Suite Summary\n\nPrimary entrypoint: `scenario_comparison_report.html`\n\n" + "\n".join(f"- `{summary['scenario']}`" for summary in scenario_summaries))
    _emit_progress(f"wrote unified report to {run_dir / 'scenario_comparison_report.html'}")
    _emit_progress(f"wrote run summary to {run_dir / 'run_summary.json'}")
    if run_dir != requested_run_dir:
        requested_run_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, requested_run_dir, dirs_exist_ok=True)
        _emit_progress(f"copied final artifacts to {requested_run_dir}")
        return requested_run_dir
    return run_dir


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sequential benchmark suite runner")
    parser.add_argument("--scenario", help="Benchmark scenario name or path")
    parser.add_argument("--all", action="store_true", help="Run every benchmark scenario in the bundle")
    parser.add_argument("--validate", action="store_true", help="Validate only; do not execute scenarios")
    parser.add_argument("--smoke", action="store_true", help="Reduce scenario intensity for smoke runs")
    parser.add_argument("--output-root", help="Output root directory")
    parser.add_argument("--report-run", help="Existing run directory to re-render scenario and suite reports")
    parser.add_argument("--compare-run", help="Existing run directory to re-render comparison outputs")
    parser.add_argument("--list", action="store_true", help="List available benchmark scenarios")
    parser.add_argument("--check-runtime", action="store_true", help="Validate benchmark runtime prerequisites and write run metadata")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.list:
        print("\n".join(list_scenarios()))
        return 0
    if args.report_run:
        run_dir = regenerate_reports(Path(args.report_run))
    elif args.compare_run:
        run_dir = regenerate_reports(Path(args.compare_run))
    else:
        if not args.all and not args.scenario:
            raise SystemExit("Provide --scenario <name-or-path> or --all")
        output_root = Path(args.output_root) if args.output_root else None
        run_dir = execute_suite(str(args.scenario or "all-scenarios"), validate_only=args.validate, smoke=args.smoke, output_root=output_root, check_runtime_only=args.check_runtime, run_all=bool(args.all))
    try:
        print(run_dir)
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
