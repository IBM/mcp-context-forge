# -*- coding: utf-8 -*-
"""Minimal MCP Apps helpers.

This module centralizes MCP Apps metadata handling, capability advertising, and
AppBridge session management.
"""

# Standard
import base64
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Iterable, List, Optional
import uuid

# Third-Party
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import MCPAppSession as DbMCPAppSession

MCP_UI_EXTENSION = "io.modelcontextprotocol/ui"
MCP_UI_DEFAULT_VERSION = "2026-01-26"

_ALLOWED_CSP_DIRECTIVES = frozenset(
    {
        "connect-src",
        "default-src",
        "font-src",
        "frame-src",
        "img-src",
        "media-src",
        "baseUriDomains",
        "connectDomains",
        "frameDomains",
        "resourceDomains",
        "script-src",
        "style-src",
    }
)
_ALLOWED_SANDBOX_TOKENS = frozenset(
    {
        "allow-downloads",
        "allow-forms",
        "allow-modals",
        "allow-popups",
        "allow-scripts",
    }
)
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_APP_PERMISSION_KEYS = frozenset({"camera", "microphone", "geolocation", "clipboardWrite"})
_BLOCKED_SOURCE_PREFIXES = ("javascript:", "file:", "data:")


class MCPAppsValidationError(ValueError):
    """Raised when MCP Apps metadata is unsafe or malformed."""


def mcp_apps_enabled() -> bool:
    """Return whether MCP Apps support is enabled."""
    return bool(getattr(settings, "mcpgateway_mcp_apps_enabled", False))


def mcp_apps_capability() -> Dict[str, Any]:
    """Return the MCP Apps capability payload."""
    return {
        "version": MCP_UI_DEFAULT_VERSION,
        "resources": {"schemes": ["ui://"]},
        "bridge": {"methods": ["tools/call"]},
    }


def build_mcp_apps_capabilities(*, authorized: bool) -> Dict[str, Any]:
    """Build initialize-time MCP Apps capabilities for the current caller."""
    if not authorized or not mcp_apps_enabled():
        return {}
    return {MCP_UI_EXTENSION: mcp_apps_capability()}


def extension_metadata_value(value: Any) -> Dict[str, Any]:
    """Normalize nullable MCP Apps metadata to a dictionary."""
    return value if isinstance(value, dict) else {}


def optional_extension_metadata(value: Any) -> Optional[Dict[str, Any]]:
    """Return MCP Apps metadata when present, otherwise treat it as absent."""
    return value if isinstance(value, dict) else None


def mcp_ui_metadata(value: Any) -> Dict[str, Any]:
    """Return the MCP UI metadata block."""
    metadata = extension_metadata_value(value)
    ui = metadata.get(MCP_UI_EXTENSION)
    return ui if isinstance(ui, dict) else {}


def merge_mcp_protocol_meta(payload: Dict[str, Any]) -> None:
    """Translate MCP protocol ``_meta.ui`` into internal extension metadata.

    Upstream MCP servers advertise Apps metadata on protocol objects as
    ``_meta: {"ui": ...}``, while ContextForge stores extension state as
    ``extensionMetadata: {"io.modelcontextprotocol/ui": ...}``.
    """
    meta = payload.get("_meta")
    if not isinstance(meta, dict):
        return

    ui = meta.get("ui")
    if not isinstance(ui, dict) or not ui:
        return

    extension_metadata = payload.get("extensionMetadata") or payload.get("extension_metadata")
    if not isinstance(extension_metadata, dict):
        extension_metadata = {}
    else:
        extension_metadata = dict(extension_metadata)

    existing_ui = extension_metadata.get(MCP_UI_EXTENSION)
    merged_ui = dict(existing_ui) if isinstance(existing_ui, dict) else {}
    merged_ui.update(ui)
    extension_metadata[MCP_UI_EXTENSION] = merged_ui
    payload["extensionMetadata"] = extension_metadata


