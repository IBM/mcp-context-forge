# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/code_execution_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Secure code execution with a virtual tool filesystem.

This module powers code_execution virtual servers and their two meta-tools:
- shell_exec: run sandboxed code/commands
- fs_browse: lightweight virtual filesystem browsing
"""

# Standard
from __future__ import annotations

import abc
import asyncio
from collections import defaultdict, deque
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import sys
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING
import uuid

# Third-Party
import jq
from sqlalchemy import select
from sqlalchemy.orm import joinedload, Session

try:
    # Third-Party
    from plugins_rust import catalog_builder as rust_catalog_builder
    from plugins_rust import fs_search as rust_fs_search
    from plugins_rust import json_schema_to_stubs as rust_json_schema_to_stubs

    _RUST_CODE_EXEC_AVAILABLE = True
except ImportError:
    rust_catalog_builder = None
    rust_fs_search = None
    rust_json_schema_to_stubs = None
    _RUST_CODE_EXEC_AVAILABLE = False

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import CodeExecutionRun, CodeExecutionSkill, Server as DbServer, SkillApproval
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import utc_now
from mcpgateway.observability import create_span
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.security_logger import SecurityLogger, SecuritySeverity
from mcpgateway.utils.create_slug import slugify

if TYPE_CHECKING:
    # First-Party
    from mcpgateway.common.models import ToolResult


logger = LoggingService().get_logger(__name__)
security_logger = SecurityLogger()

CODE_EXECUTION_SERVER_TYPE = "code_execution"
META_TOOL_SHELL_EXEC = "shell_exec"
META_TOOL_FS_BROWSE = "fs_browse"
CODE_EXECUTION_META_TOOLS = (META_TOOL_SHELL_EXEC, META_TOOL_FS_BROWSE)
VFS_SCHEMA_VERSION = "2026-02-01"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_PYTHON_DANGEROUS_PATTERNS = (
    r"(?i)\beval\s*\(",
    r"(?i)\bexec\s*\(",
    r"(?i)__import__\s*\(",
    r"(?i)\bos\.system\s*\(",
    r"(?i)\bsubprocess\.",
    r"(?i)\bopen\s*\(\s*['\"]/(etc|proc|sys)",
)
_TS_DANGEROUS_PATTERNS = (
    r"(?i)\beval\s*\(",
    r"(?i)\bDeno\.run\b",
    r"(?i)\bDeno\.Command\b",
    r"(?i)\bfetch\s*\(",
    r"(?i)from\s+['\"]https?://",
    r"(?i)import\s*\(\s*['\"]https?://",
)

_DEFAULT_FS_READ = ("/tools/**", "/skills/**", "/scratch/**", "/results/**")
_DEFAULT_FS_WRITE = ("/scratch/**", "/results/**")
_DEFAULT_FS_DENY = ("/etc/**", "/proc/**", "/sys/**")
_DEFAULT_TOKENIZATION_TYPES = ("email", "phone", "ssn", "credit_card", "name")


def _coerce_string_list(value: Any, fallback: Sequence[str]) -> List[str]:
    """Normalize a setting/environment value into a list of non-empty strings."""
    if not isinstance(value, list):
        return list(fallback)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned


# Safe subset only. No eval/exec/open/import.
_SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


class CodeExecutionError(Exception):
    """Base class for code execution errors."""


class CodeExecutionSecurityError(CodeExecutionError):
    """Raised when code violates policy."""


class CodeExecutionRateLimitError(CodeExecutionError):
    """Raised when execution is rate limited."""


@dataclass
class SandboxExecutionResult:
    """Runtime execution result."""

    stdout: str
    stderr: str
    exit_code: int
    wall_time_ms: int


@dataclass
class ToolCallRecord:
    """Single tool bridge invocation trace."""

    name: str
    started_at: datetime
    latency_ms: int
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class TokenizationContext:
    """Session-scoped bidirectional token map."""

    enabled: bool = False
    token_types: Sequence[str] = field(default_factory=tuple)
    value_to_token: Dict[str, str] = field(default_factory=dict)
    token_to_value: Dict[str, str] = field(default_factory=dict)

    def _next_token(self, category: str) -> str:
        prefix = category.upper().replace("-", "_")
        idx = len(self.value_to_token) + 1
        return f"TKN_{prefix}_{idx:06d}"

    def _tokenize_exact(self, raw: str, category: str) -> str:
        token = self.value_to_token.get(raw)
        if token is None:
            token = self._next_token(category)
            self.value_to_token[raw] = token
            self.token_to_value[token] = raw
        return token

    def _replace_with_tokens(self, text: str) -> str:
        if not self.enabled or not text:
            return text

        replaced = text
        patterns: List[Tuple[str, re.Pattern[str]]] = []
        if "email" in self.token_types:
            patterns.append(("EMAIL", _EMAIL_RE))
        if "phone" in self.token_types:
            patterns.append(("PHONE", _PHONE_RE))
        if "ssn" in self.token_types:
            patterns.append(("SSN", _SSN_RE))
        if "credit_card" in self.token_types:
            patterns.append(("CREDIT_CARD", _CC_RE))

        for category, pattern in patterns:
            def repl(match: re.Match[str]) -> str:
                raw = match.group(0)
                return self._tokenize_exact(raw, category)

            replaced = pattern.sub(repl, replaced)
        return replaced

    def _is_name_key(self, key: str) -> bool:
        lowered = key.lower()
        return lowered == "name" or lowered.endswith("_name") or lowered.endswith("name")

    def tokenize_obj(self, value: Any) -> Any:
        """Tokenize recursive data structure."""
        if isinstance(value, str):
            return self._replace_with_tokens(value)
        if isinstance(value, list):
            return [self.tokenize_obj(v) for v in value]
        if isinstance(value, dict):
            tokenize_names = "name" in self.token_types
            out: Dict[str, Any] = {}
            for k, v in value.items():
                key_str = str(k)
                if tokenize_names and isinstance(v, str) and self._is_name_key(key_str):
                    out[k] = self._tokenize_exact(v, "NAME")
                else:
                    out[k] = self.tokenize_obj(v)
            return out
        return value

    def detokenize_obj(self, value: Any) -> Any:
        """Detokenize recursive data structure."""
        if not self.enabled:
            return value
        if isinstance(value, str):
            result = value
            for token, raw in self.token_to_value.items():
                result = result.replace(token, raw)
            return result
        if isinstance(value, list):
            return [self.detokenize_obj(v) for v in value]
        if isinstance(value, dict):
            return {k: self.detokenize_obj(v) for k, v in value.items()}
        return value


@dataclass
class CodeExecutionSession:
    """In-memory code execution session."""

    session_id: str
    server_id: str
    user_email: str
    language: str
    root_dir: Path
    created_at: datetime
    last_used_at: datetime
    tools_dir: Path
    scratch_dir: Path
    skills_dir: Path
    results_dir: Path
    mounted_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runtime_tool_index: Dict[Tuple[str, str], str] = field(default_factory=dict)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    tokenization: TokenizationContext = field(default_factory=TokenizationContext)
    generated_at: Optional[datetime] = None
    content_hash: Optional[str] = None

    @property
    def all_dirs(self) -> Tuple[Path, Path, Path, Path]:
        """Return primary virtual directories."""
        return (self.tools_dir, self.scratch_dir, self.skills_dir, self.results_dir)


class SandboxRuntime(abc.ABC):
    """Runtime contract for pluggable sandboxes."""

    @abc.abstractmethod
    async def create_session(self, session: CodeExecutionSession, policy: Dict[str, Any]) -> None:
        """Prepare runtime state for a new session."""

    @abc.abstractmethod
    async def execute(
        self,
        session: CodeExecutionSession,
        code: str,
        timeout_ms: int,
        policy: Dict[str, Any],
        tool_handler: Callable[[str, str, Dict[str, Any]], Awaitable[Any]],
    ) -> SandboxExecutionResult:
        """Execute code and return structured process result."""

    @abc.abstractmethod
    async def destroy_session(self, session: CodeExecutionSession) -> None:
        """Cleanup any runtime resources."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if runtime is available."""


class DenoRuntime(SandboxRuntime):
    """Deno-based runtime with explicit permission flags."""

    def __init__(self) -> None:
        """Locate the Deno executable used for sandbox runs."""
        self._deno_path = shutil.which("deno")

    async def create_session(self, session: CodeExecutionSession, policy: Dict[str, Any]) -> None:  # noqa: ARG002
        """Prepare runtime state for a session (no-op for subprocess-per-run model)."""
        return None

    async def execute(
        self,
        session: CodeExecutionSession,
        code: str,
        timeout_ms: int,
        policy: Dict[str, Any],
        tool_handler: Callable[[str, str, Dict[str, Any]], Awaitable[Any]],
    ) -> SandboxExecutionResult:
        """Execute TypeScript in Deno with the stdio tool bridge."""
        if not self._deno_path:
            raise CodeExecutionError("Deno runtime is not available on this host")

        started = time.perf_counter()
        secret = uuid.uuid4().hex
        script_path = session.scratch_dir / f"codeexec_{uuid.uuid4().hex}.ts"

        wrapped_lines = ["async function __user_main__() {"]
        for line in code.splitlines() or [""]:
            wrapped_lines.append(f"  {line}")
        wrapped_lines.append("}")

        runner = (
            "// Auto-generated by MCP Gateway code execution mode. Do not edit.\n"
            f"const __CODEEXEC_SECRET = {json.dumps(secret)};\n"
            "const __encoder = new TextEncoder();\n"
            "async function __send(msg: any) {\n"
            "  const line = JSON.stringify(msg) + \"\\n\";\n"
            "  await Deno.stdout.write(__encoder.encode(line));\n"
            "}\n"
            "async function* __readLines() {\n"
            "  const decoder = new TextDecoder();\n"
            "  let buf = \"\";\n"
            "  for await (const chunk of Deno.stdin.readable) {\n"
            "    buf += decoder.decode(chunk);\n"
            "    while (true) {\n"
            "      const idx = buf.indexOf(\"\\n\");\n"
            "      if (idx < 0) break;\n"
            "      const line = buf.slice(0, idx);\n"
            "      buf = buf.slice(idx + 1);\n"
            "      yield line;\n"
            "    }\n"
            "  }\n"
            "  if (buf.length) yield buf;\n"
            "}\n"
            "type Pending = { resolve: (v: any) => void; reject: (e: any) => void };\n"
            "const __pending = new Map<string, Pending>();\n"
            "(async () => {\n"
            "  for await (const line of __readLines()) {\n"
            "    const trimmed = line.trim();\n"
            "    if (!trimmed) continue;\n"
            "    let msg: any;\n"
            "    try { msg = JSON.parse(trimmed); } catch { continue; }\n"
            "    if (msg.secret !== __CODEEXEC_SECRET) continue;\n"
            "    if (msg.type !== \"toolcall_response\") continue;\n"
            "    const entry = __pending.get(msg.id);\n"
            "    if (!entry) continue;\n"
            "    __pending.delete(msg.id);\n"
            "    if (msg.ok) entry.resolve(msg.result);\n"
            "    else entry.reject(new Error(String(msg.error ?? \"toolcall failed\")));\n"
            "  }\n"
            "})();\n"
            "async function __toolcall__(a: string, b: any, c?: any): Promise<any> {\n"
            "  let server = \"\";\n"
            "  let tool = \"\";\n"
            "  let args: Record<string, any> = {};\n"
            "  if (c === undefined && typeof b === \"object\") {\n"
            "    tool = String(a);\n"
            "    args = (b ?? {}) as Record<string, any>;\n"
            "  } else {\n"
            "    server = String(a);\n"
            "    tool = String(b);\n"
            "    args = (c ?? {}) as Record<string, any>;\n"
            "  }\n"
            "  const id = crypto.randomUUID();\n"
            "  const p = new Promise((resolve, reject) => { __pending.set(id, { resolve, reject }); });\n"
            "  await __send({ secret: __CODEEXEC_SECRET, type: \"toolcall\", id, server, tool, args });\n"
            "  return await p;\n"
            "}\n"
            "(globalThis as any).__toolcall__ = __toolcall__;\n"
            "function __makeToolProxy(server: string) {\n"
            "  return new Proxy({}, {\n"
            "    get(_t: any, prop: string | symbol) {\n"
            "      if (typeof prop === \"symbol\") return undefined;\n"
            "      const tool = String(prop);\n"
            "      return async (args: Record<string, any> = {}) => __toolcall__(server, tool, args);\n"
            "    }\n"
            "  });\n"
            "}\n"
            "const tools = new Proxy({}, {\n"
            "  get(_t: any, prop: string | symbol) {\n"
            "    if (typeof prop === \"symbol\") return undefined;\n"
            "    const server = String(prop);\n"
            "    return __makeToolProxy(server);\n"
            "  }\n"
            "});\n"
            "(globalThis as any).tools = tools;\n"
            "const __out: string[] = [];\n"
            "const __err: string[] = [];\n"
            "console.log = (...args: unknown[]) => { __out.push(args.map(String).join(\" \")); };\n"
            "console.error = (...args: unknown[]) => { __err.push(args.map(String).join(\" \")); };\n"
            + "\n".join(wrapped_lines)
            + "\n"
            "(async () => {\n"
            "  let exitCode = 0;\n"
            "  try {\n"
            "    const result = await __user_main__();\n"
            "    if (result !== undefined) __out.push(JSON.stringify(result));\n"
            "  } catch (e) {\n"
            "    exitCode = 1;\n"
            "    if (e instanceof Error) __err.push(String(e.stack ?? e.message));\n"
            "    else __err.push(String(e));\n"
            "  }\n"
            "  const outStr = __out.join(\"\\n\");\n"
            "  const errStr = __err.join(\"\\n\");\n"
            "  await __send({ secret: __CODEEXEC_SECRET, type: \"result\", output: outStr, error: errStr || null, exit_code: exitCode });\n"
            "  Deno.exit(exitCode);\n"
            "})();\n"
        )
        script_path.write_text(runner, encoding="utf-8")

        import_map_path = session.scratch_dir / "import_map.json"
        imports = {
            "/tools/": session.tools_dir.resolve().as_uri() + "/",
            "/skills/": session.skills_dir.resolve().as_uri() + "/",
        }
        import_map_path.write_text(json.dumps({"imports": imports}, indent=2), encoding="utf-8")

        allow_read = ",".join(str(p) for p in session.all_dirs)
        allow_write = ",".join(str(p) for p in (session.scratch_dir, session.results_dir))
        cmd = [
            self._deno_path,
            "run",
            "--quiet",
            "--no-remote",
            f"--import-map={import_map_path}",
            f"--allow-read={allow_read}",
            f"--allow-write={allow_write}",
        ]
        if bool(policy.get("allow_raw_http", False)):
            cmd.append("--allow-net")

        max_memory_mb = int(policy.get("max_memory_mb", 256))
        cmd.append(f"--v8-flags=--max-old-space-size={max_memory_mb}")
        cmd.append(str(script_path))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(session.root_dir),
        )
        if not proc.stdout or not proc.stdin or not proc.stderr:
            raise CodeExecutionError("Failed to start Deno sandbox process")

        write_lock = asyncio.Lock()
        tool_tasks: set[asyncio.Task[None]] = set()
        result_output: str = ""
        result_error: str = ""
        result_exit: int = 1

        async def _send_response(payload: Dict[str, Any]) -> None:
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            async with write_lock:
                proc.stdin.write(line.encode("utf-8"))
                await proc.stdin.drain()

        async def _handle_toolcall(msg: Dict[str, Any]) -> None:
            tool_id = str(msg.get("id") or "")
            server = str(msg.get("server") or "")
            tool = str(msg.get("tool") or "")
            args = msg.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            try:
                result = await tool_handler(server, tool, args)
                await _send_response({"secret": secret, "type": "toolcall_response", "id": tool_id, "ok": True, "result": result})
            except Exception as exc:  # pragma: no cover - defensive
                await _send_response({"secret": secret, "type": "toolcall_response", "id": tool_id, "ok": False, "error": str(exc)})

        async def _pump_stdout() -> None:
            nonlocal result_output, result_error, result_exit
            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("secret") != secret:
                    continue
                if msg.get("type") == "toolcall":
                    task = asyncio.create_task(_handle_toolcall(msg))
                    tool_tasks.add(task)
                    task.add_done_callback(lambda t: tool_tasks.discard(t))
                    continue
                if msg.get("type") == "result":
                    result_output = str(msg.get("output") or "")
                    err_val = msg.get("error")
                    result_error = str(err_val) if err_val else ""
                    result_exit = int(msg.get("exit_code") or 0)
                    break

        try:
            await asyncio.wait_for(_pump_stdout(), timeout=timeout_ms / 1000)
            if tool_tasks:
                await asyncio.gather(*tool_tasks, return_exceptions=True)
            await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000)
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise CodeExecutionError(f"Execution timed out after {timeout_ms}ms") from exc

        stderr_extra = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
        if stderr_extra and not result_error:
            result_error = stderr_extra
        elif stderr_extra and result_error and stderr_extra not in result_error:
            result_error = f"{result_error}\n{stderr_extra}"

        wall = int((time.perf_counter() - started) * 1000)
        return SandboxExecutionResult(stdout=result_output, stderr=result_error, exit_code=result_exit, wall_time_ms=wall)

    async def destroy_session(self, session: CodeExecutionSession) -> None:  # noqa: ARG002
        """Cleanup runtime session state (no-op for subprocess-per-run model)."""
        return None

    async def health_check(self) -> bool:
        """Return whether Deno is installed and runnable."""
        return self._deno_path is not None


