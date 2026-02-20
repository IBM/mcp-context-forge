# -*- coding: utf-8 -*-
"""Tests for mcpgateway.services.vfs_service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from mcpgateway.services.vfs_service import (
    META_TOOL_FS_BROWSE,
    META_TOOL_FS_READ,
    META_TOOL_FS_WRITE,
    VFS_META_TOOLS,
    VFS_SCHEMA_VERSION,
    VFS_SERVER_TYPE,
    VfsError,
    VfsSecurityError,
    VfsService,
    VfsSession,
    _is_path_within,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_tool(
    tool_id: str = "t1",
    name: str = "my_tool",
    original_name: str = "my_tool",
    description: str = "A test tool",
    input_schema: Optional[Dict[str, Any]] = None,
    tags: Optional[List] = None,
    gateway_name: str = "demo_gw",
    gateway_slug: str = "demo_gw",
    visibility: str = "public",
    owner_email: Optional[str] = None,
    team_id: Optional[str] = None,
    enabled: bool = True,
    reachable: bool = True,
    custom_name_slug: Optional[str] = None,
) -> SimpleNamespace:
    """Build a lightweight tool-like object accepted by VfsService internals."""
    gw = SimpleNamespace(id="gw1", name=gateway_name, slug=gateway_slug)
    return SimpleNamespace(
        id=tool_id,
        name=name,
        original_name=original_name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        tags=tags or [],
        gateway=gw,
        visibility=visibility,
        owner_email=owner_email,
        team_id=team_id,
        enabled=enabled,
        reachable=reachable,
        updated_at=datetime(2026, 2, 19, tzinfo=timezone.utc),
        custom_name_slug=custom_name_slug,
    )


def _make_server(
    server_id: str = "srv1",
    server_type: str = "vfs",
    stub_format: Optional[str] = None,
    mount_rules: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """Build a lightweight server-like object."""
    return SimpleNamespace(
        id=server_id,
        server_type=server_type,
        stub_format=stub_format,
        mount_rules=mount_rules,
    )


def _stub_db(tools: Optional[List] = None):
    """Return a mock DB session that yields the given tools from select()."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = tools or []
    return db


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def vfs(tmp_path):
    """Create a VfsService rooted in a temp dir."""
    with patch("mcpgateway.services.vfs_service.settings") as mock_settings:
        mock_settings.vfs_base_dir = str(tmp_path / "vfs")
        mock_settings.vfs_session_ttl_seconds = 900
        mock_settings.vfs_fs_browse_enabled = True
        mock_settings.vfs_fs_read_enabled = True
        mock_settings.vfs_fs_write_enabled = True
        mock_settings.vfs_fs_read_max_size_bytes = 1048576
        mock_settings.vfs_fs_browse_default_max_entries = 200
        mock_settings.vfs_fs_browse_max_entries = 1000
        mock_settings.vfs_default_stub_format = "json"
        service = VfsService()
    return service


@pytest.fixture()
def server():
    return _make_server()


@pytest.fixture()
def tool():
    return _make_tool()


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
class TestConstants:
    def test_vfs_server_type(self):
        assert VFS_SERVER_TYPE == "vfs"

    def test_meta_tool_names(self):
        assert META_TOOL_FS_BROWSE == "fs_browse"
        assert META_TOOL_FS_READ == "fs_read"
        assert META_TOOL_FS_WRITE == "fs_write"

    def test_meta_tools_tuple(self):
        assert VFS_META_TOOLS == ("fs_browse", "fs_read", "fs_write")

    def test_schema_version(self):
        assert VFS_SCHEMA_VERSION == "2026-02-19"


# --------------------------------------------------------------------------- #
# _is_path_within
# --------------------------------------------------------------------------- #
class TestIsPathWithin:
    def test_same_dir(self, tmp_path):
        assert _is_path_within(tmp_path, tmp_path) is True

    def test_child(self, tmp_path):
        child = tmp_path / "sub" / "file.txt"
        child.parent.mkdir(parents=True)
        child.touch()
        assert _is_path_within(child, tmp_path) is True

    def test_outside(self, tmp_path):
        other = tmp_path.parent / "elsewhere"
        assert _is_path_within(other, tmp_path) is False