def _as_string_list(value: Any, *, field_name: str) -> List[str]:
    """Normalize a nullable string-or-list metadata value to a string list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise MCPAppsValidationError(f"{field_name} must be a string or list of strings")


def _validate_csp(csp: Any) -> None:
    """Validate the MCP Apps CSP metadata shape and unsafe source values."""
    if csp is None:
        return
    if not isinstance(csp, dict):
        raise MCPAppsValidationError("MCP Apps csp must be an object")
    for directive, values in csp.items():
        if directive not in _ALLOWED_CSP_DIRECTIVES:
            raise MCPAppsValidationError(f"Unsupported MCP Apps CSP directive: {directive}")
        for source in _as_string_list(values, field_name=f"csp.{directive}"):
            source_lower = source.lower()
            if source_lower == "*":
                raise MCPAppsValidationError("Wildcard CSP sources are not allowed for MCP Apps")
            if directive == "script-src" and source_lower in {"'unsafe-inline'", "'unsafe-eval'"}:
                raise MCPAppsValidationError(f"{source_lower} is not allowed for MCP Apps script-src")
            if source_lower.startswith(_BLOCKED_SOURCE_PREFIXES):
                raise MCPAppsValidationError(f"Blocked MCP Apps CSP source: {source}")


def _validate_sandbox(sandbox: Any) -> None:
    """Validate sandbox tokens accepted for MCP Apps UI resources."""
    for token in _as_string_list(sandbox, field_name="sandbox"):
        if token not in _ALLOWED_SANDBOX_TOKENS:
            raise MCPAppsValidationError(f"Unsupported MCP Apps sandbox token: {token}")


def _validate_permissions(permissions: Any) -> None:
    """Validate browser permission policy tokens for MCP Apps UI resources."""
    if isinstance(permissions, dict):
        for permission, value in permissions.items():
            if permission not in _APP_PERMISSION_KEYS or not isinstance(value, dict):
                raise MCPAppsValidationError(f"Unsupported MCP Apps permission: {permission}")
        return
    for permission in _as_string_list(permissions, field_name="permissions"):
        if not _PERMISSION_RE.match(permission):
            raise MCPAppsValidationError(f"Unsupported MCP Apps permission: {permission}")


def validate_extension_metadata(value: Optional[Dict[str, Any]]) -> None:
    """Validate stored MCP Apps metadata."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise MCPAppsValidationError("extensionMetadata must be an object")
    ui = mcp_ui_metadata(value)
    if not ui:
        return
    resource_uri = ui.get("resourceUri") or ui.get("resource_uri")
    if resource_uri is not None and (not isinstance(resource_uri, str) or not resource_uri.startswith("ui://")):
        raise MCPAppsValidationError("MCP Apps resourceUri must use the ui:// scheme")
    audience = ui.get("visibility", ui.get("audience"))
    if audience is not None:
        for item in _as_string_list(audience, field_name="visibility"):
            if item not in {"model", "app"}:
                raise MCPAppsValidationError("MCP Apps visibility entries must be 'model' or 'app'")
    _validate_csp(ui.get("csp"))
    _validate_sandbox(ui.get("sandbox"))
    _validate_permissions(ui.get("permissions"))


def validate_ui_resource(resource_uri: str, mime_type: Optional[str], extension_metadata: Optional[Dict[str, Any]]) -> None:
    """Validate an MCP Apps UI resource registration."""
    validate_extension_metadata(extension_metadata)
    if not resource_uri.startswith("ui://"):
        return
    if not mcp_apps_enabled():
        raise MCPAppsValidationError("MCP Apps UI resources are disabled")
    if not mime_type or mime_type.split(";", 1)[0].strip().lower() != "text/html":
        raise MCPAppsValidationError("ui:// resources must use text/html MIME type")
    ui = mcp_ui_metadata(extension_metadata)
    if not ui:
        raise MCPAppsValidationError("ui:// resources require MCP Apps metadata")
    csp = ui.get("csp")
    if not isinstance(csp, dict) or not csp:
        raise MCPAppsValidationError("ui:// resources require a non-empty MCP Apps CSP policy")
    sandbox = _as_string_list(ui.get("sandbox"), field_name="sandbox")
    if not sandbox:
        raise MCPAppsValidationError("ui:// resources require a non-empty MCP Apps sandbox policy")


