# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/vfs_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Virtual Tool Filesystem (VFS) service.

Provides a browsable, read/write virtual filesystem that exposes mounted MCP tools
as generated stubs in configurable formats (Python, TypeScript, or MCP JSON).

Meta-tools:
- fs_browse: list virtual directory contents
- fs_read:   read a file from the virtual filesystem
- fs_write:  write a file to writable directories (/scratch, /results)
"""

# Future
from __future__ import annotations

# Standard
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_slug import slugify

try:
    # First-Party
    from plugins_rust import json_schema_to_stubs as rust_json_schema_to_stubs

    _RUST_VFS_AVAILABLE = True
except ImportError:
    rust_json_schema_to_stubs = None
    _RUST_VFS_AVAILABLE = False


logger = LoggingService().get_logger(__name__)

VFS_SERVER_TYPE = "vfs"
META_TOOL_FS_BROWSE = "fs_browse"
META_TOOL_FS_READ = "fs_read"
META_TOOL_FS_WRITE = "fs_write"
VFS_META_TOOLS = (META_TOOL_FS_BROWSE, META_TOOL_FS_READ, META_TOOL_FS_WRITE)
VFS_SCHEMA_VERSION = "2026-02-19"

_DEFAULT_VFS_BASE_DIR = str(Path(tempfile.gettempdir()) / "mcpgateway_vfs")
_DEFAULT_FS_READ = ("/tools/**", "/scratch/**", "/results/**")
_DEFAULT_FS_WRITE = ("/scratch/**", "/results/**")
_DEFAULT_FS_DENY = ("/etc/**", "/proc/**", "/sys/**")


class VfsError(Exception):
    """General VFS operation error."""


class VfsSecurityError(VfsError):
    """VFS security violation (path traversal, permission denied)."""


def _is_path_within(child: Path, parent: Path) -> bool:
    """Return True if *child* is equal to or inside *parent* (symlink-safe)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@dataclass
class VfsSession:
    """In-memory VFS session state."""

    session_id: str
    server_id: str
    user_email: str
    stub_format: str  # "python", "typescript", or "json"
    root_dir: Path
    tools_dir: Path
    scratch_dir: Path
    results_dir: Path
    mounted_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    content_hash: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def all_dirs(self) -> Tuple[Path, Path, Path]:
        """Return primary virtual directories."""
        return (self.tools_dir, self.scratch_dir, self.results_dir)


