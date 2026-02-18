# -*- coding: utf-8 -*-
"""Unit tests for code execution service."""

# Standard
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

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
    TokenizationContext,
    ToolCallRecord,
    _coerce_string_list,
    _is_path_within,
    _MAX_REGEX_LENGTH,
)


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


def test_build_meta_tools_respects_feature_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_shell_exec_enabled", False, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_default_max_entries", 25, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_max_entries", 40, raising=False)

    svc = CodeExecutionService()
    tools = svc.build_meta_tools("server-1")

    assert [tool["name"] for tool in tools] == ["fs_browse"]
    max_entries_schema = tools[0]["input_schema"]["properties"]["max_entries"]
    assert max_entries_schema["default"] == 25
    assert max_entries_schema["maximum"] == 40


def test_server_policy_defaults_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_runtime", "python", raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_max_execution_time_ms", 15000, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_max_runs_per_minute", 9, raising=False)
    monkeypatch.setattr(
        "mcpgateway.services.code_execution_service.settings.code_execution_default_filesystem_read_paths",
        ["/tools/**", "/custom/**"],
        raising=False,
    )
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_allow_tool_calls", False, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_allow_raw_http", True, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_tokenization_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_tokenization_types", ["email"], raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_default_tokenization_strategy", "bidirectional", raising=False)

    svc = CodeExecutionService()
    server = SimpleNamespace(sandbox_policy=None, tokenization=None)

    policy = svc._server_sandbox_policy(server)
    tokenization = svc._server_tokenization_policy(server)

    assert policy["runtime"] == "python"
    assert policy["max_execution_time_ms"] == 15000
    assert policy["max_runs_per_minute"] == 9
    assert policy["permissions"]["filesystem"]["read"] == ["/tools/**", "/custom/**"]
    assert policy["permissions"]["network"]["allow_tool_calls"] is False
    assert policy["permissions"]["network"]["allow_raw_http"] is True
    assert tokenization["enabled"] is True
    assert tokenization["types"] == ["email"]
    assert tokenization["strategy"] == "bidirectional"


def test_validate_code_safety_uses_configured_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_python_dangerous_patterns", [r"dangerous_py\("], raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_typescript_dangerous_patterns", [r"dangerous_ts\("], raising=False)

    svc = CodeExecutionService()
    svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]

    with pytest.raises(CodeExecutionSecurityError):
        svc._validate_code_safety(code="dangerous_py()", language="python", allow_raw_http=False, user_email=None, request_headers=None)

    with pytest.raises(CodeExecutionSecurityError):
        svc._validate_code_safety(code="dangerous_ts()", language="typescript", allow_raw_http=False, user_email=None, request_headers=None)


@pytest.mark.asyncio
async def test_fs_browse_clamps_max_entries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_default_max_entries", 2, raising=False)
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_fs_browse_max_entries", 3, raising=False)

    svc = CodeExecutionService()
    session = _make_session(tmp_path)
    for index in range(6):
        (session.tools_dir / f"file-{index}.txt").write_text("x\n", encoding="utf-8")

    async def _fake_get_or_create_session(**_kwargs: Any) -> CodeExecutionSession:
        return session

    svc._get_or_create_session = _fake_get_or_create_session  # type: ignore[method-assign]
    result = await svc.fs_browse(
        db=SimpleNamespace(),
        server=SimpleNamespace(stub_language="python"),
        path="/tools",
        include_hidden=False,
        max_entries=999,
        user_email="user@example.com",
        token_teams=None,
    )

    assert len(result["entries"]) == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_replay_disabled_by_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcpgateway.services.code_execution_service.settings.code_execution_replay_enabled", False, raising=False)
    svc = CodeExecutionService()

    with pytest.raises(CodeExecutionError, match="Replay is disabled"):
        await svc.replay_run(
            db=SimpleNamespace(),
            run_id="run-1",
            user_email="user@example.com",
            token_teams=None,
            request_headers=None,
            invoke_tool=AsyncMock(),
        )


def test_internal_shell_subset_supports_ls_cat_grep_and_jq(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    session = _make_session(tmp_path)

    reports_dir = session.tools_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "csv_tool.txt").write_text("csv spreadsheet helper\n", encoding="utf-8")
    (session.tools_dir / "catalog.json").write_text(
        orjson.dumps({"tools": [{"name": "csv_tool", "tag": "csv"}, {"name": "other", "tag": "misc"}]}).decode("utf-8"),
        encoding="utf-8",
    )

    out_ls, err_ls, code_ls = svc._execute_shell_pipeline_sync(session, "ls /tools/reports", _policy())
    assert code_ls == 0
    assert err_ls == ""
    assert "csv_tool.txt" in out_ls

    out_cat, err_cat, code_cat = svc._execute_shell_pipeline_sync(session, "cat /tools/reports/csv_tool.txt", _policy())
    assert code_cat == 0
    assert err_cat == ""
    assert "spreadsheet" in out_cat

    out_grep, err_grep, code_grep = svc._execute_shell_pipeline_sync(
        session,
        "grep -r 'csv|spreadsheet' /tools --include='*.txt' -l",
        _policy(),
    )
    assert code_grep == 0
    assert err_grep == ""
    assert "/tools/reports/csv_tool.txt" in out_grep

    out_jq, err_jq, code_jq = svc._execute_shell_pipeline_sync(
        session,
        "cat /tools/catalog.json | jq '.tools[] | select(.tag == \"csv\") | .name'",
        _policy(),
    )
    assert code_jq == 0
    assert err_jq == ""
    assert "csv_tool" in out_jq