# --------------------------------------------------------------------------- #
# VfsSession
# --------------------------------------------------------------------------- #
class TestVfsSession:
    def test_all_dirs(self, tmp_path):
        session = VfsSession(
            session_id="s1",
            server_id="srv1",
            user_email="u@e.com",
            stub_format="json",
            root_dir=tmp_path,
            tools_dir=tmp_path / "tools",
            scratch_dir=tmp_path / "scratch",
            results_dir=tmp_path / "results",
        )
        assert session.all_dirs == (tmp_path / "tools", tmp_path / "scratch", tmp_path / "results")

    def test_default_fields(self, tmp_path):
        session = VfsSession(
            session_id="s1",
            server_id="srv1",
            user_email="u@e.com",
            stub_format="json",
            root_dir=tmp_path,
            tools_dir=tmp_path / "tools",
            scratch_dir=tmp_path / "scratch",
            results_dir=tmp_path / "results",
        )
        assert session.mounted_tools == {}
        assert session.content_hash is None
        assert session.generated_at is None


# --------------------------------------------------------------------------- #
# get_meta_tools
# --------------------------------------------------------------------------- #
class TestGetMetaTools:
    def test_all_enabled(self, vfs, server):
        tools = vfs.get_meta_tools(server)
        names = [t["name"] for t in tools]
        assert names == ["fs_browse", "fs_read", "fs_write"]

    def test_browse_disabled(self, vfs, server):
        vfs._fs_browse_enabled = False
        tools = vfs.get_meta_tools(server)
        names = [t["name"] for t in tools]
        assert "fs_browse" not in names
        assert "fs_read" in names
        assert "fs_write" in names

    def test_read_disabled(self, vfs, server):
        vfs._fs_read_enabled = False
        tools = vfs.get_meta_tools(server)
        names = [t["name"] for t in tools]
        assert "fs_read" not in names

    def test_write_disabled(self, vfs, server):
        vfs._fs_write_enabled = False
        tools = vfs.get_meta_tools(server)
        names = [t["name"] for t in tools]
        assert "fs_write" not in names

    def test_all_disabled(self, vfs, server):
        vfs._fs_browse_enabled = False
        vfs._fs_read_enabled = False
        vfs._fs_write_enabled = False
        assert vfs.get_meta_tools(server) == []

    def test_schema_shape(self, vfs, server):
        tools = vfs.get_meta_tools(server)
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
            assert isinstance(t["inputSchema"], dict)


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #
class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_deterministic_session_id(self, vfs):
        sid1 = vfs._deterministic_session_id("srv1", "u@e.com")
        sid2 = vfs._deterministic_session_id("srv1", "u@e.com")
        assert sid1 == sid2
        assert len(sid1) == 24

    @pytest.mark.asyncio
    async def test_different_users_different_ids(self, vfs):
        sid1 = vfs._deterministic_session_id("srv1", "alice@e.com")
        sid2 = vfs._deterministic_session_id("srv1", "bob@e.com")
        assert sid1 != sid2

    @pytest.mark.asyncio
    async def test_get_or_create_creates_dirs(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        assert session.tools_dir.exists()
        assert session.scratch_dir.exists()
        assert session.results_dir.exists()

    @pytest.mark.asyncio
    async def test_get_or_create_returns_same(self, vfs, server):
        db = _stub_db()
        s1 = await vfs.get_or_create_session(db, server, "u@e.com")
        s2 = await vfs.get_or_create_session(db, server, "u@e.com")
        assert s1 is s2

    @pytest.mark.asyncio
    async def test_session_respects_stub_format(self, vfs):
        srv = _make_server(stub_format="typescript")
        db = _stub_db()
        session = await vfs.get_or_create_session(db, srv, "u@e.com")
        assert session.stub_format == "typescript"

    @pytest.mark.asyncio
    async def test_session_falls_back_to_default_format(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        assert session.stub_format == "json"

    @pytest.mark.asyncio
    async def test_invalid_stub_format_falls_back(self, vfs):
        srv = _make_server(stub_format="invalid_format")
        db = _stub_db()
        session = await vfs.get_or_create_session(db, srv, "u@e.com")
        assert session.stub_format == "json"


# --------------------------------------------------------------------------- #
# fs_browse
# --------------------------------------------------------------------------- #
class TestFsBrowse:
    @pytest.mark.asyncio
    async def test_browse_root(self, vfs, server):
        db = _stub_db()
        result = await vfs.fs_browse(db, server, "/", False, None, "u@e.com", None)
        assert result["path"] == "/"
        entries = result["entries"]
        names = {e["name"] for e in entries}
        assert names == {"tools", "scratch", "results"}

    @pytest.mark.asyncio
    async def test_browse_tools_empty(self, vfs, server):
        db = _stub_db()
        result = await vfs.fs_browse(db, server, "/tools", False, None, "u@e.com", None)
        # With no tools, /tools should have only meta files (_schema.json)
        assert result["path"] == "/tools"
        assert isinstance(result["entries"], list)

    @pytest.mark.asyncio
    async def test_browse_with_tool_generates_stubs(self, vfs, server):
        db = _stub_db([_make_tool()])
        result = await vfs.fs_browse(db, server, "/tools", False, None, "u@e.com", None)
        # Should contain at least the gateway directory and/or meta files
        assert len(result["entries"]) > 0

    @pytest.mark.asyncio
    async def test_browse_nonexistent_path(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsError, match="Path not found"):
            await vfs.fs_browse(db, server, "/tools/nonexistent", False, None, "u@e.com", None)

    @pytest.mark.asyncio
    async def test_browse_outside_vfs_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError):
            await vfs.fs_browse(db, server, "/etc/passwd", False, None, "u@e.com", None)

    @pytest.mark.asyncio
    async def test_browse_disabled(self, vfs, server):
        vfs._fs_browse_enabled = False
        db = _stub_db()
        with pytest.raises(VfsError, match="disabled"):
            await vfs.fs_browse(db, server, "/", False, None, "u@e.com", None)

    @pytest.mark.asyncio
    async def test_browse_max_entries_limit(self, vfs, server):
        db = _stub_db()
        # Create a session with some files in scratch
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        for i in range(10):
            (session.scratch_dir / f"file{i}.txt").write_text(f"content {i}")
        result = await vfs.fs_browse(db, server, "/scratch", False, 3, "u@e.com", None)
        assert len(result["entries"]) == 3
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_browse_hidden_files_excluded(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        (session.scratch_dir / ".hidden").write_text("secret")
        (session.scratch_dir / "visible.txt").write_text("ok")
        result = await vfs.fs_browse(db, server, "/scratch", False, None, "u@e.com", None)
        names = {e["name"] for e in result["entries"]}
        assert ".hidden" not in names
        assert "visible.txt" in names

    @pytest.mark.asyncio
    async def test_browse_hidden_files_included(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        (session.scratch_dir / ".hidden").write_text("secret")
        (session.scratch_dir / "visible.txt").write_text("ok")
        result = await vfs.fs_browse(db, server, "/scratch", True, None, "u@e.com", None)
        names = {e["name"] for e in result["entries"]}
        assert ".hidden" in names

    @pytest.mark.asyncio
    async def test_browse_file_path(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        (session.scratch_dir / "test.txt").write_text("hello")
        result = await vfs.fs_browse(db, server, "/scratch/test.txt", False, None, "u@e.com", None)
        assert len(result["entries"]) == 1
        assert result["entries"][0]["type"] == "file"

    @pytest.mark.asyncio
    async def test_browse_max_entries_bool_ignored(self, vfs, server):
        """Bool max_entries should fall back to default."""
        db = _stub_db()
        result = await vfs.fs_browse(db, server, "/", False, True, "u@e.com", None)
        assert isinstance(result["entries"], list)

    @pytest.mark.asyncio
    async def test_browse_max_entries_string_ignored(self, vfs, server):
        """Non-numeric max_entries should fall back to default."""
        db = _stub_db()
        result = await vfs.fs_browse(db, server, "/", False, "invalid", "u@e.com", None)
        assert isinstance(result["entries"], list)


# --------------------------------------------------------------------------- #
# fs_read
# --------------------------------------------------------------------------- #
class TestFsRead:
    @pytest.mark.asyncio
    async def test_read_scratch_file(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        (session.scratch_dir / "hello.txt").write_text("Hello, VFS!")
        result = await vfs.fs_read(db, server, "/scratch/hello.txt", "u@e.com", None)
        assert result["content"] == "Hello, VFS!"
        assert result["path"] == "/scratch/hello.txt"
        assert "size_bytes" in result
        assert "modified_at" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsError, match="Path not found"):
            await vfs.fs_read(db, server, "/scratch/nope.txt", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_directory(self, vfs, server):
        db = _stub_db()
        await vfs.get_or_create_session(db, server, "u@e.com")
        with pytest.raises(VfsError, match="directory"):
            await vfs.fs_read(db, server, "/scratch", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_empty_path(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsError, match="path is required"):
            await vfs.fs_read(db, server, "", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_outside_vfs_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError):
            await vfs.fs_read(db, server, "/etc/passwd", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_disabled(self, vfs, server):
        vfs._fs_read_enabled = False
        db = _stub_db()
        with pytest.raises(VfsError, match="disabled"):
            await vfs.fs_read(db, server, "/scratch/file.txt", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_tool_stub_json(self, vfs, server):
        """After stub generation, we should be able to read a tool stub."""
        tool = _make_tool(name="list_users", original_name="list_users")
        db = _stub_db([tool])
        await vfs.get_or_create_session(db, server, "u@e.com")
        # Browse to find generated stubs
        browse_result = await vfs.fs_browse(db, server, "/tools", False, None, "u@e.com", None)
        # There should be a server directory
        dirs = [e for e in browse_result["entries"] if e["type"] == "directory"]
        assert len(dirs) > 0

    @pytest.mark.asyncio
    async def test_read_file_too_large(self, vfs, server):
        vfs._fs_read_max_size_bytes = 10  # Very small limit
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        (session.scratch_dir / "big.txt").write_text("x" * 100)
        with pytest.raises(VfsError, match="too large"):
            await vfs.fs_read(db, server, "/scratch/big.txt", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_read_traversal_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError):
            await vfs.fs_read(db, server, "/scratch/../../etc/passwd", "u@e.com", None)


# --------------------------------------------------------------------------- #
# fs_write
# --------------------------------------------------------------------------- #
class TestFsWrite:
    @pytest.mark.asyncio
    async def test_write_to_scratch(self, vfs, server):
        db = _stub_db()
        result = await vfs.fs_write(db, server, "/scratch/test.txt", "Hello!", "u@e.com", None)
        assert result["path"] == "/scratch/test.txt"
        assert result["size_bytes"] == 6

    @pytest.mark.asyncio
    async def test_write_to_results(self, vfs, server):
        db = _stub_db()
        result = await vfs.fs_write(db, server, "/results/output.json", '{"ok": true}', "u@e.com", None)
        assert result["path"] == "/results/output.json"

    @pytest.mark.asyncio
    async def test_write_to_tools_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError, match="write denied"):
            await vfs.fs_write(db, server, "/tools/evil.py", "bad", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_empty_path(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsError, match="path is required"):
            await vfs.fs_write(db, server, "", "content", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_none_content(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsError, match="content is required"):
            await vfs.fs_write(db, server, "/scratch/test.txt", None, "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_disabled(self, vfs, server):
        vfs._fs_write_enabled = False
        db = _stub_db()
        with pytest.raises(VfsError, match="disabled"):
            await vfs.fs_write(db, server, "/scratch/test.txt", "hi", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_outside_vfs_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError):
            await vfs.fs_write(db, server, "/etc/hack.txt", "pwned", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_traversal_denied(self, vfs, server):
        db = _stub_db()
        with pytest.raises(VfsSecurityError):
            await vfs.fs_write(db, server, "/scratch/../../etc/passwd", "pwned", "u@e.com", None)

    @pytest.mark.asyncio
    async def test_write_creates_subdirectories(self, vfs, server):
        db = _stub_db()
        result = await vfs.fs_write(db, server, "/scratch/a/b/c/file.txt", "nested", "u@e.com", None)
        assert result["path"] == "/scratch/a/b/c/file.txt"
        assert result["size_bytes"] == 6

    @pytest.mark.asyncio
    async def test_write_then_read(self, vfs, server):
        db = _stub_db()
        await vfs.fs_write(db, server, "/scratch/roundtrip.txt", "round trip!", "u@e.com", None)
        read_result = await vfs.fs_read(db, server, "/scratch/roundtrip.txt", "u@e.com", None)
        assert read_result["content"] == "round trip!"


# --------------------------------------------------------------------------- #
# Stub generation
# --------------------------------------------------------------------------- #
class TestStubGeneration:
    @pytest.mark.asyncio
    async def test_json_stub_format(self, vfs):
        srv = _make_server(stub_format="json")
        tool = _make_tool(name="test_tool", description="A test tool")
        db = _stub_db([tool])
        session = await vfs.get_or_create_session(db, srv, "u@e.com")
        # Find the json stub file
        json_files = list(session.tools_dir.rglob("*.json"))
        # Filter out meta files
        tool_stubs = [f for f in json_files if not f.name.startswith("_")]
        assert len(tool_stubs) >= 1
        content = json.loads(tool_stubs[0].read_text())
        assert "name" in content
        assert "inputSchema" in content

    @pytest.mark.asyncio
    async def test_python_stub_format(self, vfs):
        srv = _make_server(stub_format="python")
        tool = _make_tool(name="test_tool", description="A test tool")
        db = _stub_db([tool])
        session = await vfs.get_or_create_session(db, srv, "u@e.com")
        py_files = list(session.tools_dir.rglob("*.py"))
        assert len(py_files) >= 1
        content = py_files[0].read_text()
        assert "async def" in content
        assert "Auto-generated" in content

    @pytest.mark.asyncio
    async def test_typescript_stub_format(self, vfs):
        srv = _make_server(stub_format="typescript")
        tool = _make_tool(name="test_tool", description="A test tool")
        db = _stub_db([tool])
        session = await vfs.get_or_create_session(db, srv, "u@e.com")
        ts_files = list(session.tools_dir.rglob("*.ts"))
        assert len(ts_files) >= 1
        content = ts_files[0].read_text()
        assert "export async function" in content
        assert "Auto-generated" in content

    @pytest.mark.asyncio
    async def test_catalog_json_written(self, vfs, server):
        tool = _make_tool()
        db = _stub_db([tool])
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        catalog = session.tools_dir / "_catalog.json"
        assert catalog.exists()
        data = json.loads(catalog.read_text())
        assert data["tool_count"] == 1
        assert len(data["tools"]) == 1

    @pytest.mark.asyncio
    async def test_schema_json_written(self, vfs, server):
        db = _stub_db([_make_tool()])
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        schema = session.tools_dir / "_schema.json"
        assert schema.exists()
        data = json.loads(schema.read_text())
        assert data["version"] == VFS_SCHEMA_VERSION
        assert data["stub_format"] == "json"

    @pytest.mark.asyncio
    async def test_search_index_built(self, vfs, server):
        db = _stub_db([_make_tool()])
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        index = session.tools_dir / ".search_index"
        assert index.exists()

    @pytest.mark.asyncio
    async def test_content_hash_prevents_regeneration(self, vfs, server):
        tool = _make_tool()
        db = _stub_db([tool])
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        first_hash = session.content_hash
        first_gen = session.generated_at
        assert first_hash is not None
        # Get session again — should reuse without regeneration
        await vfs.get_or_create_session(db, server, "u@e.com")
        assert session.content_hash == first_hash
        assert session.generated_at == first_gen


# --------------------------------------------------------------------------- #
# Type mapping
# --------------------------------------------------------------------------- #
class TestTypeMapping:
    def test_python_string(self, vfs):
        assert vfs._schema_to_python_type({"type": "string"}) == "str"

    def test_python_integer(self, vfs):
        assert vfs._schema_to_python_type({"type": "integer"}) == "int"

    def test_python_number(self, vfs):
        assert vfs._schema_to_python_type({"type": "number"}) == "float"

    def test_python_boolean(self, vfs):
        assert vfs._schema_to_python_type({"type": "boolean"}) == "bool"

    def test_python_array(self, vfs):
        assert vfs._schema_to_python_type({"type": "array", "items": {"type": "string"}}) == "List[str]"

    def test_python_object(self, vfs):
        assert vfs._schema_to_python_type({"type": "object"}) == "Dict[str, Any]"

    def test_python_enum(self, vfs):
        result = vfs._schema_to_python_type({"enum": ["a", "b"]})
        assert "Literal[" in result

    def test_python_unknown(self, vfs):
        assert vfs._schema_to_python_type({}) == "Any"

    def test_typescript_string(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "string"}) == "string"

    def test_typescript_number(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "number"}) == "number"

    def test_typescript_integer(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "integer"}) == "number"

    def test_typescript_boolean(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "boolean"}) == "boolean"

    def test_typescript_array(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "array", "items": {"type": "string"}}) == "string[]"

    def test_typescript_object_no_props(self, vfs):
        assert vfs._schema_to_typescript_type({"type": "object"}) == "Record<string, any>"

    def test_typescript_object_with_props(self, vfs):
        result = vfs._schema_to_typescript_type(
            {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}, "required": ["name"]}
        )
        assert "name: string" in result
        assert "age?: number" in result

    def test_typescript_enum(self, vfs):
        result = vfs._schema_to_typescript_type({"enum": ["a", "b"]})
        assert '"a"' in result
        assert '"b"' in result

    def test_typescript_unknown(self, vfs):
        assert vfs._schema_to_typescript_type({}) == "any"


# --------------------------------------------------------------------------- #
# Path mapping
# --------------------------------------------------------------------------- #
class TestPathMapping:
    @pytest.mark.asyncio
    async def test_virtual_to_real_tools(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        real = vfs._virtual_to_real_path(session, "/tools")
        assert real == session.tools_dir

    @pytest.mark.asyncio
    async def test_virtual_to_real_scratch_subpath(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        real = vfs._virtual_to_real_path(session, "/scratch/file.txt")
        assert str(real).endswith("file.txt")

    @pytest.mark.asyncio
    async def test_virtual_to_real_outside_returns_none(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        assert vfs._virtual_to_real_path(session, "/unknown/path") is None

    @pytest.mark.asyncio
    async def test_virtual_to_real_traversal_returns_none(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        result = vfs._virtual_to_real_path(session, "/scratch/../../etc/passwd")
        assert result is None

    @pytest.mark.asyncio
    async def test_real_to_virtual(self, vfs, server):
        db = _stub_db()
        session = await vfs.get_or_create_session(db, server, "u@e.com")
        real = session.tools_dir / "gateway" / "tool.json"
        virtual = vfs._real_to_virtual_path(session, real)
        assert virtual == "/tools/gateway/tool.json"


# --------------------------------------------------------------------------- #
# Mount rules
# --------------------------------------------------------------------------- #
class TestMountRules:
    def test_include_tags(self, vfs):
        tool = _make_tool(tags=[{"name": "math"}])
        assert vfs._tool_matches_mount_rules(tool, {"include_tags": ["math"]}) is True
        assert vfs._tool_matches_mount_rules(tool, {"include_tags": ["science"]}) is False

    def test_exclude_tags(self, vfs):
        tool = _make_tool(tags=[{"name": "deprecated"}])
        assert vfs._tool_matches_mount_rules(tool, {"exclude_tags": ["deprecated"]}) is False
        assert vfs._tool_matches_mount_rules(tool, {"exclude_tags": ["other"]}) is True

    def test_include_tools(self, vfs):
        tool = _make_tool(name="my_tool")
        assert vfs._tool_matches_mount_rules(tool, {"include_tools": ["my_tool"]}) is True
        assert vfs._tool_matches_mount_rules(tool, {"include_tools": ["other"]}) is False

    def test_exclude_tools(self, vfs):
        tool = _make_tool(name="my_tool")
        assert vfs._tool_matches_mount_rules(tool, {"exclude_tools": ["my_tool"]}) is False
        assert vfs._tool_matches_mount_rules(tool, {"exclude_tools": ["other"]}) is True

    def test_include_servers(self, vfs):
        tool = _make_tool(gateway_slug="demo_gw")
        # slugify converts underscores to dashes
        assert vfs._tool_matches_mount_rules(tool, {"include_servers": ["demo-gw"]}) is True
        assert vfs._tool_matches_mount_rules(tool, {"include_servers": ["other"]}) is False

    def test_exclude_servers(self, vfs):
        tool = _make_tool(gateway_slug="demo_gw")
        assert vfs._tool_matches_mount_rules(tool, {"exclude_servers": ["demo-gw"]}) is False
        assert vfs._tool_matches_mount_rules(tool, {"exclude_servers": ["other"]}) is True

    def test_empty_rules_match_all(self, vfs):
        tool = _make_tool()
        assert vfs._tool_matches_mount_rules(tool, {}) is True

    def test_server_mount_rules_normalizes(self, vfs):
        srv = _make_server(mount_rules={"include_tags": ["math"]})
        result = vfs._server_mount_rules(srv)
        assert result == {"include_tags": ["math"]}

    def test_server_mount_rules_none(self, vfs):
        srv = _make_server(mount_rules=None)
        result = vfs._server_mount_rules(srv)
        assert result == {}


# --------------------------------------------------------------------------- #
# Visibility scoping
# --------------------------------------------------------------------------- #
class TestVisibilityScoping:
    def test_no_teams_sees_all(self, vfs):
        tool = _make_tool(visibility="team", team_id="t1")
        assert vfs._tool_visible_for_scope(tool, None, None) is True

    def test_empty_teams_sees_public_only(self, vfs):
        public_tool = _make_tool(visibility="public")
        team_tool = _make_tool(visibility="team", team_id="t1")
        assert vfs._tool_visible_for_scope(public_tool, "u@e.com", []) is True
        assert vfs._tool_visible_for_scope(team_tool, "u@e.com", []) is False

    def test_team_member_sees_team_tools(self, vfs):
        tool = _make_tool(visibility="team", team_id="t1")
        assert vfs._tool_visible_for_scope(tool, "u@e.com", ["t1"]) is True
        assert vfs._tool_visible_for_scope(tool, "u@e.com", ["t2"]) is False

    def test_owner_sees_own_tools(self, vfs):
        tool = _make_tool(visibility="private", owner_email="u@e.com", team_id="t1")
        assert vfs._tool_visible_for_scope(tool, "u@e.com", ["t2"]) is True
        assert vfs._tool_visible_for_scope(tool, "other@e.com", ["t2"]) is False


# --------------------------------------------------------------------------- #
# Naming helpers
# --------------------------------------------------------------------------- #
class TestNamingHelpers:
    def test_tool_server_slug(self, vfs):
        tool = _make_tool(gateway_slug="my-gateway")
        result = vfs._tool_server_slug(tool)
        assert result == "my-gateway"

    def test_tool_server_slug_no_gateway(self, vfs):
        tool = _make_tool()
        tool.gateway = None
        assert vfs._tool_server_slug(tool) == "local"

    def test_tool_file_name(self, vfs):
        tool = _make_tool(name="my-fancy-tool")
        result = vfs._tool_file_name(tool)
        # Should be filesystem-safe (slugified with underscores)
        assert all(c.isalnum() or c == "_" for c in result)

    def test_python_identifier(self, vfs):
        assert vfs._python_identifier("my-tool") == "my_tool"
        assert vfs._python_identifier("123start") == "_123start"
        assert vfs._python_identifier("") == "x"

    def test_python_identifier_special_chars(self, vfs):
        result = vfs._python_identifier("tool@server#1")
        assert result.isidentifier()


# --------------------------------------------------------------------------- #
# Filesystem permissions
# --------------------------------------------------------------------------- #
class TestFsPermissions:
    def test_read_tools_allowed(self, vfs):
        vfs._enforce_fs_permission("read", "/tools/foo.py")

    def test_read_scratch_allowed(self, vfs):
        vfs._enforce_fs_permission("read", "/scratch/bar.txt")

    def test_read_results_allowed(self, vfs):
        vfs._enforce_fs_permission("read", "/results/output.json")

    def test_read_etc_denied(self, vfs):
        with pytest.raises(VfsSecurityError):
            vfs._enforce_fs_permission("read", "/etc/passwd")

    def test_write_scratch_allowed(self, vfs):
        vfs._enforce_fs_permission("write", "/scratch/test.txt")

    def test_write_results_allowed(self, vfs):
        vfs._enforce_fs_permission("write", "/results/out.json")

    def test_write_tools_denied(self, vfs):
        with pytest.raises(VfsSecurityError):
            vfs._enforce_fs_permission("write", "/tools/evil.py")

    def test_write_etc_denied(self, vfs):
        with pytest.raises(VfsSecurityError):
            vfs._enforce_fs_permission("write", "/etc/hack")


# --------------------------------------------------------------------------- #
# Filesystem utilities
# --------------------------------------------------------------------------- #
class TestFsUtilities:
    def test_wipe_and_recreate(self, vfs, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        (d / "file.txt").write_text("old")
        vfs._wipe_and_recreate_directory(d)
        assert d.exists()
        assert list(d.iterdir()) == []

    def test_matches_any_pattern(self, vfs):
        assert vfs._matches_any_pattern("/tools/foo.py", ["/tools/**"]) is True
        assert vfs._matches_any_pattern("/etc/passwd", ["/tools/**"]) is False
        # Direct root match
        assert vfs._matches_any_pattern("/tools", ["/tools/**"]) is True