def _protocol_ui_metadata(value: Any) -> Dict[str, Any]:
    """Return MCP protocol ``_meta.ui`` metadata when present."""
    metadata = extension_metadata_value(value)
    ui = metadata.get("ui")
    return ui if isinstance(ui, dict) else {}


def tool_audience(extension_metadata: Optional[Dict[str, Any]], protocol_meta: Any = None) -> List[str]:
    """Return normalized tool audience for MCP Apps filtering."""
    ui = mcp_ui_metadata(extension_metadata)
    if not ui:
        ui = _protocol_ui_metadata(protocol_meta)
    audience = ui.get("visibility", ui.get("audience"))
    if audience is None:
        return ["model"]
    return _as_string_list(audience, field_name="visibility")


def is_model_visible_tool(tool: Any) -> bool:
    """Return whether a tool should appear in model-facing tools/list."""
    extension_metadata = getattr(tool, "extension_metadata", None) if not isinstance(tool, dict) else tool.get("extensionMetadata") or tool.get("extension_metadata")
    protocol_meta = getattr(tool, "meta", None) if not isinstance(tool, dict) else tool.get("_meta") or tool.get("meta")
    return "model" in tool_audience(extension_metadata, protocol_meta)


def is_app_visible_tool(tool: Any) -> bool:
    """Return whether a tool can be invoked through AppBridge."""
    extension_metadata = getattr(tool, "extension_metadata", None) if not isinstance(tool, dict) else tool.get("extensionMetadata") or tool.get("extension_metadata")
    protocol_meta = getattr(tool, "meta", None) if not isinstance(tool, dict) else tool.get("_meta") or tool.get("meta")
    return "app" in tool_audience(extension_metadata, protocol_meta)


def filter_model_visible_tools(tools: Iterable[Any]) -> List[Any]:
    """Filter out app-only tools for model-facing list operations."""
    if not mcp_apps_enabled():
        return list(tools)
    return [tool for tool in tools if is_model_visible_tool(tool)]


def apply_tool_meta(payload: Dict[str, Any], extension_metadata: Optional[Dict[str, Any]]) -> None:
    """Project MCP Apps metadata into MCP tool descriptor _meta."""
    if not mcp_apps_enabled():
        return
    ui = mcp_ui_metadata(extension_metadata)
    resource_uri = ui.get("resourceUri") or ui.get("resource_uri")
    if not resource_uri:
        return
    meta = payload.setdefault("_meta", {})
    ui_meta = meta.setdefault("ui", {})
    ui_meta["resourceUri"] = resource_uri
    audience = ui.get("visibility", ui.get("audience"))
    if audience is not None:
        ui_meta["visibility"] = _as_string_list(audience, field_name="visibility")


def apply_resource_meta(payload: Dict[str, Any], extension_metadata: Optional[Dict[str, Any]]) -> None:
    """Project known UI resource metadata into MCP resource payload _meta."""
    if not mcp_apps_enabled():
        return
    ui = mcp_ui_metadata(extension_metadata)
    if not ui:
        return
    meta = payload.setdefault("_meta", {})
    meta["ui"] = {k: v for k, v in ui.items() if k in {"csp", "domain", "permissions", "prefersBorder", "sandbox"}}