class PythonSandboxRuntime(SandboxRuntime):
    """Python runtime fallback when Deno is unavailable or python is requested."""

    def __init__(self) -> None:
        """Locate the Python executable used for sandbox runs."""
        self._python_path = sys.executable or shutil.which("python3") or shutil.which("python")

    async def create_session(self, session: CodeExecutionSession, policy: Dict[str, Any]) -> None:  # noqa: ARG002
        """Prepare runtime state for a session (no-op for subprocess-per-run model)."""
        return None

    async def execute(
        self,
        session: CodeExecutionSession,
        code: str,
        timeout_ms: int,
        policy: Dict[str, Any],
        tool_handler: Callable[[str, str, Dict[str, Any]], Awaitable[Any]],
    ) -> SandboxExecutionResult:
        """Execute Python code with a restricted builtin/import environment."""
        if not self._python_path:
            raise CodeExecutionError("Python runtime is not available on this host")

        started = time.perf_counter()
        secret = uuid.uuid4().hex
        script_path = session.scratch_dir / f"codeexec_{uuid.uuid4().hex}.py"

        tools_root = str(session.tools_dir.resolve())
        skills_root = str(session.skills_dir.resolve())
        scratch_root = str(session.scratch_dir.resolve())
        results_root = str(session.results_dir.resolve())

        user_lines = ["async def __user_main__():", "    # User code"]
        for line in code.splitlines() or [""]:
            user_lines.append(f"    {line}")

        wrapper = (
            "# Auto-generated by MCP Gateway code execution mode. Do not edit.\n"
            "from __future__ import annotations\n"
            "import asyncio\n"
            "import builtins\n"
            "import contextlib\n"
            "import io\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "import re\n"
            "import sys\n"
            "import traceback\n"
            "import uuid\n"
            "\n"
            f"__CODEEXEC_SECRET = {json.dumps(secret)}\n"
            f"__TOOLS_ROOT = {json.dumps(tools_root)}\n"
            f"__SKILLS_ROOT = {json.dumps(skills_root)}\n"
            f"__SCRATCH_ROOT = {json.dumps(scratch_root)}\n"
            f"__RESULTS_ROOT = {json.dumps(results_root)}\n"
            "\n"
            "sys.path.insert(0, str(Path(__TOOLS_ROOT).parent))\n"
            "\n"
            "SAFE_IMPORTS = {\n"
            "    'asyncio','json','re','math','datetime','time','uuid','collections','itertools','functools','statistics','typing',\n"
            "    'tools','skills',\n"
            "}\n"
            "\n"
            "def __safe_import(name, globals=None, locals=None, fromlist=(), level=0):\n"
            "    base = name.split('.', 1)[0]\n"
            "    if name not in SAFE_IMPORTS and base not in SAFE_IMPORTS:\n"
            "        raise ImportError(f\"Import of '{name}' is not allowed in sandbox\")\n"
            "    return builtins.__import__(name, globals, locals, fromlist, level)\n"
            "\n"
            "_SAFE_BUILTINS = {\n"
            "    'abs': abs, 'all': all, 'any': any, 'bool': bool, 'dict': dict, 'enumerate': enumerate,\n"
            "    'float': float, 'int': int, 'len': len, 'list': list, 'max': max, 'min': min, 'print': print,\n"
            "    'range': range, 'set': set, 'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple, 'zip': zip,\n"
            "    'Exception': Exception, 'ValueError': ValueError, 'TypeError': TypeError,\n"
            "    '__import__': __safe_import,\n"
            "}\n"
            "\n"
            "def __virtual_to_real(path: str) -> Path:\n"
            "    raw = (path or '').strip()\n"
            "    if not raw:\n"
            "        raise PermissionError('EACCES: invalid path')\n"
            "    if not raw.startswith('/'):\n"
            "        raw = '/scratch/' + raw\n"
            "    normalized = '/' + raw.strip().lstrip('/')\n"
            "    mapping = {\n"
            "        '/tools': Path(__TOOLS_ROOT),\n"
            "        '/skills': Path(__SKILLS_ROOT),\n"
            "        '/scratch': Path(__SCRATCH_ROOT),\n"
            "        '/results': Path(__RESULTS_ROOT),\n"
            "    }\n"
            "    for root, real_root in mapping.items():\n"
            "        if normalized == root or normalized.startswith(root + '/'):\n"
            "            suffix = normalized[len(root):].lstrip('/')\n"
            "            resolved = (real_root / suffix).resolve()\n"
            "            if str(resolved).startswith(str(real_root.resolve())):\n"
            "                return resolved\n"
            "    raise PermissionError(f'EACCES: path denied: {normalized}')\n"
            "\n"
            "def read_file(path: str) -> str:\n"
            "    p = __virtual_to_real(path)\n"
            "    if not p.exists() or not p.is_file():\n"
            "        raise PermissionError(f'EACCES: read denied for path: {path}')\n"
            "    return p.read_text(encoding='utf-8')\n"
            "\n"
            "def write_file(path: str, content: str) -> None:\n"
            "    p = __virtual_to_real(path)\n"
            "    if not (str(p).startswith(str(Path(__SCRATCH_ROOT).resolve())) or str(p).startswith(str(Path(__RESULTS_ROOT).resolve()))):\n"
            "        raise PermissionError(f'EACCES: write denied for path: {path}')\n"
            "    p.parent.mkdir(parents=True, exist_ok=True)\n"
            "    p.write_text(content, encoding='utf-8')\n"
            "\n"
            "def list_dir(path: str = '/scratch') -> list[str]:\n"
            "    p = __virtual_to_real(path)\n"
            "    if not p.exists() or not p.is_dir():\n"
            "        raise PermissionError(f'EACCES: read denied for path: {path}')\n"
            "    return sorted([c.name for c in p.iterdir()])\n"
            "\n"
            "class _ToolGroup:\n"
            "    def __init__(self, server: str) -> None:\n"
            "        self._server = server\n"
            "    def __getattr__(self, item: str):\n"
            "        async def _invoke(args=None):\n"
            "            return await __toolcall__(self._server, item, args or {})\n"
            "        return _invoke\n"
            "\n"
            "class _Tools:\n"
            "    def __getattr__(self, item: str):\n"
            "        return _ToolGroup(item)\n"
            "\n"
            "tools = _Tools()\n"
            "\n"
            "PENDING: dict[str, asyncio.Future] = {}\n"
            "\n"
            "async def __pump_responses() -> None:\n"
            "    while True:\n"
            "        line = await asyncio.to_thread(sys.stdin.readline)\n"
            "        if not line:\n"
            "            return\n"
            "        line = line.strip()\n"
            "        if not line:\n"
            "            continue\n"
            "        try:\n"
            "            msg = json.loads(line)\n"
            "        except Exception:\n"
            "            continue\n"
            "        if msg.get('secret') != __CODEEXEC_SECRET:\n"
            "            continue\n"
            "        if msg.get('type') != 'toolcall_response':\n"
            "            continue\n"
            "        req_id = str(msg.get('id') or '')\n"
            "        fut = PENDING.pop(req_id, None)\n"
            "        if fut is None:\n"
            "            continue\n"
            "        if msg.get('ok'):\n"
            "            fut.set_result(msg.get('result'))\n"
            "        else:\n"
            "            fut.set_exception(RuntimeError(str(msg.get('error') or 'toolcall failed')))\n"
            "\n"
            "async def __toolcall__(a: str, b, c=None):\n"
            "    server = ''\n"
            "    tool = ''\n"
            "    args = {}\n"
            "    if c is None and isinstance(b, dict):\n"
            "        tool = str(a)\n"
            "        args = b\n"
            "    else:\n"
            "        server = str(a)\n"
            "        tool = str(b)\n"
            "        args = c or {}\n"
            "    req_id = uuid.uuid4().hex\n"
            "    loop = asyncio.get_running_loop()\n"
            "    fut = loop.create_future()\n"
            "    PENDING[req_id] = fut\n"
            "    req = {'secret': __CODEEXEC_SECRET, 'type': 'toolcall', 'id': req_id, 'server': server, 'tool': tool, 'args': args}\n"
            "    sys.__stdout__.write(json.dumps(req, ensure_ascii=False) + '\\n')\n"
            "    sys.__stdout__.flush()\n"
            "    return await fut\n"
            "\n"
            + "\n".join(user_lines)
            + "\n\n"
            "async def __main() -> int:\n"
            "    stdout_capture = io.StringIO()\n"
            "    stderr_capture = io.StringIO()\n"
            "    orig_stdout, orig_stderr = sys.stdout, sys.stderr\n"
            "    sys.stdout, sys.stderr = stdout_capture, stderr_capture\n"
            "    exit_code = 0\n"
            "    result_value = None\n"
            "    try:\n"
            "        globals_dict = {\n"
            "            '__builtins__': _SAFE_BUILTINS,\n"
            "            '__toolcall__': __toolcall__,\n"
            "            'tools': tools,\n"
            "            'json': json,\n"
            "            'read_file': read_file,\n"
            "            'write_file': write_file,\n"
            "            'list_dir': list_dir,\n"
            "        }\n"
            "        exec('\\n'.join(__CODE__.splitlines()), globals_dict)\n"
            "    except Exception:\n"
            "        pass\n"
            "    finally:\n"
            "        pass\n"
            "\n"
            "    sys.stdout, sys.stderr = orig_stdout, orig_stderr\n"
            "    return exit_code\n"
            "\n"
            "# Execute user code in a restricted globals dict\n"
            "__CODE__ = " + json.dumps("\n".join(user_lines)) + "\n"
            "\n"
            "async def __run_user() -> tuple[str, str, int]:\n"
            "    pump_task = asyncio.create_task(__pump_responses())\n"
            "    stdout_capture = io.StringIO()\n"
            "    stderr_capture = io.StringIO()\n"
            "    orig_stdout, orig_stderr = sys.stdout, sys.stderr\n"
            "    sys.stdout, sys.stderr = stdout_capture, stderr_capture\n"
            "    exit_code = 0\n"
            "    try:\n"
            "        globals_dict = {\n"
            "            '__builtins__': _SAFE_BUILTINS,\n"
            "            '__toolcall__': __toolcall__,\n"
            "            'tools': tools,\n"
            "            'json': json,\n"
            "            'read_file': read_file,\n"
            "            'write_file': write_file,\n"
            "            'list_dir': list_dir,\n"
            "        }\n"
            "        exec(__CODE__, globals_dict)\n"
            "        fn = globals_dict.get('__user_main__')\n"
            "        if fn is None:\n"
            "            raise RuntimeError('user main not defined')\n"
            "        result = await fn()\n"
            "        if result is not None:\n"
            "            print(json.dumps(result, ensure_ascii=False, default=str))\n"
            "    except Exception as e:\n"
            "        exit_code = 1\n"
            "        traceback.print_exc(file=sys.stderr)\n"
            "    finally:\n"
            "        sys.stdout, sys.stderr = orig_stdout, orig_stderr\n"
            "        pump_task.cancel()\n"
            "        with contextlib.suppress(Exception):\n"
            "            await pump_task\n"
            "    return stdout_capture.getvalue(), stderr_capture.getvalue(), exit_code\n"
            "\n"
            "def __send_result(out: str, err: str, exit_code: int) -> None:\n"
            "    payload = {'secret': __CODEEXEC_SECRET, 'type': 'result', 'output': out, 'error': err or None, 'exit_code': exit_code}\n"
            "    sys.__stdout__.write(json.dumps(payload, ensure_ascii=False) + '\\n')\n"
            "    sys.__stdout__.flush()\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    out, err, code = asyncio.run(__run_user())\n"
            "    __send_result(out, err, code)\n"
            "    raise SystemExit(code)\n"
        )

        script_path.write_text(wrapper, encoding="utf-8")
        cmd = [self._python_path, "-I", "-S", str(script_path)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(session.root_dir),
        )
        if not proc.stdout or not proc.stdin or not proc.stderr:
            raise CodeExecutionError("Failed to start Python sandbox process")

        write_lock = asyncio.Lock()
        tool_tasks: set[asyncio.Task[None]] = set()
        result_output: str = ""
        result_error: str = ""
        result_exit: int = 1

        async def _send_response(payload: Dict[str, Any]) -> None:
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            async with write_lock:
                proc.stdin.write(line.encode("utf-8"))
                await proc.stdin.drain()

        async def _handle_toolcall(msg: Dict[str, Any]) -> None:
            tool_id = str(msg.get("id") or "")
            server = str(msg.get("server") or "")
            tool = str(msg.get("tool") or "")
            args = msg.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            try:
                result = await tool_handler(server, tool, args)
                await _send_response({"secret": secret, "type": "toolcall_response", "id": tool_id, "ok": True, "result": result})
            except Exception as exc:  # pragma: no cover - defensive
                await _send_response({"secret": secret, "type": "toolcall_response", "id": tool_id, "ok": False, "error": str(exc)})

        async def _pump_stdout() -> None:
            nonlocal result_output, result_error, result_exit
            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("secret") != secret:
                    continue
                if msg.get("type") == "toolcall":
                    task = asyncio.create_task(_handle_toolcall(msg))
                    tool_tasks.add(task)
                    task.add_done_callback(lambda t: tool_tasks.discard(t))
                    continue
                if msg.get("type") == "result":
                    result_output = str(msg.get("output") or "")
                    err_val = msg.get("error")
                    result_error = str(err_val) if err_val else ""
                    result_exit = int(msg.get("exit_code") or 0)
                    break

        try:
            await asyncio.wait_for(_pump_stdout(), timeout=timeout_ms / 1000)
            if tool_tasks:
                await asyncio.gather(*tool_tasks, return_exceptions=True)
            await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000)
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise CodeExecutionError(f"Execution timed out after {timeout_ms}ms") from exc

        stderr_extra = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
        if stderr_extra and not result_error:
            result_error = stderr_extra
        elif stderr_extra and result_error and stderr_extra not in result_error:
            result_error = f"{result_error}\n{stderr_extra}"

        wall = int((time.perf_counter() - started) * 1000)
        return SandboxExecutionResult(stdout=result_output, stderr=result_error, exit_code=result_exit, wall_time_ms=wall)

    async def destroy_session(self, session: CodeExecutionSession) -> None:  # noqa: ARG002
        """Cleanup runtime session state (no-op for subprocess-per-run model)."""
        return None

    async def health_check(self) -> bool:
        """Return whether Python is available for sandbox execution."""
        return self._python_path is not None