def test_internal_shell_blocks_etc_passwd_access(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    session = _make_session(tmp_path)

    out, err, code = svc._execute_shell_pipeline_sync(session, "cat /etc/passwd", _policy())

    assert out == ""
    assert code == 126
    assert "EACCES" in err


def test_stub_generation_uses_server_tool_signature() -> None:
    svc = CodeExecutionService()
    tool = SimpleNamespace(
        name="get_document",
        description="Retrieve a document",
        input_schema={"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"]},
        custom_name_slug=None,
        original_name=None,
    )

    ts_stub = svc._generate_typescript_stub(tool=tool, server_slug="google-drive")
    py_stub = svc._generate_python_stub(tool=tool, server_slug="google-drive")

    assert '__toolcall__("google-drive", "get_document", args)' in ts_stub
    assert 'toolcall("google-drive", "get_document", args)' in py_stub


@pytest.mark.asyncio
async def test_runtime_tool_bridge_applies_detokenize_and_tokenize(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    session = _make_session(tmp_path)

    mounted_tool = "gateway_sep_get_document"
    session.mounted_tools[mounted_tool] = {
        "server_slug": "google-drive",
        "stub_basename": "get_document",
    }
    session.runtime_tool_index[("google_drive", "get_document")] = mounted_tool

    session.tokenization.enabled = True
    session.tokenization.token_types = ("email",)
    session.tokenization.value_to_token["alice@example.com"] = "TKN_EMAIL_000001"
    session.tokenization.token_to_value["TKN_EMAIL_000001"] = "alice@example.com"

    captured: Dict[str, Any] = {}

    async def _invoke_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        captured["name"] = name
        captured["args"] = args
        return {"structuredContent": {"email": "alice@example.com"}}

    policy = _policy()
    policy["permissions"]["tools"]["allow"] = ["google-drive/get_document"]

    result = await svc._invoke_mounted_tool(
        session=session,
        policy=policy,
        server_name="google_drive",
        tool_name="get_document",
        args={"email": "TKN_EMAIL_000001"},
        invoke_tool=_invoke_tool,
        request_headers={},
        user_email="user@example.com",
        security_events=[],
    )

    assert captured["name"] == mounted_tool
    assert captured["args"]["email"] == "alice@example.com"
    assert result["email"].startswith("TKN_EMAIL_")
    assert len(session.tool_calls) == 1
    assert session.tool_calls[0].success is True


@pytest.mark.asyncio
async def test_runtime_tool_bridge_enforces_deny_policies(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    svc._emit_security_event = lambda **_: None  # type: ignore[method-assign]
    session = _make_session(tmp_path)

    mounted_tool = "gateway_sep_get_document"
    session.mounted_tools[mounted_tool] = {
        "server_slug": "google-drive",
        "stub_basename": "get_document",
    }
    session.runtime_tool_index[("google_drive", "get_document")] = mounted_tool

    async def _invoke_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        _ = name, args
        return {"structuredContent": {"ok": True}}

    policy = _policy()
    policy["permissions"]["tools"]["deny"] = ["google-drive/get_document"]
    events: List[Dict[str, Any]] = []

    with pytest.raises(CodeExecutionSecurityError):
        await svc._invoke_mounted_tool(
            session=session,
            policy=policy,
            server_name="google_drive",
            tool_name="get_document",
            args={},
            invoke_tool=_invoke_tool,
            request_headers={},
            user_email="user@example.com",
            security_events=events,
        )

    assert any(event.get("event") == "tool_call_blocked" for event in events)


@pytest.mark.asyncio
async def test_list_active_sessions_filters_by_server(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    now = datetime.now(timezone.utc)

    session_a = _make_session(tmp_path / "a", language="python")
    session_a.session_id = "session-a"
    session_a.server_id = "server-a"
    session_a.created_at = now
    session_a.last_used_at = now
    session_a.mounted_tools["tool_one"] = {}
    (session_a.skills_dir / "skill_one.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    session_b = _make_session(tmp_path / "b", language="typescript")
    session_b.session_id = "session-b"
    session_b.server_id = "server-b"
    session_b.user_email = "other@example.com"
    session_b.created_at = now
    session_b.last_used_at = now

    svc._sessions[(session_a.server_id, session_a.user_email, session_a.language)] = session_a
    svc._sessions[(session_b.server_id, session_b.user_email, session_b.language)] = session_b

    sessions = await svc.list_active_sessions(server_id="server-a")

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-a"
    assert sessions[0]["server_id"] == "server-a"
    assert sessions[0]["tool_count"] == 1
    assert sessions[0]["skill_count"] == 1


class _ScalarResult:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> List[Any]:
        return self._rows


class _FakeDb:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def execute(self, _query: Any) -> _ScalarResult:
        return _ScalarResult(self._rows)


class _ScalarVersionResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "_ScalarVersionResult":
        return self

    def first(self) -> Any:
        return self._value


class _FakeSkillDb:
    def __init__(self, current_version: Any = None, objects: Optional[Dict[str, Any]] = None) -> None:
        self.current_version = current_version
        self.objects = objects or {}
        self.added: List[Any] = []

    def execute(self, _query: Any) -> _ScalarVersionResult:
        return _ScalarVersionResult(self.current_version)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def get(self, _model: Any, key: str) -> Any:
        return self.objects.get(key)


def test_skills_mount_uses_latest_approved_version_and_scope(tmp_path: Path) -> None:
    svc = CodeExecutionService()
    now = datetime.now(timezone.utc)
    skills = [
        SimpleNamespace(
            id="s1v1",
            server_id="server-1",
            name="enrich_data",
            version=1,
            language="python",
            status="approved",
            is_active=True,
            team_id="team-1",
            owner_email="user@example.com",
            source_code="def run():\n    return 1\n",
            updated_at=now,
        ),
        SimpleNamespace(
            id="s1v2",
            server_id="server-1",
            name="enrich_data",
            version=2,
            language="python",
            status="approved",
            is_active=True,
            team_id="team-1",
            owner_email="user@example.com",
            source_code="def run():\n    return 2\n",
            updated_at=now,
        ),
        SimpleNamespace(
            id="s2",
            server_id="server-1",
            name="ops_secret",
            version=1,
            language="python",
            status="approved",
            is_active=True,
            team_id="team-2",
            owner_email="other@example.com",
            source_code="def run():\n    return 99\n",
            updated_at=now,
        ),
    ]
    db = _FakeDb(skills)
    server = SimpleNamespace(id="server-1", skills_scope="team:team-1")

    mounted = svc._resolve_mounted_skills(
        db=db,
        server=server,
        user_email="user@example.com",
        token_teams=["team-1"],
        language="python",
    )

    assert len(mounted) == 1
    assert mounted[0].id == "s1v2"

    session = _make_session(tmp_path, language="python")
    svc._mount_skills(session=session, skills=mounted)

    assert (session.skills_dir / "__init__.py").exists()
    skill_file = session.skills_dir / "enrich_data.py"
    assert skill_file.exists()
    assert "return 2" in skill_file.read_text(encoding="utf-8")

    meta = orjson.loads((session.skills_dir / "_meta.json").read_bytes())
    assert meta["skill_count"] == 1
    assert meta["skills"][0]["name"] == "enrich_data"


@pytest.mark.asyncio
async def test_skill_create_and_approval_lifecycle() -> None:
    svc = CodeExecutionService()
    server = SimpleNamespace(id="server-1", skills_require_approval=True, team_id="team-1")
    db = _FakeSkillDb(current_version=None)

    skill = await svc.create_skill(
        db=db,  # type: ignore[arg-type]
        server=server,
        name="sanitize",
        source_code="def sanitize(v):\n    return v\n",
        language="python",
        description="sanitize input",
        owner_email="user@example.com",
        created_by="user@example.com",
    )
    assert skill.status == "pending"
    assert any(getattr(item, "status", "") == "pending" for item in db.added)

    if not getattr(skill, "id", None):
        skill.id = "skill-1"
    approval = next(item for item in db.added if hasattr(item, "skill_id"))
    if not getattr(approval, "id", None):
        approval.id = "approval-1"
    approval.skill_id = skill.id
    db.objects = {approval.id: approval, skill.id: skill}

    approved = await svc.approve_skill(  # type: ignore[arg-type]
        db=db,
        approval_id=approval.id,
        reviewer_email="admin@example.com",
        approve=True,
        reason="looks good",
    )
    assert approved.status == "approved"
    assert skill.status == "approved"
    assert skill.approved_by == "admin@example.com"

    revoked = await svc.revoke_skill(  # type: ignore[arg-type]
        db=db,
        skill_id=skill.id,
        reviewer_email="admin@example.com",
        reason="retired",
    )
    assert revoked.status == "revoked"
    assert revoked.is_active is False