def serialize_resource_content_for_mcp(content: Any, *, fallback_uri: Optional[str] = None) -> Dict[str, Any]:
    """Serialize internal resource content into an MCP ``resources/read`` content item."""
    # First-Party
    from mcpgateway.common.models import ResourceContent, ResourceContents  # pylint: disable=import-outside-toplevel

    if isinstance(content, ResourceContent):
        payload: Dict[str, Any] = {"uri": content.uri or fallback_uri}
        if content.mime_type:
            payload["mimeType"] = content.mime_type
        if content.text is not None:
            payload["text"] = content.text
        elif content.blob is not None:
            payload["blob"] = base64.b64encode(content.blob).decode("ascii")
        if content.meta:
            payload["_meta"] = content.meta
        return {key: value for key, value in payload.items() if value is not None}

    if isinstance(content, ResourceContents):
        return content.model_dump(by_alias=True, exclude_none=True)

    if isinstance(content, dict):
        payload = dict(content)
        if fallback_uri and "uri" not in payload:
            payload["uri"] = fallback_uri
        if "mime_type" in payload and "mimeType" not in payload:
            payload["mimeType"] = payload.pop("mime_type")
        if "meta" in payload and "_meta" not in payload:
            payload["_meta"] = payload.pop("meta")
        return {key: value for key, value in payload.items() if value is not None}

    uri = fallback_uri or getattr(content, "uri", None)
    mime_type_value = getattr(content, "mime_type", None) or getattr(content, "mimeType", None)
    mime_type = mime_type_value if isinstance(mime_type_value, str) else None
    meta_value = getattr(content, "meta", None)
    meta = meta_value if isinstance(meta_value, dict) else None
    text_value = getattr(content, "text", None)
    blob_value = getattr(content, "blob", None)
    has_text_payload = isinstance(text_value, str)
    has_blob_payload = isinstance(blob_value, (bytes, str))
    if has_text_payload or has_blob_payload or isinstance(content, (str, bytes)):
        payload = {"uri": uri}
        if mime_type:
            payload["mimeType"] = mime_type
        if has_text_payload:
            payload["text"] = text_value
        elif has_blob_payload:
            payload["blob"] = base64.b64encode(blob_value).decode("ascii") if isinstance(blob_value, bytes) else blob_value
        elif isinstance(content, str):
            payload["text"] = content
        elif isinstance(content, bytes):
            payload["blob"] = base64.b64encode(content).decode("ascii")
        if meta:
            payload["_meta"] = meta
        return {key: value for key, value in payload.items() if value is not None}

    if hasattr(content, "model_dump"):
        payload = content.model_dump(by_alias=True, exclude_none=True)
        if fallback_uri and "uri" not in payload:
            payload["uri"] = fallback_uri
        return payload

    payload = {"uri": uri}
    if mime_type:
        payload["mimeType"] = mime_type
    payload["text"] = str(content)
    if meta:
        payload["_meta"] = meta
    return {key: value for key, value in payload.items() if value is not None}


class MCPAppSessionService:
    """Persistence-backed AppBridge session helper."""

    def create_session(
        self,
        db: Session,
        *,
        mcp_session_id: str,
        user_email: str,
        server_id: Optional[str],
        resource_uri: str,
        token_teams: Optional[List[str]],
    ) -> DbMCPAppSession:
        """Create a short-lived AppBridge session."""
        now = datetime.now(timezone.utc)
        session = DbMCPAppSession(
            id=uuid.uuid4().hex,
            mcp_session_id=mcp_session_id,
            user_email=user_email,
            server_id=server_id,
            resource_uri=resource_uri,
            token_teams=token_teams,
            expires_at=now + timedelta(seconds=max(1, int(getattr(settings, "mcpgateway_mcp_apps_session_ttl", 900)))),
            created_at=now,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get_valid_session(
        self,
        db: Session,
        *,
        app_session_id: str,
        mcp_session_id: str,
        user_email: str,
        server_id: Optional[str],
        is_admin: bool = False,
    ) -> Optional[DbMCPAppSession]:
        """Return a valid same-user, same-session AppBridge session."""
        now = datetime.now(timezone.utc)
        conditions = [
            DbMCPAppSession.id == app_session_id,
            DbMCPAppSession.mcp_session_id == mcp_session_id,
            DbMCPAppSession.expires_at > now,
        ]
        if server_id is not None:
            conditions.append(DbMCPAppSession.server_id == server_id)
        if not is_admin:
            conditions.append(DbMCPAppSession.user_email == user_email)
        return db.execute(select(DbMCPAppSession).where(and_(*conditions))).scalar_one_or_none()


mcp_app_session_service = MCPAppSessionService()
