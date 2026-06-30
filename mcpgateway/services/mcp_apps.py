# -*- coding: utf-8 -*-
"""Minimal MCP Apps helpers.

This module centralizes MCP Apps metadata handling, capability advertising, and
AppBridge session management.
"""

# Standard
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any, Dict, Iterable, List, Optional
import uuid

# Third-Party
from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import fresh_db_session, MCPAppSession as DbMCPAppSession

logger = logging.getLogger(__name__)

MCP_UI_EXTENSION = "io.modelcontextprotocol/ui"
MCP_UI_DEFAULT_VERSION = "2026-01-26"
MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"

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


def _get_mapping_or_attr(value: Any, key: str) -> Any:
    """Read ``key`` from either a mapping-like object or a model attribute."""
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _client_capabilities(context: Any) -> Any:
    """Best-effort extraction of MCP client capabilities from SDK request context."""
    capabilities = getattr(context, "client_capabilities", None)
    if capabilities is not None:
        return capabilities

    session = getattr(context, "session", None)
    client_params = getattr(session, "client_params", None)
    if client_params is None:
        return None
    return getattr(client_params, "capabilities", None)


def client_supports_mcp_apps(context: Any) -> bool:
    """Return whether the current MCP client advertised MCP Apps support."""
    if not mcp_apps_enabled() or context is None:
        return False

    capabilities = _client_capabilities(context)
    extensions = _get_mapping_or_attr(capabilities, "extensions")
    if not isinstance(extensions, dict):
        return False

    ui_settings = extensions.get(MCP_UI_EXTENSION)
    if not isinstance(ui_settings, dict):
        return False

    mime_types = ui_settings.get("mimeTypes") or ui_settings.get("mime_types")
    return isinstance(mime_types, (list, tuple)) and MCP_APP_MIME_TYPE in mime_types


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