ToolInvokeCallback = Callable[[str, Dict[str, Any]], Awaitable["ToolResult"]]


class CodeExecutionService:
    """Service implementing virtual filesystem + secure code execution."""

    def __init__(self) -> None:
        """Initialize in-memory caches and available sandbox runtimes."""
        self._sessions: Dict[Tuple[str, str, str], CodeExecutionSession] = {}
        self._rate_windows: Dict[Tuple[str, str], deque[float]] = defaultdict(deque)
        self._session_rate_windows: Dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._base_dir = Path(getattr(settings, "code_execution_base_dir", "/tmp/mcpgateway_code_execution"))
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._default_ttl = int(getattr(settings, "code_execution_session_ttl_seconds", 900))
        self._shell_exec_enabled = bool(getattr(settings, "code_execution_shell_exec_enabled", True))
        self._fs_browse_enabled = bool(getattr(settings, "code_execution_fs_browse_enabled", True))
        self._replay_enabled = bool(getattr(settings, "code_execution_replay_enabled", True))
        self._rust_acceleration_enabled = bool(getattr(settings, "code_execution_rust_acceleration_enabled", True))
        self._python_inprocess_fallback_enabled = bool(getattr(settings, "code_execution_python_inprocess_fallback_enabled", True))

        default_runtime = str(getattr(settings, "code_execution_default_runtime", "deno") or "deno").strip().lower()
        self._default_runtime = default_runtime if default_runtime in {"deno", "python"} else "deno"
        self._default_allow_tool_calls = bool(getattr(settings, "code_execution_default_allow_tool_calls", True))
        self._default_allow_raw_http = bool(getattr(settings, "code_execution_default_allow_raw_http", False))

        fs_read_default = _coerce_string_list(getattr(settings, "code_execution_default_filesystem_read_paths", None), _DEFAULT_FS_READ)
        fs_write_default = _coerce_string_list(getattr(settings, "code_execution_default_filesystem_write_paths", None), _DEFAULT_FS_WRITE)
        fs_deny_default = _coerce_string_list(getattr(settings, "code_execution_default_filesystem_deny_paths", None), _DEFAULT_FS_DENY)
        tool_allow_default = _coerce_string_list(getattr(settings, "code_execution_default_tool_allow_patterns", None), ())
        tool_deny_default = _coerce_string_list(getattr(settings, "code_execution_default_tool_deny_patterns", None), ())

        self._sandbox_limit_defaults: Dict[str, int] = {
            "max_execution_time_ms": int(getattr(settings, "code_execution_default_max_execution_time_ms", 30000)),
            "max_memory_mb": int(getattr(settings, "code_execution_default_max_memory_mb", 256)),
            "max_cpu_percent": int(getattr(settings, "code_execution_default_max_cpu_percent", 50)),
            "max_network_connections": int(getattr(settings, "code_execution_default_max_network_connections", 0)),
            "max_file_size_mb": int(getattr(settings, "code_execution_default_max_file_size_mb", 10)),
            "max_total_disk_mb": int(getattr(settings, "code_execution_default_max_total_disk_mb", 100)),
            "max_runs_per_minute": int(getattr(settings, "code_execution_default_max_runs_per_minute", 20)),
            "session_ttl_seconds": self._default_ttl,
        }
        self._sandbox_permissions_defaults: Dict[str, Dict[str, Any]] = {
            "filesystem": {
                "read": fs_read_default,
                "write": fs_write_default,
                "deny": fs_deny_default,
            },
            "tools": {
                "allow": tool_allow_default,
                "deny": tool_deny_default,
            },
            "network": {
                "allow_tool_calls": self._default_allow_tool_calls,
                "allow_raw_http": self._default_allow_raw_http,
            },
        }

        self._tokenization_defaults: Dict[str, Any] = {
            "enabled": bool(getattr(settings, "code_execution_default_tokenization_enabled", False)),
            "types": _coerce_string_list(getattr(settings, "code_execution_default_tokenization_types", None), _DEFAULT_TOKENIZATION_TYPES),
            "strategy": str(getattr(settings, "code_execution_default_tokenization_strategy", "bidirectional") or "bidirectional"),
        }

        python_patterns = _coerce_string_list(getattr(settings, "code_execution_python_dangerous_patterns", None), _PYTHON_DANGEROUS_PATTERNS)
        typescript_patterns = _coerce_string_list(getattr(settings, "code_execution_typescript_dangerous_patterns", None), _TS_DANGEROUS_PATTERNS)
        self._python_dangerous_patterns = tuple(python_patterns)
        self._typescript_dangerous_patterns = tuple(typescript_patterns)

        self._fs_browse_max_entries = max(1, int(getattr(settings, "code_execution_fs_browse_max_entries", 1000)))
        self._fs_browse_default_max_entries = max(
            1,
            min(int(getattr(settings, "code_execution_fs_browse_default_max_entries", 200)), self._fs_browse_max_entries),
        )
        self._max_persisted_output_chars = max(1000, int(getattr(settings, "code_execution_max_persisted_output_chars", 200000)))
        self._deno_runtime = DenoRuntime()
        self._python_runtime = PythonSandboxRuntime()

    async def get_server_or_none(self, db: Session, server_id: str) -> Optional[DbServer]:
        """Return server with code execution config if found."""
        return db.execute(select(DbServer).where(DbServer.id == server_id)).scalar_one_or_none()

    def is_code_execution_server(self, server: Optional[DbServer]) -> bool:
        """Return True if server is code_execution type."""
        if not getattr(settings, "code_execution_enabled", True):
            return False
        return bool(server and getattr(server, "server_type", "standard") == CODE_EXECUTION_SERVER_TYPE)

    def _is_rust_acceleration_available(self) -> bool:
        """Return True when Rust accelerators are both enabled and importable."""
        return bool(self._rust_acceleration_enabled and _RUST_CODE_EXEC_AVAILABLE)

    def build_meta_tools(self, server_id: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Build synthetic tool payloads for shell_exec/fs_browse."""
        ts = now or utc_now()
        base_fields = {
            "url": None,
            "integration_type": "MCP",
            "request_type": "SSE",
            "headers": None,
            "output_schema": None,
            "annotations": {},
            "jsonpath_filter": "",
            "auth": None,
            "created_at": ts,
            "updated_at": ts,
            "enabled": True,
            "reachable": True,
            "gateway_id": None,
            "execution_count": None,
            "metrics": None,
            "gateway_slug": "code-execution",
            "custom_name": "",
            "custom_name_slug": "",
            "tags": [{"name": "code-execution"}],
            "team_id": None,
            "team": None,
            "owner_email": None,
            "visibility": "public",
            "base_url": None,
            "path_template": None,
            "query_mapping": None,
            "header_mapping": None,
            "timeout_ms": 20000,
            "expose_passthrough": False,
            "allowlist": None,
            "plugin_chain_pre": None,
            "plugin_chain_post": None,
            "created_by": "system",
            "created_from_ip": None,
            "created_via": "code_execution",
            "created_user_agent": None,
            "modified_by": None,
            "modified_from_ip": None,
            "modified_via": None,
            "modified_user_agent": None,
            "import_batch_id": None,
            "federation_source": None,
            "version": 1,
            "original_description": None,
            "displayName": None,
        }
        shell_tool = {
            **base_fields,
            "id": f"codeexec:{server_id}:shell_exec",
            "name": META_TOOL_SHELL_EXEC,
            "original_name": META_TOOL_SHELL_EXEC,
            "custom_name": META_TOOL_SHELL_EXEC,
            "custom_name_slug": META_TOOL_SHELL_EXEC,
            "description": "Execute sandboxed code against virtual /tools, /scratch, /skills, /results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string", "enum": ["typescript", "python"]},
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": int(self._sandbox_limit_defaults.get("max_execution_time_ms", 30000)),
                    },
                    "stream": {"type": "boolean"},
                },
                "required": ["code"],
            },
        }
        browse_tool = {
            **base_fields,
            "id": f"codeexec:{server_id}:fs_browse",
            "name": META_TOOL_FS_BROWSE,
            "original_name": META_TOOL_FS_BROWSE,
            "custom_name": META_TOOL_FS_BROWSE,
            "custom_name_slug": META_TOOL_FS_BROWSE,
            "description": "List files/directories in the virtual tool filesystem without full code execution.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "/tools"},
                    "include_hidden": {"type": "boolean", "default": False},
                    "max_entries": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": self._fs_browse_max_entries,
                        "default": self._fs_browse_default_max_entries,
                    },
                },
            },
        }
        tools: List[Dict[str, Any]] = []
        if self._shell_exec_enabled:
            tools.append(shell_tool)
        if self._fs_browse_enabled:
            tools.append(browse_tool)
        return tools

    async def fs_browse(
        self,
        db: Session,
        server: DbServer,
        path: str,
        include_hidden: bool,
        max_entries: Any,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Browse virtual filesystem for a code execution server."""
        if not self._fs_browse_enabled:
            raise CodeExecutionError("fs_browse meta-tool is disabled by configuration")

        if max_entries is None:
            max_entries_value = self._fs_browse_default_max_entries
        elif isinstance(max_entries, bool):
            max_entries_value = self._fs_browse_default_max_entries
        else:
            try:
                max_entries_value = int(max_entries)
            except (TypeError, ValueError):
                max_entries_value = self._fs_browse_default_max_entries
        max_entries_value = max(1, min(max_entries_value, self._fs_browse_max_entries))

        language = getattr(server, "stub_language", None) or "python"
        session = await self._get_or_create_session(db=db, server=server, user_email=user_email or "anonymous", language=language, token_teams=token_teams)
        virtual_path = path or "/tools"
        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise CodeExecutionSecurityError(f"Path '{virtual_path}' is outside the virtual filesystem")
        if not real_path.exists():
            raise CodeExecutionError(f"Path not found: {virtual_path}")

        entries: List[Dict[str, Any]] = []
        if real_path.is_file():
            stat = real_path.stat()
            entries.append(
                {
                    "name": real_path.name,
                    "path": virtual_path,
                    "type": "file",
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        else:
            children = sorted(real_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for child in children:
                if not include_hidden and child.name.startswith("."):
                    continue
                stat = child.stat()
                entries.append(
                    {
                        "name": child.name,
                        "path": self._real_to_virtual_path(session, child),
                        "type": "directory" if child.is_dir() else "file",
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    }
                )
                if len(entries) >= max_entries_value:
                    break

        return {
            "path": virtual_path,
            "entries": entries,
            "truncated": len(entries) >= max_entries_value,
        }

    async def shell_exec(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        db: Session,
        server: DbServer,
        code: str,
        language: Optional[str],
        timeout_ms: Optional[int],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        request_headers: Optional[Dict[str, str]],
        invoke_tool: ToolInvokeCallback,
        stream: Optional[bool] = None,  # reserved; ignored for now
    ) -> Dict[str, Any]:
        """Execute sandboxed code for code_execution virtual servers."""
        del stream
        if not self._shell_exec_enabled:
            raise CodeExecutionError("shell_exec meta-tool is disabled by configuration")
        if not code or not code.strip():
            raise CodeExecutionError("code is required")

        policy = self._server_sandbox_policy(server)
        max_execution_time_ms = int(policy.get("max_execution_time_ms", self._sandbox_limit_defaults["max_execution_time_ms"]))
        effective_timeout = timeout_ms or max_execution_time_ms
        effective_timeout = max(100, min(effective_timeout, max_execution_time_ms))
        stub_language = (getattr(server, "stub_language", None) or ("typescript" if policy.get("runtime") == "deno" else "python")).lower()
        requested_language = (language or "").strip().lower() if language is not None else None
        is_shell = requested_language is None and self._looks_like_shell_command(code)
        execution_language = "shell" if is_shell else (requested_language or stub_language)
        session = await self._get_or_create_session(db=db, server=server, user_email=user_email or "anonymous", language=stub_language, token_teams=token_teams)
        self._enforce_rate_limit(server=server, user_email=user_email, policy=policy, session_id=session.session_id)

        tokenization_cfg = self._server_tokenization_policy(server)
        session.tokenization.enabled = bool(tokenization_cfg.get("enabled", False))
        session.tokenization.token_types = tuple(tokenization_cfg.get("types", []))

        if not is_shell:
            self._validate_code_safety(code=code, language=execution_language, allow_raw_http=bool(policy.get("allow_raw_http", False)), user_email=user_email, request_headers=request_headers)
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()

        run = CodeExecutionRun(
            server_id=server.id,
            session_id=session.session_id,
            user_email=user_email,
            language=execution_language,
            code_hash=code_hash,
            code_body=code,
            status="running",
            started_at=utc_now(),
            team_id=server.team_id,
            token_teams=token_teams,
            runtime=policy.get("runtime"),
            code_size_bytes=len(code.encode("utf-8")),
        )
        db.add(run)
        db.flush()

        output = ""
        error = ""
        security_events: List[Dict[str, Any]] = []
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        session.tool_calls = []
        runtime_name = str(policy.get("runtime") or "deno")

        async def _runtime_tool_handler(server_name: str, tool_name: str, args: Dict[str, Any]) -> Any:
            return await self._invoke_mounted_tool(
                session=session,
                policy=policy,
                server_name=server_name,
                tool_name=tool_name,
                args=args,
                invoke_tool=invoke_tool,
                request_headers=request_headers,
                user_email=user_email,
                security_events=security_events,
            )

        with create_span(
            "code_execution.shell_exec",
            {
                "code.hash": code_hash,
                "server.id": server.id,
                "user.email": user_email or "anonymous",
                "language": execution_language,
            },
        ):
            try:
                if is_shell:
                    result = await self._run_internal_shell(session=session, command=code, timeout_ms=effective_timeout, policy=policy)
                    output, error = result.stdout, result.stderr
                    if result.exit_code != 0 and not error:
                        error = f"Command exited with status {result.exit_code}"
                    run.status = "completed" if result.exit_code == 0 else "failed"
                elif execution_language in {"python", "typescript"}:
                    if execution_language == "typescript":
                        runtime = self._deno_runtime
                        runtime_name = "deno"
                    else:
                        runtime = self._python_runtime
                        runtime_name = "python"
                    run.runtime = runtime_name

                    if not await runtime.health_check():
                        # Backward-compatible fallback for hosts that cannot run isolated python subprocess.
                        if execution_language == "python" and self._python_inprocess_fallback_enabled:
                            py_result = await self._execute_python_inprocess(
                                code=code,
                                session=session,
                                timeout_ms=effective_timeout,
                                invoke_tool=invoke_tool,
                                policy=policy,
                                request_headers=request_headers,
                                user_email=user_email,
                            )
                            output = py_result.get("output", "")
                            error = py_result.get("error", "")
                            run.status = "completed" if not error else "failed"
                        elif execution_language == "python":
                            raise CodeExecutionError("Python runtime is not available on this host")
                        else:
                            raise CodeExecutionError("Deno runtime is not available on this host")
                    else:
                        await runtime.create_session(session=session, policy=policy)
                        runtime_result = await runtime.execute(
                            session=session,
                            code=code,
                            timeout_ms=effective_timeout,
                            policy=policy,
                            tool_handler=_runtime_tool_handler,
                        )
                        output, error = runtime_result.stdout, runtime_result.stderr
                        if runtime_result.exit_code != 0 and not error:
                            error = f"Execution exited with status {runtime_result.exit_code}"
                        run.status = "completed" if runtime_result.exit_code == 0 else "failed"
                else:
                    raise CodeExecutionError(f"Unsupported language: {execution_language}")

                self._enforce_disk_limits(session=session, policy=policy)
            except CodeExecutionSecurityError as exc:
                error = str(exc)
                run.status = "blocked"
                security_events.append({"event": "policy_block", "message": error})
                self._emit_security_event(
                    user_email=user_email,
                    description=error,
                    request_headers=request_headers,
                    threat_indicators={"reason": "policy_block", "language": execution_language},
                )
            except TimeoutError as exc:
                error = str(exc)
                run.status = "timed_out"
            except Exception as exc:  # pragma: no cover - defensive fallback
                error = str(exc)
                run.status = "failed"

        wall_ms = int((time.perf_counter() - wall_start) * 1000)
        cpu_ms = int((time.process_time() - cpu_start) * 1000)
        latencies = [tc.latency_ms for tc in session.tool_calls] or [0]
        metrics = {
            "run_id": run.id,
            "code_hash": code_hash,
            "wall_time_ms": wall_ms,
            "cpu_time_ms": cpu_ms,
            "tool_call_count": len(session.tool_calls),
            "tool_latency_p50_ms": int(statistics.median(latencies)),
            "tool_latency_p95_ms": int(self._percentile(latencies, 95)),
            "tool_latency_p99_ms": int(self._percentile(latencies, 99)),
            "error_rate": 0.0 if len(session.tool_calls) == 0 else sum(1 for tc in session.tool_calls if not tc.success) / len(session.tool_calls),
            "bytes_written": len(output.encode("utf-8", errors="replace")),
            "bytes_error": len(error.encode("utf-8", errors="replace")),
        }

        tokenization_cfg = self._server_tokenization_policy(server)
        session.tokenization.enabled = bool(tokenization_cfg.get("enabled", False))
        session.tokenization.token_types = tuple(tokenization_cfg.get("types", []))

        tokenized_output = output if not session.tokenization.enabled else str(session.tokenization.tokenize_obj(output))
        tokenized_error = error if not session.tokenization.enabled else str(session.tokenization.tokenize_obj(error))

        run.output = tokenized_output[: self._max_persisted_output_chars]
        run.error = tokenized_error[: self._max_persisted_output_chars] if tokenized_error else None
        run.metrics = metrics
        run.tool_calls_made = [tc.to_dict() for tc in session.tool_calls]
        run.security_events = security_events
        run.finished_at = utc_now()

        return {
            "output": tokenized_output,
            "error": tokenized_error or None,
            "metrics": metrics,
            "tool_calls_made": [tc.to_dict() for tc in session.tool_calls],
            "run_id": run.id,
        }

    async def list_runs(self, db: Session, server_id: str, limit: int = 50) -> List[CodeExecutionRun]:
        """List recent run history for a code execution server."""
        return db.execute(select(CodeExecutionRun).where(CodeExecutionRun.server_id == server_id).order_by(CodeExecutionRun.created_at.desc()).limit(limit)).scalars().all()

    async def list_active_sessions(self, server_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List in-memory active sessions, optionally filtered by server."""
        rows: List[Dict[str, Any]] = []
        async with self._lock:
            for session in self._sessions.values():
                if server_id and session.server_id != server_id:
                    continue
                try:
                    skill_files = [p for p in session.skills_dir.glob("*") if p.is_file() and p.name not in {"_meta.json", "__init__.py"}]
                except Exception:  # pragma: no cover - defensive
                    skill_files = []
                rows.append(
                    {
                        "session_id": session.session_id,
                        "server_id": session.server_id,
                        "user_email": session.user_email,
                        "language": session.language,
                        "created_at": session.created_at.isoformat(),
                        "last_used_at": session.last_used_at.isoformat(),
                        "generated_at": session.generated_at.isoformat() if session.generated_at else None,
                        "tool_count": len(session.mounted_tools),
                        "skill_count": len(skill_files),
                    }
                )
        rows.sort(key=lambda item: item["last_used_at"], reverse=True)
        return rows

    async def replay_run(
        self,
        db: Session,
        run_id: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        request_headers: Optional[Dict[str, str]],
        invoke_tool: ToolInvokeCallback,
    ) -> Dict[str, Any]:
        """Replay a previous code execution run with debug metadata."""
        if not self._replay_enabled:
            raise CodeExecutionError("Replay is disabled by configuration")

        run = db.get(CodeExecutionRun, run_id)
        if not run:
            raise CodeExecutionError(f"Run not found: {run_id}")
        if not run.code_body:
            raise CodeExecutionError("Replay unavailable: code body was not persisted")

        server = db.get(DbServer, run.server_id)
        if not server:
            raise CodeExecutionError(f"Server not found: {run.server_id}")

        replay_result = await self.shell_exec(
            db=db,
            server=server,
            code=run.code_body,
            language=run.language,
            timeout_ms=int((run.metrics or {}).get("wall_time_ms", self._sandbox_limit_defaults["max_execution_time_ms"])),
            user_email=user_email,
            token_teams=token_teams,
            request_headers=request_headers,
            invoke_tool=invoke_tool,
        )
        replay_result["replayed_from_run_id"] = run_id
        return replay_result

    async def create_skill(
        self,
        db: Session,
        server: DbServer,
        name: str,
        source_code: str,
        language: str,
        description: Optional[str],
        owner_email: Optional[str],
        created_by: Optional[str],
    ) -> CodeExecutionSkill:
        """Create a persisted skill and optionally queue approval."""
        current_version = db.execute(select(CodeExecutionSkill.version).where(CodeExecutionSkill.server_id == server.id, CodeExecutionSkill.name == name).order_by(CodeExecutionSkill.version.desc())).scalars().first()
        next_version = (current_version or 0) + 1
        requires_approval = bool(getattr(server, "skills_require_approval", False))
        status = "pending" if requires_approval else "approved"
        skill = CodeExecutionSkill(
            server_id=server.id,
            name=name,
            description=description,
            language=language,
            source_code=source_code,
            version=next_version,
            status=status,
            owner_email=owner_email,
            team_id=server.team_id,
            created_by=created_by,
            created_via="api",
            version_counter=1,
        )
        db.add(skill)
        db.flush()

        if requires_approval:
            approval = SkillApproval(
                skill_id=skill.id,
                requested_by=owner_email,
                requested_at=utc_now(),
                expires_at=utc_now() + timedelta(days=30),
                status="pending",
            )
            db.add(approval)
        else:
            skill.approved_at = utc_now()
            skill.approved_by = created_by

        return skill

    async def list_skills(self, db: Session, server_id: str, include_inactive: bool = False) -> List[CodeExecutionSkill]:
        """List skills for a code execution server."""
        query = select(CodeExecutionSkill).where(CodeExecutionSkill.server_id == server_id).order_by(CodeExecutionSkill.name.asc(), CodeExecutionSkill.version.desc())
        if not include_inactive:
            query = query.where(CodeExecutionSkill.is_active.is_(True))
        return db.execute(query).scalars().all()

    async def approve_skill(self, db: Session, approval_id: str, reviewer_email: str, approve: bool, reason: Optional[str] = None) -> SkillApproval:
        """Approve or reject a pending skill request."""
        approval = db.get(SkillApproval, approval_id)
        if not approval:
            raise CodeExecutionError(f"Skill approval not found: {approval_id}")
        skill = db.get(CodeExecutionSkill, approval.skill_id)
        if not skill:
            raise CodeExecutionError(f"Skill not found: {approval.skill_id}")
        if approval.status != "pending":
            raise CodeExecutionError(f"Approval is already in terminal state: {approval.status}")
        approval.reviewed_by = reviewer_email
        approval.reviewed_at = utc_now()
        if approve:
            approval.status = "approved"
            skill.status = "approved"
            skill.approved_by = reviewer_email
            skill.approved_at = utc_now()
            skill.rejection_reason = None
        else:
            approval.status = "rejected"
            approval.rejection_reason = reason or "Rejected"
            skill.status = "rejected"
            skill.rejection_reason = approval.rejection_reason
            skill.is_active = False
        return approval

    async def revoke_skill(self, db: Session, skill_id: str, reviewer_email: str, reason: Optional[str] = None) -> CodeExecutionSkill:
        """Revoke an active skill."""
        skill = db.get(CodeExecutionSkill, skill_id)
        if not skill:
            raise CodeExecutionError(f"Skill not found: {skill_id}")
        skill.status = "revoked"
        skill.is_active = False
        skill.rejection_reason = reason or "Revoked"
        skill.modified_by = reviewer_email
        skill.modified_via = "api"
        skill.updated_at = utc_now()
        return skill

    async def _get_or_create_session(
        self,
        db: Session,
        server: DbServer,
        user_email: str,
        language: str,
        token_teams: Optional[List[str]],
    ) -> CodeExecutionSession:
        key = (server.id, user_email, language)
        async with self._lock:
            session = self._sessions.get(key)
            now = utc_now()
            ttl = int((self._server_sandbox_policy(server)).get("session_ttl_seconds", self._default_ttl))
            expired = session and (now - session.last_used_at).total_seconds() > ttl
            if session and expired:
                await self._destroy_session(session)
                self._sessions.pop(key, None)
                session = None

            if session is None:
                session_id = uuid.uuid4().hex
                root = self._base_dir / server.id / user_email.replace("@", "_") / session_id
                tools_dir = root / "tools"
                scratch_dir = root / "scratch"
                skills_dir = root / "skills"
                results_dir = root / "results"
                for directory in (tools_dir, scratch_dir, skills_dir, results_dir):
                    directory.mkdir(parents=True, exist_ok=True)
                session = CodeExecutionSession(
                    session_id=session_id,
                    server_id=server.id,
                    user_email=user_email,
                    language=language,
                    root_dir=root,
                    created_at=now,
                    last_used_at=now,
                    tools_dir=tools_dir,
                    scratch_dir=scratch_dir,
                    skills_dir=skills_dir,
                    results_dir=results_dir,
                )
                session.tokenization.enabled = bool(self._server_tokenization_policy(server).get("enabled", False))
                session.tokenization.token_types = tuple(self._server_tokenization_policy(server).get("types", []))
                self._sessions[key] = session

            session.last_used_at = now
            await self._refresh_virtual_filesystem_if_needed(db=db, session=session, server=server, token_teams=token_teams)
            return session

    async def _refresh_virtual_filesystem_if_needed(self, db: Session, session: CodeExecutionSession, server: DbServer, token_teams: Optional[List[str]]) -> None:
        mounted = self._resolve_mounted_tools(db=db, server=server, user_email=session.user_email, token_teams=token_teams)
        skills = self._resolve_mounted_skills(
            db=db,
            server=server,
            user_email=session.user_email,
            token_teams=token_teams,
            language=session.language,
        )
        digest_src = [
            f"{tool.id}:{tool.updated_at.isoformat() if getattr(tool, 'updated_at', None) else ''}:{tool.name}"
            for tool in mounted
        ]
        digest_src.extend(
            [
                f"skill:{skill.id}:{skill.name}:{skill.version}:{skill.updated_at.isoformat() if skill.updated_at else ''}:{skill.language}"
                for skill in skills
            ]
        )
        digest = hashlib.sha256("\n".join(sorted(digest_src)).encode("utf-8")).hexdigest()
        if session.content_hash == digest and session.generated_at:
            return

        session.mounted_tools = {}
        session.runtime_tool_index = {}
        self._wipe_and_recreate_directory(session.tools_dir)
        self._wipe_and_recreate_directory(session.skills_dir)
        (session.tools_dir / "_schema.json").write_text(
            json.dumps(
                {
                    "version": VFS_SCHEMA_VERSION,
                    "roots": ["/tools", "/scratch", "/skills", "/results"],
                    "stub_language": session.language,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._write_runtime_helpers(session.tools_dir)
        self._mount_skills(session=session, skills=skills)

        grouped: Dict[str, List[DbTool]] = defaultdict(list)
        catalog_tools: List[Dict[str, Any]] = []
        for tool in mounted:
            server_slug = self._tool_server_slug(tool)
            stub_basename = self._tool_file_name(tool)
            python_server_alias = self._python_identifier(server_slug)
            python_tool_alias = self._python_identifier(stub_basename)
            grouped[server_slug].append(tool)
            server_aliases = {
                self._normalize_runtime_alias(server_slug),
                self._normalize_runtime_alias(python_server_alias),
                self._normalize_runtime_alias(server_slug.replace("-", "_")),
                self._normalize_runtime_alias(server_slug.replace("_", "-")),
            }
            tool_aliases = {
                self._normalize_runtime_alias(stub_basename),
                self._normalize_runtime_alias(python_tool_alias),
                self._normalize_runtime_alias(tool.name),
                self._normalize_runtime_alias(getattr(tool, "original_name", "") or ""),
            }
            for server_alias in server_aliases:
                for tool_alias in tool_aliases:
                    if not server_alias or not tool_alias:
                        continue
                    session.runtime_tool_index[(server_alias, tool_alias)] = tool.name

            session.mounted_tools[tool.name] = {
                "tool_id": tool.id,
                "tool_name": tool.name,
                "server_slug": server_slug,
                "stub_basename": stub_basename,
                "python_server_alias": python_server_alias,
                "python_tool_alias": python_tool_alias,
                "original_name": getattr(tool, "original_name", None),
                "description": tool.description,
                "input_schema": tool.input_schema,
                "tags": tool.tags or [],
            }
            catalog_tools.append(
                {
                    "id": tool.id,
                    "name": tool.name,
                    "original_name": tool.original_name,
                    "server": server_slug,
                    "description": tool.description,
                    "tags": tool.tags or [],
                    "created_by": tool.created_by,
                    "created_at": tool.created_at.isoformat() if tool.created_at else None,
                    "created_from_ip": getattr(tool, "created_from_ip", None),
                    "created_via": tool.created_via,
                    "created_user_agent": getattr(tool, "created_user_agent", None),
                    "federation_source": tool.federation_source,
                    "modified_by": tool.modified_by,
                    "modified_at": tool.updated_at.isoformat() if tool.updated_at else None,
                    "modified_from_ip": getattr(tool, "modified_from_ip", None),
                    "modified_via": getattr(tool, "modified_via", None),
                    "modified_user_agent": getattr(tool, "modified_user_agent", None),
                    "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                }
            )

        for server_slug, tools in grouped.items():
            server_dir = session.tools_dir / server_slug
            server_dir.mkdir(parents=True, exist_ok=True)
            meta_payload = {
                "server": server_slug,
                "tool_count": len(tools),
                "auth_status": "unknown",
                "health": "unknown",
                "generated_at": utc_now().isoformat(),
            }
            (server_dir / "_meta.json").write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
            for tool in tools:
                base_name = self._tool_file_name(tool)
                if session.language == "typescript":
                    stub = self._generate_typescript_stub(tool=tool, server_slug=server_slug)
                    (server_dir / f"{base_name}.ts").write_text(stub, encoding="utf-8")
                else:
                    stub = self._generate_python_stub(tool=tool, server_slug=server_slug)
                    (server_dir / f"{base_name}.py").write_text(stub, encoding="utf-8")

        catalog = {
            "generated_at": utc_now().isoformat(),
            "schema_version": VFS_SCHEMA_VERSION,
            "server_id": server.id,
            "tool_count": len(catalog_tools),
            "tools": catalog_tools,
        }
        catalog_payload = json.dumps(catalog, indent=2)
        if self._is_rust_acceleration_available() and rust_catalog_builder is not None:
            with contextlib.suppress(Exception):
                catalog_payload = rust_catalog_builder(catalog_payload)
        (session.tools_dir / "_catalog.json").write_text(catalog_payload, encoding="utf-8")
        self._build_search_index(session.tools_dir)
        session.generated_at = utc_now()
        session.content_hash = digest

    def _resolve_mounted_tools(self, db: Session, server: DbServer, user_email: Optional[str], token_teams: Optional[List[str]]) -> List[DbTool]:
        query = select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.enabled.is_(True), DbTool.reachable.is_(True))
        tools = db.execute(query).scalars().all()
        mount_rules = self._server_mount_rules(server)

        resolved: List[DbTool] = []
        for tool in tools:
            if not self._tool_visible_for_scope(tool, user_email=user_email, token_teams=token_teams):
                continue
            if not self._tool_matches_mount_rules(tool, mount_rules):
                continue
            resolved.append(tool)
        return resolved

    def _resolve_mounted_skills(
        self,
        db: Session,
        server: DbServer,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        language: str,
    ) -> List[CodeExecutionSkill]:
        query = (
            select(CodeExecutionSkill)
            .where(
                CodeExecutionSkill.server_id == server.id,
                CodeExecutionSkill.is_active.is_(True),
                CodeExecutionSkill.status == "approved",
                CodeExecutionSkill.language == language,
            )
            .order_by(CodeExecutionSkill.name.asc(), CodeExecutionSkill.version.desc())
        )
        rows = db.execute(query).scalars().all()
        skills_scope = str(getattr(server, "skills_scope", "") or "").strip()
        latest_by_name: Dict[str, CodeExecutionSkill] = {}
        for skill in rows:
            if not self._skill_visible_for_scope(skill=skill, user_email=user_email, token_teams=token_teams, skills_scope=skills_scope):
                continue
            existing = latest_by_name.get(skill.name)
            if existing is None or int(getattr(skill, "version", 0) or 0) > int(getattr(existing, "version", 0) or 0):
                latest_by_name[skill.name] = skill
        return list(latest_by_name.values())

    def _skill_visible_for_scope(
        self,
        skill: CodeExecutionSkill,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        skills_scope: str,
    ) -> bool:
        if token_teams is None:
            return True

        if skills_scope.startswith("user:"):
            target_user = skills_scope.split(":", 1)[1].strip()
            if target_user and user_email != target_user:
                return False
        elif skills_scope.startswith("team:"):
            scope_team = skills_scope.split(":", 1)[1].strip()
            if scope_team:
                if not token_teams or scope_team not in token_teams:
                    return False

        if len(token_teams) == 0:
            return bool(user_email and skill.owner_email == user_email)

        if skill.team_id and skill.team_id not in token_teams:
            return bool(user_email and skill.owner_email == user_email)
        return True

    def _mount_skills(self, session: CodeExecutionSession, skills: Sequence[CodeExecutionSkill]) -> None:
        if session.language == "python":
            (session.skills_dir / "__init__.py").write_text("# Auto-generated skills package\n", encoding="utf-8")

        skills_meta: List[Dict[str, Any]] = []
        for skill in skills:
            filename = self._python_identifier(slugify(skill.name))
            ext = "ts" if session.language == "typescript" else "py"
            target = session.skills_dir / f"{filename}.{ext}"
            target.write_text(skill.source_code or "", encoding="utf-8")
            skills_meta.append(
                {
                    "id": skill.id,
                    "name": skill.name,
                    "version": skill.version,
                    "language": skill.language,
                    "owner_email": skill.owner_email,
                    "team_id": skill.team_id,
                    "path": f"/skills/{filename}.{ext}",
                }
            )

        (session.skills_dir / "_meta.json").write_text(
            json.dumps(
                {
                    "generated_at": utc_now().isoformat(),
                    "skill_count": len(skills_meta),
                    "skills": skills_meta,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _tool_visible_for_scope(self, tool: DbTool, user_email: Optional[str], token_teams: Optional[List[str]]) -> bool:
        # Admin bypass: token_teams is None (normalize_token_teams contract).
        if token_teams is None:
            return True
        if token_teams is not None:
            if len(token_teams) == 0:
                return tool.visibility == "public"
            if tool.visibility == "public":
                return True
            if user_email and tool.owner_email == user_email:
                return True
            return tool.team_id in token_teams and tool.visibility in {"team", "public"}
        # Conservative fallback: public + owner only.
        if tool.visibility == "public":
            return True
        return bool(user_email and tool.owner_email == user_email)

    def _tool_matches_mount_rules(self, tool: DbTool, mount_rules: Dict[str, Any]) -> bool:
        tags = set(tool.tags or [])
        include_tags = set(mount_rules.get("include_tags") or [])
        exclude_tags = set(mount_rules.get("exclude_tags") or [])
        include_tools = set(mount_rules.get("include_tools") or [])
        exclude_tools = set(mount_rules.get("exclude_tools") or [])
        include_servers = set(mount_rules.get("include_servers") or [])
        exclude_servers = set(mount_rules.get("exclude_servers") or [])
        server_slug = self._tool_server_slug(tool)

        if include_tags and not tags.intersection(include_tags):
            return False
        if exclude_tags and tags.intersection(exclude_tags):
            return False
        if include_tools and tool.name not in include_tools and tool.original_name not in include_tools:
            return False
        if tool.name in exclude_tools or tool.original_name in exclude_tools:
            return False
        if include_servers and server_slug not in include_servers:
            return False
        if server_slug in exclude_servers:
            return False
        return True

    def _server_mount_rules(self, server: DbServer) -> Dict[str, Any]:
        raw = getattr(server, "mount_rules", None) or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            return {}
        return dict(raw)

    def _server_sandbox_policy(self, server: DbServer) -> Dict[str, Any]:
        raw = getattr(server, "sandbox_policy", None) or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            raw = {}

        # Normalize support for both "flat" configs and nested {limits,permissions}.
        limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
        permissions = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}

        # Flat keys take precedence over nested limits.
        for key in (
            "max_execution_time_ms",
            "max_memory_mb",
            "max_cpu_percent",
            "max_network_connections",
            "max_file_size_mb",
            "max_total_disk_mb",
            "max_runs_per_minute",
            "session_ttl_seconds",
        ):
            if key in raw:
                limits[key] = raw.get(key)

        runtime = raw.get("runtime") or limits.get("runtime") or self._default_runtime
        runtime_requirements = raw.get("runtime_requirements") if isinstance(raw.get("runtime_requirements"), dict) else {}
        if not isinstance(runtime, str):
            runtime = self._default_runtime
        runtime = runtime.strip().lower() or self._default_runtime
        if runtime not in {"deno", "python"}:
            preferred_language = str(runtime_requirements.get("language") or "").strip().lower()
            if preferred_language in {"deno", "python"}:
                runtime = preferred_language
            else:
                runtime = self._default_runtime
        allow_raw_http = bool(raw.get("allow_raw_http", self._default_allow_raw_http))

        limit_defaults: Dict[str, Any] = dict(self._sandbox_limit_defaults)
        limit_defaults["session_ttl_seconds"] = self._default_ttl
        for k, v in limit_defaults.items():
            candidate = limits.get(k)
            if candidate is None:
                limits[k] = v
                continue
            if isinstance(candidate, bool):
                # Avoid bool being treated as int.
                limits[k] = v
                continue
            try:
                limits[k] = int(candidate)
            except (TypeError, ValueError):
                limits[k] = v

        fs_default = dict(self._sandbox_permissions_defaults.get("filesystem", {}))
        tools_default = dict(self._sandbox_permissions_defaults.get("tools", {}))
        network_default = dict(self._sandbox_permissions_defaults.get("network", {}))
        network_default["allow_raw_http"] = allow_raw_http

        fs_perm = permissions.get("filesystem") if isinstance(permissions.get("filesystem"), dict) else {}
        tool_perm = permissions.get("tools") if isinstance(permissions.get("tools"), dict) else {}
        net_perm = permissions.get("network") if isinstance(permissions.get("network"), dict) else {}

        fs_perm = {**fs_default, **fs_perm}
        tool_perm = {**tools_default, **tool_perm}
        net_perm = {**network_default, **net_perm}

        normalized = {
            "runtime": runtime,
            "runtime_requirements": runtime_requirements,
            "limits": limits,
            "permissions": {
                "filesystem": fs_perm,
                "tools": tool_perm,
                "network": net_perm,
            },
        }

        # Backward-compatible flat keys.
        normalized.update(limits)
        normalized["allow_raw_http"] = bool(net_perm.get("allow_raw_http", False))
        return normalized

    def _server_tokenization_policy(self, server: DbServer) -> Dict[str, Any]:
        raw = getattr(server, "tokenization", None) or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            raw = {}
        defaults = dict(self._tokenization_defaults)
        defaults.update(raw)
        defaults["types"] = _coerce_string_list(defaults.get("types"), _DEFAULT_TOKENIZATION_TYPES)
        return defaults

    def _validate_code_safety(self, code: str, language: str, allow_raw_http: bool, user_email: Optional[str], request_headers: Optional[Dict[str, str]]) -> None:
        patterns = self._python_dangerous_patterns if language == "python" else self._typescript_dangerous_patterns
        if allow_raw_http:
            patterns = tuple(p for p in patterns if "fetch" not in p and "curl" not in p and "wget" not in p)

        for pattern in patterns:
            if re.search(pattern, code):
                message = f"Blocked dangerous code pattern: {pattern}"
                self._emit_security_event(
                    user_email=user_email,
                    description=message,
                    request_headers=request_headers,
                    threat_indicators={"pattern": pattern, "language": language},
                )
                raise CodeExecutionSecurityError(message)

    def _enforce_rate_limit(self, server: DbServer, user_email: Optional[str], policy: Dict[str, Any], session_id: Optional[str] = None) -> None:
        key = (server.id, user_email or "anonymous")
        user_window = self._rate_windows[key]
        session_window = self._session_rate_windows[session_id] if session_id else None
        now = time.monotonic()
        while user_window and now - user_window[0] > 60:
            user_window.popleft()
        if session_window is not None:
            while session_window and now - session_window[0] > 60:
                session_window.popleft()
        limit = int(policy.get("max_runs_per_minute", self._sandbox_limit_defaults["max_runs_per_minute"]))
        if len(user_window) >= limit:
            raise CodeExecutionRateLimitError(f"Rate limit exceeded: max {limit} runs/minute")
        if session_window is not None and len(session_window) >= limit:
            raise CodeExecutionRateLimitError(f"Session rate limit exceeded: max {limit} runs/minute")
        user_window.append(now)
        if session_window is not None:
            session_window.append(now)

    async def _execute_python_inprocess(  # pylint: disable=too-many-locals
        self,
        code: str,
        session: CodeExecutionSession,
        timeout_ms: int,
        invoke_tool: ToolInvokeCallback,
        policy: Dict[str, Any],
        request_headers: Optional[Dict[str, str]],
        user_email: Optional[str],
    ) -> Dict[str, str]:
        """Execute python code in-process with safe globals and __toolcall__ bridge."""
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        async def _bridge(a: str, b: Optional[Any] = None, c: Optional[Any] = None) -> Any:
            server_name = ""
            tool_name = ""
            args: Dict[str, Any] = {}
            if c is None and isinstance(b, dict):
                tool_name = str(a)
                args = b
            else:
                server_name = str(a or "")
                tool_name = str(b or "")
                args = c if isinstance(c, dict) else {}
            return await self._invoke_mounted_tool(
                session=session,
                policy=policy,
                server_name=server_name,
                tool_name=tool_name,
                args=args,
                invoke_tool=invoke_tool,
                request_headers=request_headers,
                user_email=user_email,
                security_events=[],
            )

        tools_namespace = self._build_python_tools_namespace(session=session, bridge=_bridge)

        globals_dict: Dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "__toolcall__": _bridge,
            "tools": tools_namespace,
            "json": json,
            "read_file": lambda p: self._read_virtual_text_file(session, p),
            "write_file": lambda p, c: self._write_virtual_text_file(session, p, c),
            "list_dir": lambda p="/tools": self._list_virtual_dir(session, p),
        }

        wrapped = "async def __user_main__():\n"
        for line in code.splitlines():
            wrapped += f"    {line}\n"

        try:
            exec(wrapped, globals_dict)  # noqa: S102 - executed with restricted builtins and static analyzer
            user_fn = globals_dict["__user_main__"]
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                result = await asyncio.wait_for(user_fn(), timeout=timeout_ms / 1000)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False, default=str), file=stdout_buffer)
        except TimeoutError as exc:
            raise CodeExecutionError(f"Execution timed out after {timeout_ms}ms") from exc
        return {"output": stdout_buffer.getvalue(), "error": stderr_buffer.getvalue()}

    def _normalize_runtime_alias(self, value: str) -> str:
        """Normalize server/tool aliases for runtime bridge lookup."""
        return re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower()).strip("_")

    def _resolve_runtime_tool_name(self, session: CodeExecutionSession, server_name: str, tool_name: str) -> str:
        """Resolve runtime (server,tool) aliases into mounted gateway tool names."""
        normalized_tool = self._normalize_runtime_alias(tool_name)
        normalized_server = self._normalize_runtime_alias(server_name)

        if normalized_server:
            resolved = session.runtime_tool_index.get((normalized_server, normalized_tool))
            if resolved:
                return resolved

        # Support direct calls by canonical tool name for backward compatibility.
        if tool_name in session.mounted_tools:
            return tool_name

        # Allow unqualified tool lookup when alias is unique.
        matches = [
            mounted_tool
            for (server_alias, tool_alias), mounted_tool in session.runtime_tool_index.items()
            if tool_alias == normalized_tool and (not normalized_server or server_alias == normalized_server)
        ]
        unique = set(matches)
        if len(unique) == 1:
            return next(iter(unique))

        if normalized_server:
            raise CodeExecutionSecurityError(f"Tool '{server_name}/{tool_name}' is not mounted for this server")
        raise CodeExecutionSecurityError(f"Tool '{tool_name}' is not mounted for this server")

    async def _invoke_mounted_tool(
        self,
        session: CodeExecutionSession,
        policy: Dict[str, Any],
        server_name: str,
        tool_name: str,
        args: Dict[str, Any],
        invoke_tool: ToolInvokeCallback,
        request_headers: Optional[Dict[str, str]],
        user_email: Optional[str],
        security_events: List[Dict[str, Any]],
    ) -> Any:
        """Invoke mounted tool with RBAC/rate/tokenization/telemetry hooks."""
        resolved_tool = self._resolve_runtime_tool_name(session=session, server_name=server_name, tool_name=tool_name)
        try:
            self._enforce_tool_call_permission(policy=policy, session=session, tool_name=resolved_tool)
        except CodeExecutionSecurityError as exc:
            security_events.append(
                {
                    "event": "tool_call_blocked",
                    "tool": resolved_tool,
                    "message": str(exc),
                    "at": utc_now().isoformat(),
                }
            )
            self._emit_security_event(
                user_email=user_email,
                description=str(exc),
                request_headers=request_headers,
                threat_indicators={"reason": "tool_call_blocked", "tool": resolved_tool},
            )
            raise
        bridged_args = session.tokenization.detokenize_obj(args or {})
        started_at = utc_now()
        started_ts = time.perf_counter()

        with create_span(
            "code_execution.tool_call",
            {
                "session.id": session.session_id,
                "tool.name": resolved_tool,
                "tool.server": server_name or "",
            },
        ):
            try:
                result = await invoke_tool(resolved_tool, bridged_args)
                latency = int((time.perf_counter() - started_ts) * 1000)
                session.tool_calls.append(ToolCallRecord(name=resolved_tool, started_at=started_at, latency_ms=latency, success=True))
                obj = self._tool_result_to_python_obj(result)
                return session.tokenization.tokenize_obj(obj)
            except CodeExecutionSecurityError:
                raise
            except Exception as exc:  # pragma: no cover - passthrough errors
                latency = int((time.perf_counter() - started_ts) * 1000)
                session.tool_calls.append(ToolCallRecord(name=resolved_tool, started_at=started_at, latency_ms=latency, success=False, error=str(exc)))
                security_events.append(
                    {
                        "event": "tool_call_error",
                        "tool": resolved_tool,
                        "message": str(exc),
                        "at": utc_now().isoformat(),
                    }
                )
                self._emit_security_event(
                    user_email=user_email,
                    description=f"Tool call failed for {resolved_tool}: {exc}",
                    request_headers=request_headers,
                    threat_indicators={"reason": "tool_call_error", "tool": resolved_tool},
                )
                raise

    async def _run_internal_shell(self, session: CodeExecutionSession, command: str, timeout_ms: int, policy: Dict[str, Any]) -> SandboxExecutionResult:
        """Run a restricted shell pipeline against the virtual filesystem.

        This is intentionally NOT an OS shell. It supports a safe subset of
        common Unix commands (ls/cat/grep/rg/jq) and enforces filesystem policy.
        """
        started = time.perf_counter()
        try:
            stdout, stderr, exit_code = await asyncio.wait_for(
                asyncio.to_thread(self._execute_shell_pipeline_sync, session, command, policy),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError as exc:
            raise CodeExecutionError(f"Execution timed out after {timeout_ms}ms") from exc
        wall = int((time.perf_counter() - started) * 1000)
        return SandboxExecutionResult(stdout=stdout, stderr=stderr, exit_code=exit_code, wall_time_ms=wall)

    def _execute_shell_pipeline_sync(self, session: CodeExecutionSession, command: str, policy: Dict[str, Any]) -> Tuple[str, str, int]:
        tokens = shlex.split(command, posix=True)
        if not tokens:
            return ("", "", 0)

        pipeline: List[List[str]] = []
        current: List[str] = []
        for token in tokens:
            if token == "|":
                if current:
                    pipeline.append(current)
                current = []
            else:
                current.append(token)
        if current:
            pipeline.append(current)

        stdin: str = ""
        stderr: str = ""
        exit_code = 0

        for argv in pipeline:
            if not argv:
                continue
            cmd = argv[0]
            args = argv[1:]
            try:
                if cmd == "ls":
                    stdin, stderr, exit_code = self._shell_ls(session=session, args=args, policy=policy)
                elif cmd == "cat":
                    stdin, stderr, exit_code = self._shell_cat(session=session, args=args, stdin=stdin, policy=policy)
                elif cmd in {"grep", "rg"}:
                    stdin, stderr, exit_code = self._shell_grep(session=session, cmd=cmd, args=args, stdin=stdin, policy=policy)
                elif cmd == "jq":
                    stdin, stderr, exit_code = self._shell_jq(session=session, args=args, stdin=stdin, policy=policy)
                else:
                    raise CodeExecutionSecurityError(f"EACCES: command '{cmd}' is not permitted")
            except CodeExecutionSecurityError as exc:
                return ("", str(exc), 126)
            except CodeExecutionError as exc:
                return ("", str(exc), 1)
            except Exception as exc:  # pragma: no cover - defensive
                return ("", str(exc), 1)

            if exit_code != 0:
                # Stop pipeline on error (predictable behavior for agents).
                break

        return (stdin, stderr, exit_code)

    def _shell_ls(self, session: CodeExecutionSession, args: List[str], policy: Dict[str, Any]) -> Tuple[str, str, int]:
        include_hidden = False
        paths: List[str] = []
        for arg in args:
            if arg in {"-a", "--all"}:
                include_hidden = True
            elif arg.startswith("-"):
                return ("", f"Unsupported ls option: {arg}", 2)
            else:
                paths.append(arg)

        path = paths[0] if paths else "."
        virtual_path = self._normalize_shell_path(path)
        self._enforce_fs_permission(policy=policy, operation="read", virtual_path=virtual_path)

        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_path}")
        if not real_path.exists():
            raise CodeExecutionError(f"Path not found: {virtual_path}")

        if real_path.is_file():
            return (f"{real_path.name}\n", "", 0)

        entries: List[str] = []
        for child in sorted(real_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if not include_hidden and child.name.startswith("."):
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(f"{child.name}{suffix}")
        return ("\n".join(entries) + ("\n" if entries else ""), "", 0)

    def _shell_cat(self, session: CodeExecutionSession, args: List[str], stdin: str, policy: Dict[str, Any]) -> Tuple[str, str, int]:
        if not args:
            return (stdin, "", 0)

        chunks: List[str] = []
        for path in args:
            virtual_path = self._normalize_shell_path(path)
            self._enforce_fs_permission(policy=policy, operation="read", virtual_path=virtual_path)
            real_path = self._virtual_to_real_path(session, virtual_path)
            if real_path is None or not real_path.exists() or not real_path.is_file():
                raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_path}")
            chunks.append(real_path.read_text(encoding="utf-8"))
        return ("\n".join(chunks), "", 0)

    def _shell_grep(self, session: CodeExecutionSession, cmd: str, args: List[str], stdin: str, policy: Dict[str, Any]) -> Tuple[str, str, int]:
        recursive = False
        list_files = False
        include_glob: Optional[str] = None

        positionals: List[str] = []
        idx = 0
        while idx < len(args):
            arg = args[idx]
            if arg in {"-r", "-R"}:
                recursive = True
                idx += 1
                continue
            if arg == "-l":
                list_files = True
                idx += 1
                continue
            if arg.startswith("--include="):
                include_glob = arg.split("=", 1)[1]
                idx += 1
                continue
            if arg == "--include" and idx + 1 < len(args):
                include_glob = args[idx + 1]
                idx += 2
                continue
            if arg.startswith("-"):
                return ("", f"Unsupported {cmd} option: {arg}", 2)
            positionals.append(arg)
            idx += 1

        if not positionals:
            raise CodeExecutionError(f"{cmd}: missing pattern")
        pattern = positionals[0]
        search_paths = positionals[1:]

        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise CodeExecutionError(f"{cmd}: invalid regex: {exc}") from exc

        # grep from stdin when no path is provided and input exists
        if not search_paths and stdin:
            matched_lines = [line for line in stdin.splitlines() if rx.search(line)]
            return ("\n".join(matched_lines) + ("\n" if matched_lines else ""), "", 0 if matched_lines else 1)

        if not search_paths:
            search_paths = ["."]

        if (
            recursive
            and list_files
            and include_glob is None
            and len(search_paths) == 1
            and self._is_rust_acceleration_available()
            and rust_fs_search is not None
        ):
            virtual_root = self._normalize_shell_path(search_paths[0])
            if virtual_root == "/tools":
                self._enforce_fs_permission(policy=policy, operation="read", virtual_path=virtual_root)
                index_file = session.tools_dir / ".search_index"
                if index_file.exists():
                    with contextlib.suppress(Exception):
                        index_content = index_file.read_text(encoding="utf-8")
                        paths = rust_fs_search(index_content, pattern)
                        normalized = sorted({f"/tools/{str(path).lstrip('/')}" for path in paths})
                        return ("\n".join(normalized) + ("\n" if normalized else ""), "", 0 if normalized else 1)

        matches: List[str] = []
        for raw_path in search_paths:
            virtual_root = self._normalize_shell_path(raw_path)
            self._enforce_fs_permission(policy=policy, operation="read", virtual_path=virtual_root)
            real_root = self._virtual_to_real_path(session, virtual_root)
            if real_root is None:
                raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_root}")
            if not real_root.exists():
                continue

            if recursive and real_root.is_dir():
                for dirpath, dirnames, filenames in os.walk(real_root, followlinks=False):
                    # Prune hidden dirs unless explicitly included via glob; safest default.
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    for filename in filenames:
                        if filename.startswith("."):
                            continue
                        if include_glob and not fnmatch.fnmatch(filename, include_glob):
                            continue
                        file_path = Path(dirpath) / filename
                        if file_path.is_symlink():
                            continue
                        with contextlib.suppress(Exception):
                            content = file_path.read_text(encoding="utf-8")
                            if rx.search(content):
                                vpath = self._real_to_virtual_path(session, file_path)
                                if list_files:
                                    matches.append(vpath)
                                else:
                                    for line in content.splitlines():
                                        if rx.search(line):
                                            matches.append(f"{vpath}:{line}")
            else:
                if real_root.is_dir():
                    continue
                if include_glob and not fnmatch.fnmatch(real_root.name, include_glob):
                    continue
                content = real_root.read_text(encoding="utf-8")
                if rx.search(content):
                    vpath = self._real_to_virtual_path(session, real_root)
                    if list_files:
                        matches.append(vpath)
                    else:
                        for line in content.splitlines():
                            if rx.search(line):
                                matches.append(f"{vpath}:{line}")

        return ("\n".join(matches) + ("\n" if matches else ""), "", 0 if matches else 1)

    def _shell_jq(self, session: CodeExecutionSession, args: List[str], stdin: str, policy: Dict[str, Any]) -> Tuple[str, str, int]:
        if not args:
            raise CodeExecutionError("jq: missing filter")
        jq_filter = args[0]
        file_arg = args[1] if len(args) > 1 else None

        raw_input = stdin
        if file_arg:
            virtual_path = self._normalize_shell_path(file_arg)
            self._enforce_fs_permission(policy=policy, operation="read", virtual_path=virtual_path)
            real_path = self._virtual_to_real_path(session, virtual_path)
            if real_path is None or not real_path.exists() or not real_path.is_file():
                raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_path}")
            raw_input = real_path.read_text(encoding="utf-8")

        if not raw_input.strip():
            return ("", "", 0)

        try:
            parsed = json.loads(raw_input)
        except json.JSONDecodeError as exc:
            raise CodeExecutionError(f"jq: invalid JSON input: {exc}") from exc

        # pylint: disable=c-extension-no-member
        program = jq.compile(jq_filter)
        results = program.input(parsed).all()
        out_lines: List[str] = []
        for item in results:
            if isinstance(item, (dict, list)):
                out_lines.append(json.dumps(item, ensure_ascii=False))
            else:
                out_lines.append(str(item))
        return ("\n".join(out_lines) + ("\n" if out_lines else ""), "", 0)

    def _normalize_shell_path(self, path: str) -> str:
        raw = (path or ".").strip()
        if raw == ".":
            return "/scratch"
        if raw.startswith("/"):
            return "/" + raw.strip().lstrip("/")
        return f"/scratch/{raw}".replace("//", "/")

    def _enforce_fs_permission(self, policy: Dict[str, Any], operation: str, virtual_path: str) -> None:
        """Enforce filesystem allow/deny rules for an operation on a virtual path."""
        perms = policy.get("permissions") or {}
        fs = perms.get("filesystem") or {}
        filesystem_defaults = self._sandbox_permissions_defaults.get("filesystem", {})
        deny = fs.get("deny") or filesystem_defaults.get("deny") or list(_DEFAULT_FS_DENY)
        read_allow = fs.get("read") or filesystem_defaults.get("read") or list(_DEFAULT_FS_READ)
        write_allow = fs.get("write") or filesystem_defaults.get("write") or list(_DEFAULT_FS_WRITE)

        normalized = "/" + virtual_path.strip().lstrip("/")

        if self._matches_any_pattern(normalized, deny):
            raise CodeExecutionSecurityError(f"EACCES: {operation} denied for path: {normalized}")

        allowed = read_allow if operation == "read" else write_allow
        if not self._matches_any_pattern(normalized, allowed):
            raise CodeExecutionSecurityError(f"EACCES: {operation} denied for path: {normalized}")

    def _enforce_tool_call_permission(self, policy: Dict[str, Any], session: CodeExecutionSession, tool_name: str) -> None:
        """Enforce tool allow/deny policy for __toolcall__ bridges."""
        perms = policy.get("permissions") or {}
        network = perms.get("network") or {}
        if network.get("allow_tool_calls", self._default_allow_tool_calls) is False:
            raise CodeExecutionSecurityError("EACCES: tool calls are disabled by policy")

        tools_policy = perms.get("tools") or {}
        allow_patterns = tools_policy.get("allow") or []
        deny_patterns = tools_policy.get("deny") or []

        meta = session.mounted_tools.get(tool_name) or {}
        server_slug = str(meta.get("server_slug") or "local")
        stub_basename = str(meta.get("stub_basename") or "")
        if not stub_basename:
            stub_basename = tool_name

        candidate = f"{server_slug}/{stub_basename}"
        if deny_patterns and self._matches_any_pattern(candidate, deny_patterns):
            raise CodeExecutionSecurityError(f"EACCES: tool '{candidate}' is denied by policy")
        if allow_patterns and not self._matches_any_pattern(candidate, allow_patterns):
            raise CodeExecutionSecurityError(f"EACCES: tool '{candidate}' is not allowed by policy")

    def _matches_any_pattern(self, value: str, patterns: Sequence[str]) -> bool:
        for pattern in patterns or []:
            if fnmatch.fnmatch(value, pattern):
                return True
            if pattern.endswith("/**") and value == pattern[: -len("/**")]:
                return True
        return False

    def _build_python_tools_namespace(self, session: CodeExecutionSession, bridge: Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]) -> Any:
        groups: Dict[str, Dict[str, str]] = defaultdict(dict)
        for tool_name, meta in session.mounted_tools.items():
            server_slug = meta.get("server_slug", "tools")
            py_server = self._python_identifier(server_slug)
            py_tool = str(meta.get("python_tool_alias") or self._python_identifier(meta.get("stub_basename", tool_name)))
            groups[py_server][py_tool] = tool_name

        class ToolGroup:
            def __init__(self, mapping: Dict[str, str]) -> None:
                self._mapping = mapping

            def __getattr__(self, item: str) -> Any:
                if item not in self._mapping:
                    raise AttributeError(item)
                resolved_tool = self._mapping[item]

                async def _invoke(args: Optional[Dict[str, Any]] = None) -> Any:
                    return await bridge(resolved_tool, args)

                return _invoke

        class ToolNamespace:
            pass

        namespace = ToolNamespace()
        for server_slug, mapping in groups.items():
            setattr(namespace, server_slug, ToolGroup(mapping))
        return namespace

    def _tool_result_to_python_obj(self, result: "ToolResult") -> Any:
        payload: Dict[str, Any]
        if hasattr(result, "model_dump"):
            payload = result.model_dump(by_alias=True, mode="json")
        elif isinstance(result, dict):
            payload = result
        else:
            return str(result)

        if payload.get("structuredContent") is not None:
            return payload.get("structuredContent")
        if payload.get("structured_content") is not None:
            return payload.get("structured_content")

        contents = payload.get("content") or []
        if not contents:
            return {}
        texts: List[str] = []
        for item in contents:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    texts.append(text)
            else:
                text = getattr(item, "text", None)
                if text:
                    texts.append(str(text))
        merged = "\n".join(texts).strip()
        if not merged:
            return {}
        try:
            return json.loads(merged)
        except Exception:
            return {"text": merged}

    def _tool_server_slug(self, tool: DbTool) -> str:
        gateway = getattr(tool, "gateway", None)
        if gateway:
            slug = getattr(gateway, "slug", None) or slugify(getattr(gateway, "name", "gateway"))
            return slugify(slug)
        return "local"

    def _tool_file_name(self, tool: DbTool) -> str:
        value = getattr(tool, "custom_name_slug", None) or getattr(tool, "original_name", None) or tool.name
        return slugify(value).replace("-", "_")

    def _python_identifier(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        if not normalized:
            normalized = "x"
        if normalized[0].isdigit():
            normalized = f"_{normalized}"
        return normalized

    def _generate_typescript_stub(self, tool: DbTool, server_slug: str) -> str:
        function_name = self._python_identifier(self._tool_file_name(tool))
        if self._is_rust_acceleration_available() and rust_json_schema_to_stubs is not None:
            with contextlib.suppress(Exception):
                schema_json = json.dumps(tool.input_schema or {"type": "object"})
                payload = rust_json_schema_to_stubs(schema_json, server_slug, function_name, tool.description or "")
                parsed = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(parsed, dict):
                    stub = parsed.get("typescript")
                    if isinstance(stub, str) and stub.strip():
                        return stub

        args_type = self._schema_to_typescript_type(tool.input_schema or {"type": "object"})
        description = (tool.description or "").strip().replace("*/", "* /")
        return (
            "// Auto-generated by MCP Gateway code execution mode. Do not edit.\n"
            f"// Server: {server_slug}\n\n"
            "import { type ToolResult } from \"/tools/_runtime.ts\";\n\n"
            "/**\n"
            f" * {description}\n"
            f" * @server {server_slug}\n"
            " */\n"
            f"export async function {function_name}(args: {args_type}): Promise<ToolResult<any>> {{\n"
            f"  return __toolcall__(\"{server_slug}\", \"{function_name}\", args);\n"
            "}\n"
        )

    def _generate_python_stub(self, tool: DbTool, server_slug: str) -> str:
        function_name = self._python_identifier(self._tool_file_name(tool))
        if self._is_rust_acceleration_available() and rust_json_schema_to_stubs is not None:
            with contextlib.suppress(Exception):
                schema_json = json.dumps(tool.input_schema or {"type": "object"})
                payload = rust_json_schema_to_stubs(schema_json, server_slug, function_name, tool.description or "")
                parsed = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(parsed, dict):
                    stub = parsed.get("python")
                    if isinstance(stub, str) and stub.strip():
                        return stub

        args_type = self._schema_to_python_type(tool.input_schema or {"type": "object"})
        description = (tool.description or "").strip().replace('"""', r"\"\"\"")
        return (
            "# Auto-generated by MCP Gateway code execution mode. Do not edit.\n"
            f"# Server: {server_slug}\n\n"
            "from __future__ import annotations\n"
            "from typing import Any, Dict, List, Literal\n"
            "from tools._runtime import toolcall\n\n"
            f"async def {function_name}(args: {args_type}) -> Any:\n"
            f"    \"\"\"{description}\"\"\"\n"
            f"    return await toolcall(\"{server_slug}\", \"{function_name}\", args)\n"
        )

    def _schema_to_typescript_type(self, schema: Dict[str, Any]) -> str:
        schema_type = schema.get("type")
        if schema.get("enum"):
            options = [json.dumps(v) for v in schema.get("enum", [])]
            return " | ".join(options) if options else "any"
        if schema_type == "string":
            return "string"
        if schema_type == "integer" or schema_type == "number":
            return "number"
        if schema_type == "boolean":
            return "boolean"
        if schema_type == "array":
            return f"{self._schema_to_typescript_type(schema.get('items') or {})}[]"
        if schema_type == "object":
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            if not props:
                return "Record<string, any>"
            fields = []
            for key, prop in props.items():
                ts_type = self._schema_to_typescript_type(prop or {})
                optional = "" if key in required else "?"
                fields.append(f"{key}{optional}: {ts_type};")
            return "{ " + " ".join(fields) + " }"
        return "any"

    def _schema_to_python_type(self, schema: Dict[str, Any]) -> str:
        schema_type = schema.get("type")
        if schema.get("enum"):
            values = [repr(v) for v in schema.get("enum", [])]
            return "Literal[" + ", ".join(values) + "]" if values else "Any"
        if schema_type == "string":
            return "str"
        if schema_type == "integer":
            return "int"
        if schema_type == "number":
            return "float"
        if schema_type == "boolean":
            return "bool"
        if schema_type == "array":
            return f"List[{self._schema_to_python_type(schema.get('items') or {})}]"
        if schema_type == "object":
            return "Dict[str, Any]"
        return "Any"

    def _write_runtime_helpers(self, tools_dir: Path) -> None:
        (tools_dir / "_runtime.ts").write_text(
            "// Auto-generated runtime helper for code-execution stubs.\n"
            "export type ToolResult<T = any> = Promise<T>;\n"
            "declare function __toolcall__(serverName: string, toolName: string, args: Record<string, any>): Promise<any>;\n",
            encoding="utf-8",
        )
        (tools_dir / "_runtime.py").write_text(
            "# Auto-generated runtime helper for code-execution stubs.\n"
            "from __future__ import annotations\n"
            "from typing import Any, Dict\n\n"
            "async def toolcall(server_name: str, tool_name: str, args: Dict[str, Any]) -> Any:\n"
            "    return await __toolcall__(server_name, tool_name, args)\n",
            encoding="utf-8",
        )

    def _build_search_index(self, tools_dir: Path) -> None:
        index_lines: List[str] = []
        for file_path in tools_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue
            rel = file_path.relative_to(tools_dir)
            index_lines.append(f"{rel}:{content.replace(os.linesep, ' ')}")
        (tools_dir / ".search_index").write_text("\n".join(index_lines), encoding="utf-8")

    def _looks_like_shell_command(self, code: str) -> bool:
        stripped = code.strip()
        if "\n" in stripped:
            return False
        python_markers = ("def ", "class ", "import ", "from ", "await ", "return ", "for ", "while ", "if ")
        ts_markers = ("const ", "let ", "function ", "=>", "import ", "export ", "await ")
        if stripped.startswith(python_markers) or stripped.startswith(ts_markers):
            return False
        # Single-line command-like input.
        return bool(re.match(r"^[A-Za-z0-9_./-]+\s?.*$", stripped))

    def _enforce_disk_limits(self, session: CodeExecutionSession, policy: Dict[str, Any]) -> None:
        max_file_bytes = int(policy.get("max_file_size_mb", self._sandbox_limit_defaults["max_file_size_mb"])) * 1024 * 1024
        max_total_bytes = int(policy.get("max_total_disk_mb", self._sandbox_limit_defaults["max_total_disk_mb"])) * 1024 * 1024
        total_bytes = 0
        for root in (session.scratch_dir, session.results_dir):
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if size > max_file_bytes:
                    raise CodeExecutionSecurityError(f"EACCES: file size limit exceeded at {self._real_to_virtual_path(session, path)}")
                total_bytes += size
                if total_bytes > max_total_bytes:
                    raise CodeExecutionSecurityError("EACCES: total disk usage limit exceeded")

    def _emit_security_event(
        self,
        user_email: Optional[str],
        description: str,
        request_headers: Optional[Dict[str, str]],
        threat_indicators: Dict[str, Any],
    ) -> None:
        client_ip = "unknown"
        if request_headers:
            client_ip = request_headers.get("x-forwarded-for") or request_headers.get("x-real-ip") or "unknown"
        with contextlib.suppress(Exception):
            security_logger.log_suspicious_activity(
                activity_type="code_execution_policy_violation",
                description=description,
                user_id=user_email,
                user_email=user_email,
                client_ip=client_ip,
                user_agent=request_headers.get("user-agent") if request_headers else None,
                threat_score=0.8,
                severity=SecuritySeverity.HIGH,
                threat_indicators=threat_indicators,
                action_taken="blocked",
            )

    def _virtual_to_real_path(self, session: CodeExecutionSession, virtual_path: str) -> Optional[Path]:
        normalized = "/" + virtual_path.strip().lstrip("/")
        mapping = {
            "/tools": session.tools_dir,
            "/scratch": session.scratch_dir,
            "/skills": session.skills_dir,
            "/results": session.results_dir,
        }
        for root, real_root in mapping.items():
            if normalized == root:
                return real_root
            if normalized.startswith(root + "/"):
                suffix = normalized[len(root) + 1 :]
                resolved = (real_root / suffix).resolve()
                if str(resolved).startswith(str(real_root.resolve())):
                    return resolved
                return None
        return None

    def _real_to_virtual_path(self, session: CodeExecutionSession, real_path: Path) -> str:
        candidates = (
            (session.tools_dir.resolve(), "/tools"),
            (session.scratch_dir.resolve(), "/scratch"),
            (session.skills_dir.resolve(), "/skills"),
            (session.results_dir.resolve(), "/results"),
        )
        resolved = real_path.resolve()
        for root, virtual in candidates:
            with contextlib.suppress(ValueError):
                rel = resolved.relative_to(root)
                return f"{virtual}/{rel.as_posix()}" if rel.as_posix() != "." else virtual
        return resolved.as_posix()

    def _read_virtual_text_file(self, session: CodeExecutionSession, virtual_path: str) -> str:
        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None or not real_path.exists() or not real_path.is_file():
            raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_path}")
        return real_path.read_text(encoding="utf-8")

    def _write_virtual_text_file(self, session: CodeExecutionSession, virtual_path: str, content: str) -> None:
        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise CodeExecutionSecurityError(f"EACCES: write denied for path: {virtual_path}")
        allowed_roots = (session.scratch_dir.resolve(), session.results_dir.resolve())
        resolved = real_path.resolve()
        if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
            raise CodeExecutionSecurityError(f"EACCES: write denied for path: {virtual_path}")
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")

    def _list_virtual_dir(self, session: CodeExecutionSession, virtual_path: str) -> List[str]:
        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None or not real_path.exists() or not real_path.is_dir():
            raise CodeExecutionSecurityError(f"EACCES: read denied for path: {virtual_path}")
        return sorted(child.name for child in real_path.iterdir())

    async def _destroy_session(self, session: CodeExecutionSession) -> None:
        with contextlib.suppress(Exception):
            await self._deno_runtime.destroy_session(session)
        with contextlib.suppress(Exception):
            await self._python_runtime.destroy_session(session)
        shutil.rmtree(session.root_dir, ignore_errors=True)

    def _wipe_and_recreate_directory(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)

    def _percentile(self, values: Iterable[int], percentile: int) -> float:
        sorted_vals = sorted(values)
        if not sorted_vals:
            return 0.0
        if len(sorted_vals) == 1:
            return float(sorted_vals[0])
        rank = (percentile / 100) * (len(sorted_vals) - 1)
        low = int(rank)
        high = min(low + 1, len(sorted_vals) - 1)
        weight = rank - low
        return (1 - weight) * sorted_vals[low] + weight * sorted_vals[high]


code_execution_service = CodeExecutionService()