class VfsService:
    """Service implementing the Virtual Tool Filesystem.

    Exposes mounted MCP tools as browsable files in Python, TypeScript, or
    JSON format. Provides fs_browse, fs_read, and fs_write meta-tools.
    """

    def __init__(self) -> None:
        """Initialize VFS service from gateway settings."""
        configured_base_dir = str(getattr(settings, "vfs_base_dir", "") or "").strip()
        self._base_dir = Path(configured_base_dir or _DEFAULT_VFS_BASE_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._default_ttl = int(getattr(settings, "vfs_session_ttl_seconds", 900))
        self._fs_browse_enabled = bool(getattr(settings, "vfs_fs_browse_enabled", True))
        self._fs_read_enabled = bool(getattr(settings, "vfs_fs_read_enabled", True))
        self._fs_write_enabled = bool(getattr(settings, "vfs_fs_write_enabled", True))
        self._fs_read_max_size_bytes = int(getattr(settings, "vfs_fs_read_max_size_bytes", 1048576))
        self._fs_browse_default_max_entries = int(getattr(settings, "vfs_fs_browse_default_max_entries", 200))
        self._fs_browse_max_entries = int(getattr(settings, "vfs_fs_browse_max_entries", 1000))
        self._default_stub_format = str(getattr(settings, "vfs_default_stub_format", "json"))
        self._rust_acceleration_enabled = _RUST_VFS_AVAILABLE

        self._sessions: Dict[Tuple[str, str], VfsSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _deterministic_session_id(self, server_id: str, user_email: str) -> str:
        """Generate a deterministic session ID from server + user."""
        raw = f"{server_id}:{user_email}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    async def get_or_create_session(
        self,
        db: Session,
        server: DbServer,
        user_email: str,
        token_teams: Optional[List[str]] = None,
    ) -> VfsSession:
        """Get an existing VFS session or create a new one."""
        stub_format = getattr(server, "stub_format", None) or self._default_stub_format
        if stub_format not in {"python", "typescript", "json"}:
            stub_format = self._default_stub_format

        key = (server.id, user_email)
        session = self._sessions.get(key)
        if session is not None:
            session.last_used_at = datetime.now(tz=timezone.utc)
            await self._refresh_virtual_filesystem_if_needed(db=db, session=session, server=server, token_teams=token_teams)
            return session

        session_id = self._deterministic_session_id(server.id, user_email)
        root_dir = self._base_dir / session_id
        root_dir.mkdir(parents=True, exist_ok=True)

        session = VfsSession(
            session_id=session_id,
            server_id=server.id,
            user_email=user_email,
            stub_format=stub_format,
            root_dir=root_dir,
            tools_dir=root_dir / "tools",
            scratch_dir=root_dir / "scratch",
            results_dir=root_dir / "results",
        )

        for d in session.all_dirs:
            d.mkdir(parents=True, exist_ok=True)

        await self._refresh_virtual_filesystem_if_needed(db=db, session=session, server=server, token_teams=token_teams)
        self._sessions[key] = session
        return session

    # ------------------------------------------------------------------
    # Meta-tools
    # ------------------------------------------------------------------

    def get_meta_tools(self, server: DbServer) -> List[Dict[str, Any]]:  # noqa: ARG002  # pylint: disable=unused-argument
        """Return the list of VFS meta-tool definitions for a server."""
        browse_tool = {
            "name": META_TOOL_FS_BROWSE,
            "description": "Browse the virtual tool filesystem. Lists files and directories under /tools (read-only tool stubs), /scratch (read-write workspace), and /results (outputs).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Virtual path to browse (e.g. '/', '/tools', '/scratch'). Defaults to '/'."},
                    "include_hidden": {"type": "boolean", "description": "Include hidden (dot) files", "default": False},
                    "max_entries": {
                        "type": "integer",
                        "description": f"Max entries (default {self._fs_browse_default_max_entries}, max {self._fs_browse_max_entries})",
                        "default": self._fs_browse_default_max_entries,
                    },
                },
            },
        }
        read_tool = {
            "name": META_TOOL_FS_READ,
            "description": "Read a file from the virtual filesystem. Returns file content as text with metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Virtual path to read (e.g. '/tools/server_name/tool_name.py')"},
                },
                "required": ["path"],
            },
        }
        write_tool = {
            "name": META_TOOL_FS_WRITE,
            "description": "Write a file to a writable virtual directory (/scratch or /results).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Virtual path to write (must be under /scratch or /results)"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        }

        tools = []
        if self._fs_browse_enabled:
            tools.append(browse_tool)
        if self._fs_read_enabled:
            tools.append(read_tool)
        if self._fs_write_enabled:
            tools.append(write_tool)
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
        """Browse virtual filesystem for a VFS server."""
        if not self._fs_browse_enabled:
            raise VfsError("fs_browse meta-tool is disabled by configuration")

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

        session = await self.get_or_create_session(db=db, server=server, user_email=user_email or "anonymous", token_teams=token_teams)
        virtual_path = path or "/"

        normalized_vpath = "/" + virtual_path.strip().lstrip("/")
        if normalized_vpath == "/":
            vfs_roots = [
                ("/tools", "read-only tool stubs (browsable metadata)", session.tools_dir),
                ("/scratch", "read-write temporary workspace", session.scratch_dir),
                ("/results", "read-write outputs", session.results_dir),
            ]
            entries: List[Dict[str, Any]] = []
            for vroot, description, real_root in vfs_roots:
                entry: Dict[str, Any] = {
                    "name": vroot.lstrip("/"),
                    "path": vroot,
                    "type": "directory",
                    "description": description,
                }
                if real_root.exists():
                    entry["size_bytes"] = sum(1 for _ in real_root.iterdir() if not _.name.startswith("."))
                entries.append(entry)
            return {"path": "/", "entries": entries, "truncated": False}

        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise VfsSecurityError(f"Path '{virtual_path}' is outside the virtual filesystem")

        self._enforce_fs_permission("read", virtual_path)

        if not real_path.exists():
            raise VfsError(f"Path not found: {virtual_path}")

        entries = []
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

        return {"path": virtual_path, "entries": entries, "truncated": len(entries) >= max_entries_value}

    async def fs_read(
        self,
        db: Session,
        server: DbServer,
        path: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Read a file from the virtual filesystem."""
        if not self._fs_read_enabled:
            raise VfsError("fs_read meta-tool is disabled by configuration")
        if not path or not path.strip():
            raise VfsError("path is required")

        session = await self.get_or_create_session(db=db, server=server, user_email=user_email or "anonymous", token_teams=token_teams)
        virtual_path = path.strip()

        self._enforce_fs_permission("read", virtual_path)

        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise VfsSecurityError(f"Path '{virtual_path}' is outside the virtual filesystem")
        if not real_path.exists():
            raise VfsError(f"Path not found: {virtual_path}")
        if not real_path.is_file():
            raise VfsError(f"Path is a directory, not a file: {virtual_path}. Use fs_browse to list directories.")

        stat = real_path.stat()
        if stat.st_size > self._fs_read_max_size_bytes:
            raise VfsError(f"File too large ({stat.st_size} bytes, limit {self._fs_read_max_size_bytes}).")

        content = real_path.read_text(encoding="utf-8")
        return {
            "path": virtual_path,
            "content": content,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    async def fs_write(
        self,
        db: Session,
        server: DbServer,
        path: str,
        content: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Write a file to the virtual filesystem (only /scratch and /results)."""
        if not self._fs_write_enabled:
            raise VfsError("fs_write meta-tool is disabled by configuration")
        if not path or not path.strip():
            raise VfsError("path is required")
        if content is None:
            raise VfsError("content is required")

        session = await self.get_or_create_session(db=db, server=server, user_email=user_email or "anonymous", token_teams=token_teams)
        virtual_path = path.strip()

        self._enforce_fs_permission("write", virtual_path)

        real_path = self._virtual_to_real_path(session, virtual_path)
        if real_path is None:
            raise VfsSecurityError(f"Path '{virtual_path}' is outside the virtual filesystem")

        allowed_roots = (session.scratch_dir.resolve(), session.results_dir.resolve())
        resolved = real_path.resolve()
        if not any(_is_path_within(resolved, root) for root in allowed_roots):
            raise VfsSecurityError(f"EACCES: write denied for path: {virtual_path}. Only /scratch and /results are writable.")

        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")

        stat = real_path.stat()
        return {
            "path": virtual_path,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Virtual filesystem refresh
    # ------------------------------------------------------------------

    async def _refresh_virtual_filesystem_if_needed(
        self,
        db: Session,
        session: VfsSession,
        server: DbServer,
        token_teams: Optional[List[str]],
    ) -> None:
        """Regenerate mounted tool stubs if source content changed."""
        mounted = self._resolve_mounted_tools(db=db, server=server, user_email=session.user_email, token_teams=token_teams)
        digest_src = [f"{tool.id}:{tool.updated_at.isoformat() if getattr(tool, 'updated_at', None) else ''}:{tool.name}" for tool in mounted]
        digest = hashlib.sha256("\n".join(sorted(digest_src)).encode("utf-8")).hexdigest()
        if session.content_hash == digest and session.generated_at:
            return

        session.mounted_tools = {}
        self._wipe_and_recreate_directory(session.tools_dir)
        (session.tools_dir / "_schema.json").write_text(
            json.dumps({"version": VFS_SCHEMA_VERSION, "roots": ["/tools", "/scratch", "/results"], "stub_format": session.stub_format}, indent=2),
            encoding="utf-8",
        )

        grouped: Dict[str, List[DbTool]] = {}
        catalog_tools: List[Dict[str, Any]] = []
        for tool in mounted:
            server_slug = self._tool_server_slug(tool)
            stub_basename = self._tool_file_name(tool)

            if server_slug not in grouped:
                grouped[server_slug] = []
            grouped[server_slug].append(tool)

            session.mounted_tools[tool.name] = {
                "tool_id": tool.id,
                "tool_name": tool.name,
                "server_slug": server_slug,
                "stub_basename": stub_basename,
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
                    "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                }
            )

        for server_slug, tools in grouped.items():
            server_dir = session.tools_dir / server_slug
            server_dir.mkdir(parents=True, exist_ok=True)
            meta_payload = {
                "server": server_slug,
                "tool_count": len(tools),
                "generated_at": utc_now().isoformat(),
            }
            (server_dir / "_meta.json").write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
            for tool in tools:
                base_name = self._tool_file_name(tool)
                if session.stub_format == "typescript":
                    stub = self._generate_typescript_stub(tool=tool, server_slug=server_slug)
                    (server_dir / f"{base_name}.ts").write_text(stub, encoding="utf-8")
                elif session.stub_format == "python":
                    stub = self._generate_python_stub(tool=tool, server_slug=server_slug)
                    (server_dir / f"{base_name}.py").write_text(stub, encoding="utf-8")
                else:
                    schema = self._generate_json_schema(tool=tool, server_slug=server_slug)
                    (server_dir / f"{base_name}.json").write_text(schema, encoding="utf-8")

        if catalog_tools:
            self._write_catalog_json(session.tools_dir, catalog_tools)

        self._build_search_index(session.tools_dir)
        session.content_hash = digest
        session.generated_at = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # Stub generation
    # ------------------------------------------------------------------

    def _generate_python_stub(self, tool: DbTool, server_slug: str) -> str:
        """Generate a Python type-annotated stub for a tool."""
        function_name = self._python_identifier(self._tool_file_name(tool))
        if self._rust_acceleration_enabled and rust_json_schema_to_stubs is not None:
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
            "# Auto-generated by MCP Gateway VFS. Do not edit.\n"
            f"# Server: {server_slug}\n\n"
            "from __future__ import annotations\n"
            "from typing import Any, Dict, List, Literal\n\n"
            f"async def {function_name}(args: {args_type}) -> Any:\n"
            f'    """{description}"""\n'
            "    ...\n"
        )

    def _generate_typescript_stub(self, tool: DbTool, server_slug: str) -> str:
        """Generate a TypeScript interface stub for a tool."""
        function_name = self._python_identifier(self._tool_file_name(tool))
        if self._rust_acceleration_enabled and rust_json_schema_to_stubs is not None:
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
            "// Auto-generated by MCP Gateway VFS. Do not edit.\n"
            f"// Server: {server_slug}\n\n"
            "/**\n"
            f" * {description}\n"
            f" * @server {server_slug}\n"
            " */\n"
            f"export async function {function_name}(args: {args_type}): Promise<any> {{\n"
            "  // stub: invoke via MCP tool call\n"
            "}\n"
        )

    def _generate_json_schema(self, tool: DbTool, server_slug: str) -> str:
        """Generate raw MCP JSON tool schema."""
        return json.dumps(
            {
                "name": tool.name,
                "original_name": getattr(tool, "original_name", None),
                "server": server_slug,
                "description": tool.description or "",
                "inputSchema": tool.input_schema or {"type": "object", "properties": {}},
            },
            indent=2,
        )

    # ------------------------------------------------------------------
    # Type mapping helpers
    # ------------------------------------------------------------------

    def _schema_to_python_type(self, schema: Dict[str, Any]) -> str:
        """Map JSON Schema fragments to Python typing annotations."""
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

    def _schema_to_typescript_type(self, schema: Dict[str, Any]) -> str:
        """Map JSON Schema fragments to TypeScript type expressions."""
        schema_type = schema.get("type")
        if schema.get("enum"):
            options = [json.dumps(v) for v in schema.get("enum", [])]
            return " | ".join(options) if options else "any"
        if schema_type == "string":
            return "string"
        if schema_type in {"integer", "number"}:
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

    # ------------------------------------------------------------------
    # Path mapping
    # ------------------------------------------------------------------

    def _virtual_to_real_path(self, session: VfsSession, virtual_path: str) -> Optional[Path]:
        """Resolve a virtual path into a session-scoped real filesystem path."""
        normalized = "/" + virtual_path.strip().lstrip("/")
        mapping = {
            "/tools": session.tools_dir,
            "/scratch": session.scratch_dir,
            "/results": session.results_dir,
        }
        for root, real_root in mapping.items():
            if normalized == root:
                return real_root
            if normalized.startswith(root + "/"):
                suffix = normalized[len(root) + 1 :]
                resolved = (real_root / suffix).resolve()
                real_root_resolved = real_root.resolve()
                try:
                    resolved.relative_to(real_root_resolved)
                except ValueError:
                    return None
                return resolved
        return None

    def _real_to_virtual_path(self, session: VfsSession, real_path: Path) -> str:
        """Convert a real path under session roots back into virtual notation."""
        candidates = (
            (session.tools_dir.resolve(), "/tools"),
            (session.scratch_dir.resolve(), "/scratch"),
            (session.results_dir.resolve(), "/results"),
        )
        resolved = real_path.resolve()
        for root, virtual in candidates:
            with contextlib.suppress(ValueError):
                rel = resolved.relative_to(root)
                return f"{virtual}/{rel.as_posix()}" if rel.as_posix() != "." else virtual
        return resolved.as_posix()

    # ------------------------------------------------------------------
    # Tool resolution and mounting
    # ------------------------------------------------------------------

    def _resolve_mounted_tools(
        self,
        db: Session,
        server: DbServer,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> List[DbTool]:
        """Resolve all reachable tools visible to the current scope."""
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

    def _tool_visible_for_scope(self, tool: DbTool, user_email: Optional[str], token_teams: Optional[List[str]]) -> bool:
        """Return whether a tool is visible under token-team scoping rules."""
        if token_teams is None:
            return True
        if len(token_teams) == 0:
            return tool.visibility == "public"
        if tool.visibility == "public":
            return True
        if user_email and tool.owner_email == user_email:
            return True
        return tool.team_id in token_teams and tool.visibility in {"team", "public"}

    def _tool_matches_mount_rules(self, tool: DbTool, mount_rules: Dict[str, Any]) -> bool:
        """Evaluate include/exclude mount rules against a candidate tool."""
        raw_tags = tool.tags or []
        tags = set(t if isinstance(t, str) else t.get("name", str(t)) for t in raw_tags)
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
        """Normalize server mount-rules payload to a plain dict."""
        raw = getattr(server, "mount_rules", None) or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            return {}
        return dict(raw)

    # ------------------------------------------------------------------
    # Filesystem permissions
    # ------------------------------------------------------------------

    def _enforce_fs_permission(self, operation: str, virtual_path: str) -> None:
        """Enforce filesystem allow/deny rules for a virtual path."""
        deny = list(_DEFAULT_FS_DENY)
        read_allow = list(_DEFAULT_FS_READ)
        write_allow = list(_DEFAULT_FS_WRITE)

        normalized = "/" + virtual_path.strip().lstrip("/")

        if self._matches_any_pattern(normalized, deny):
            raise VfsSecurityError(f"EACCES: {operation} denied for path: {normalized}")

        allowed = read_allow if operation == "read" else write_allow
        if not self._matches_any_pattern(normalized, allowed):
            raise VfsSecurityError(f"EACCES: {operation} denied for path: {normalized}")

    def _matches_any_pattern(self, value: str, patterns: Sequence[str]) -> bool:
        """Return True when a value matches any configured glob pattern."""
        for pattern in patterns or []:
            if fnmatch.fnmatch(value, pattern):
                return True
            if pattern.endswith("/**") and value == pattern[: -len("/**")]:
                return True
        return False

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    def _tool_server_slug(self, tool: DbTool) -> str:
        """Return a stable server slug for a mounted tool."""
        gateway = getattr(tool, "gateway", None)
        if gateway:
            slug = getattr(gateway, "slug", None) or slugify(getattr(gateway, "name", "gateway"))
            return slugify(slug)
        return "local"

    def _tool_file_name(self, tool: DbTool) -> str:
        """Return a deterministic filesystem-safe base filename for a tool."""
        value = getattr(tool, "custom_name_slug", None) or getattr(tool, "original_name", None) or tool.name
        return slugify(value).replace("-", "_")

    def _python_identifier(self, value: str) -> str:
        """Convert arbitrary strings into valid Python identifiers."""
        normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        if not normalized:
            normalized = "x"
        if normalized[0].isdigit():
            normalized = f"_{normalized}"
        return normalized

    # ------------------------------------------------------------------
    # Filesystem utilities
    # ------------------------------------------------------------------

    def _wipe_and_recreate_directory(self, path: Path) -> None:
        """Recreate a directory from scratch, discarding previous contents."""
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)

    def _write_catalog_json(self, tools_dir: Path, catalog_tools: List[Dict[str, Any]]) -> None:
        """Write a _catalog.json index of all mounted tools."""
        (tools_dir / "_catalog.json").write_text(
            json.dumps({"version": VFS_SCHEMA_VERSION, "tool_count": len(catalog_tools), "tools": catalog_tools}, indent=2),
            encoding="utf-8",
        )

    def _build_search_index(self, tools_dir: Path) -> None:
        """Build a simple text index for fast tool-search operations."""
        index_lines: List[str] = []
        for file_path in tools_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                content = ""
            if not content:
                continue
            rel = file_path.relative_to(tools_dir)
            index_lines.append(f"{rel}:{content.replace(os.linesep, ' ')}")
        (tools_dir / ".search_index").write_text("\n".join(index_lines), encoding="utf-8")