def _compact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return payload without ``None`` values."""
    return {key: value for key, value in payload.items() if value is not None}


def _serialize_resource_content_model(content: Any, *, fallback_uri: Optional[str]) -> Optional[Dict[str, Any]]:
    """Serialize known resource content models."""
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
        return _compact_payload(payload)

    if isinstance(content, ResourceContents):
        return content.model_dump(by_alias=True, exclude_none=True)

    return None


def _serialize_resource_content_mapping(content: Dict[str, Any], *, fallback_uri: Optional[str]) -> Dict[str, Any]:
    """Serialize mapping-shaped resource content."""
    payload = dict(content)
    if fallback_uri and "uri" not in payload:
        payload["uri"] = fallback_uri
    if "mime_type" in payload and "mimeType" not in payload:
        payload["mimeType"] = payload.pop("mime_type")
    if "meta" in payload and "_meta" not in payload:
        payload["_meta"] = payload.pop("meta")
    return _compact_payload(payload)


def _serialize_resource_content_payload(content: Any, *, fallback_uri: Optional[str]) -> Optional[Dict[str, Any]]:
    """Serialize text/blob-like resource content."""
    uri = fallback_uri or getattr(content, "uri", None)
    mime_type_value = getattr(content, "mime_type", None) or getattr(content, "mimeType", None)
    mime_type = mime_type_value if isinstance(mime_type_value, str) else None
    meta_value = getattr(content, "meta", None)
    meta = meta_value if isinstance(meta_value, dict) else None
    text_value = getattr(content, "text", None)
    blob_value = getattr(content, "blob", None)
    has_text_payload = isinstance(text_value, str)
    has_blob_payload = isinstance(blob_value, (bytes, str))

    if not (has_text_payload or has_blob_payload or isinstance(content, (str, bytes))):
        return None

    payload = {"uri": uri}
    if mime_type:
        payload["mimeType"] = mime_type
    if has_text_payload:
        payload["text"] = text_value
    elif has_blob_payload:
        payload["blob"] = base64.b64encode(blob_value).decode("ascii") if isinstance(blob_value, bytes) else blob_value
    elif isinstance(content, str):
        payload["text"] = content
    else:
        payload["blob"] = base64.b64encode(content).decode("ascii")
    if meta:
        payload["_meta"] = meta
    return _compact_payload(payload)


def serialize_resource_content_for_mcp(content: Any, *, fallback_uri: Optional[str] = None) -> Dict[str, Any]:
    """Serialize internal resource content into an MCP ``resources/read`` content item."""
    model_payload = _serialize_resource_content_model(content, fallback_uri=fallback_uri)
    if model_payload is not None:
        return model_payload

    if isinstance(content, dict):
        return _serialize_resource_content_mapping(content, fallback_uri=fallback_uri)

    payload = _serialize_resource_content_payload(content, fallback_uri=fallback_uri)
    if payload is not None:
        return payload

    uri = fallback_uri or getattr(content, "uri", None)
    mime_type_value = getattr(content, "mime_type", None) or getattr(content, "mimeType", None)
    mime_type = mime_type_value if isinstance(mime_type_value, str) else None
    meta_value = getattr(content, "meta", None)
    meta = meta_value if isinstance(meta_value, dict) else None

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
    return _compact_payload(payload)


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
        try:
            db.add(session)
            db.commit()
            db.refresh(session)
            return session
        except Exception:
            logger.exception("Failed to create MCP Apps session for resource=%s server_id=%s user=%s", resource_uri, server_id, user_email)
            try:
                db.rollback()
            except Exception:
                logger.debug("Failed to roll back MCP Apps session creation", exc_info=True)
            raise

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

    def cleanup_expired_sessions(self, db: Session, *, now: Optional[datetime] = None, batch_size: int = 1000) -> int:
        """Delete expired AppBridge sessions in bounded batches."""
        cutoff = now or datetime.now(timezone.utc)
        total_deleted = 0
        effective_batch_size = max(1, batch_size)

        try:
            while True:
                expired_ids = db.execute(select(DbMCPAppSession.id).where(DbMCPAppSession.expires_at <= cutoff).limit(effective_batch_size)).scalars().all()
                if not expired_ids:
                    break
                result = db.execute(delete(DbMCPAppSession).where(DbMCPAppSession.id.in_(expired_ids)))
                deleted_count = result.rowcount if isinstance(result.rowcount, int) else len(expired_ids)
                total_deleted += deleted_count
                if len(expired_ids) < effective_batch_size:
                    break
            db.commit()
            return total_deleted
        except Exception:
            logger.exception("Failed to clean up expired MCP Apps sessions")
            try:
                db.rollback()
            except Exception:
                logger.debug("Failed to roll back MCP Apps session cleanup", exc_info=True)
            raise


class MCPAppSessionCleanupService:
    """Background cleanup task for expired AppBridge sessions."""

    def __init__(self, session_service: Optional[MCPAppSessionService] = None, *, interval_seconds: Optional[int] = None, batch_size: Optional[int] = None, enabled: Optional[bool] = None) -> None:
        """Initialize the cleanup service."""
        self.session_service = session_service or mcp_app_session_service
        self.interval_seconds = interval_seconds or getattr(settings, "mcpgateway_mcp_apps_session_cleanup_interval_seconds", 300)
        self.batch_size = batch_size or getattr(settings, "mcpgateway_mcp_apps_session_cleanup_batch_size", 1000)
        self.enabled = enabled if enabled is not None else getattr(settings, "mcpgateway_mcp_apps_session_cleanup_enabled", True)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background cleanup loop."""
        if not self.enabled:
            logger.info("MCP Apps session cleanup disabled, skipping start")
            return
        if self._cleanup_task is None or self._cleanup_task.done():
            self._shutdown_event.clear()
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("MCP Apps session cleanup task started")

    async def shutdown(self) -> None:
        """Stop the background cleanup loop."""
        self._shutdown_event.set()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def cleanup_once(self) -> int:
        """Run one cleanup pass."""
        return await asyncio.to_thread(self._cleanup_once_sync)

    def _cleanup_once_sync(self) -> int:
        """Run one cleanup pass in a worker thread."""
        with fresh_db_session() as db:
            return self.session_service.cleanup_expired_sessions(db, batch_size=self.batch_size)

    async def _cleanup_loop(self) -> None:
        """Periodically delete expired AppBridge sessions."""
        interval = max(1, int(self.interval_seconds))
        while not self._shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                    break
                except asyncio.TimeoutError:
                    pass
                deleted_count = await self.cleanup_once()
                if deleted_count:
                    logger.info("MCP Apps session cleanup deleted %d expired sessions", deleted_count)
            except Exception:
                logger.exception("MCP Apps session cleanup loop failed")
                await asyncio.sleep(min(interval, 60))


mcp_app_session_service = MCPAppSessionService()
_mcp_app_session_cleanup_service: Optional[MCPAppSessionCleanupService] = None


def get_mcp_app_session_cleanup_service() -> MCPAppSessionCleanupService:
    """Get or create the singleton MCP Apps session cleanup service."""
    global _mcp_app_session_cleanup_service  # pylint: disable=global-statement
    if _mcp_app_session_cleanup_service is None:
        _mcp_app_session_cleanup_service = MCPAppSessionCleanupService()
    return _mcp_app_session_cleanup_service
