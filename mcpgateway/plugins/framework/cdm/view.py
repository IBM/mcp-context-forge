# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/cdm/view.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

MessageView - Zero-Copy Adapter for Policy Evaluation.

Provides a uniform interface for evaluating security policy against
any message component (text, resources, tools, prompts) without
copying data.
"""

import json
import re
from enum import Enum
from typing import Any, Iterator, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Message, ContentPart, Resource, ResourceReference, ToolCall, ToolResult, PromptRequest, PromptResult, Role


class ViewKind(str, Enum):
    """Types of message view targets.

    Attributes:
        TEXT: Plain text content.
        THINKING: Reasoning/chain-of-thought content.
        RESOURCE: Embedded resource with content.
        RESOURCE_REF: Reference to a resource (URI only).
        TOOL_CALL: Tool/function invocation.
        TOOL_RESULT: Result from tool execution.
        PROMPT_REQUEST: Prompt template request.
        PROMPT_RESULT: Rendered prompt result.
        IMAGE: Image content.
        VIDEO: Video content.
        AUDIO: Audio content.
        DOCUMENT: Document content.

    Examples:
        >>> ViewKind.TOOL_CALL.value
        'tool_call'
    """

    TEXT = "text"
    THINKING = "thinking"
    RESOURCE = "resource"
    RESOURCE_REF = "resource_ref"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROMPT_REQUEST = "prompt_request"
    PROMPT_RESULT = "prompt_result"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class ViewAction(str, Enum):
    """Abstract actions that view targets represent.

    Attributes:
        READ: Reading/accessing data.
        WRITE: Writing/modifying data.
        EXECUTE: Executing code/commands.
        INVOKE: Invoking a tool or prompt.
        SEND: Sending data outbound.
        RECEIVE: Receiving data inbound.
        GENERATE: Generating content.

    Examples:
        >>> ViewAction.EXECUTE.value
        'execute'
    """

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    INVOKE = "invoke"
    SEND = "send"
    RECEIVE = "receive"
    GENERATE = "generate"

# Can define different message views.
class MessageView:
    """Zero-copy view over a message component for policy evaluation.

    This adapter provides a uniform interface for policy evaluation
    without copying any data. Properties are computed on-demand by
    accessing the underlying object directly.

    Memory footprint: Just two references (_obj, _kind) plus cached
    values only when accessed.

    Usage:
        >>> for view in message.iter_message_views():
        ...     if view.kind == ViewKind.TOOL_CALL:
        ...         if "dangerous" in view.uri:
        ...             deny()
        ...     if view.content and contains_pii(view.content):
        ...         redact()

    Attributes:
        kind: The type of view target.
        raw: Access to the underlying object.
        ctx: The evaluation context (optional).
    """

    __slots__ = ("_obj", "_kind", "_role", "_ctx")

    def __init__(
        self,
        obj: Any,
        kind: ViewKind,
        role: Optional["Role"] = None,
        ctx: Optional[Any] = None,
    ):
        """Initialize a MessageView.

        Args:
            obj: The underlying message component.
            kind: The type of component.
            role: The role of the parent message (USER, ASSISTANT, etc.).
            ctx: Optional evaluation context.
        """
        self._obj = obj
        self._kind = kind
        self._role = role
        self._ctx = ctx

    # =========================================================================
    # Core Properties
    # =========================================================================

    @property
    def kind(self) -> ViewKind:
        """The type of target (text, resource, tool_call, etc.)."""
        return self._kind

    @property
    def raw(self) -> Any:
        """Access to the underlying object for type-specific logic."""
        return self._obj

    @property
    def ctx(self) -> Optional[Any]:
        """The evaluation context."""
        return self._ctx

    @property
    def role(self) -> Optional["Role"]:
        """The role of the parent message (USER, ASSISTANT, SYSTEM, TOOL, DEVELOPER)."""
        return self._role

    # =========================================================================
    # Phase Helpers (for unified hooks)
    # =========================================================================

    @property
    def is_pre(self) -> bool:
        """True if this represents input/request content (before processing).

        Determined by:
        - ViewKind: TOOL_CALL, PROMPT_REQUEST, RESOURCE_REF are always pre (requests)
        - Role: USER, SYSTEM, DEVELOPER, TOOL messages are input to LLM (pre)

        Returns:
            True if this is pre-processing content.
        """
        from .models import Role

        # These kinds are always requests (pre)
        if self._kind in (ViewKind.TOOL_CALL, ViewKind.PROMPT_REQUEST, ViewKind.RESOURCE_REF):
            return True

        # These kinds are always responses (post)
        if self._kind in (ViewKind.TOOL_RESULT, ViewKind.PROMPT_RESULT, ViewKind.RESOURCE):
            return False

        # For TEXT, THINKING, and media: use role to determine direction
        # USER, SYSTEM, DEVELOPER, TOOL = input to LLM (pre)
        # ASSISTANT = output from LLM (post)
        if self._role is not None:
            return self._role in (Role.USER, Role.SYSTEM, Role.DEVELOPER, Role.TOOL)

        # Default to None/unknown - caller should check role is set
        return False

    @property
    def is_post(self) -> bool:
        """True if this represents output/response content (after processing).

        Determined by:
        - ViewKind: TOOL_RESULT, PROMPT_RESULT, RESOURCE are always post (responses)
        - Role: ASSISTANT messages are output from LLM (post)

        Returns:
            True if this is post-processing content.
        """
        from .models import Role

        # These kinds are always responses (post)
        if self._kind in (ViewKind.TOOL_RESULT, ViewKind.PROMPT_RESULT, ViewKind.RESOURCE):
            return True

        # These kinds are always requests (pre)
        if self._kind in (ViewKind.TOOL_CALL, ViewKind.PROMPT_REQUEST, ViewKind.RESOURCE_REF):
            return False

        # For TEXT, THINKING, and media: use role to determine direction
        # ASSISTANT = output from LLM (post)
        if self._role is not None:
            return self._role == Role.ASSISTANT

        # Default to None/unknown
        return False

    # =========================================================================
    # Entity Type Helpers
    # =========================================================================

    @property
    def is_tool(self) -> bool:
        """True if this is a tool call or result."""
        return self._kind in (ViewKind.TOOL_CALL, ViewKind.TOOL_RESULT)

    @property
    def is_prompt(self) -> bool:
        """True if this is a prompt request or result."""
        return self._kind in (ViewKind.PROMPT_REQUEST, ViewKind.PROMPT_RESULT)

    @property
    def is_resource(self) -> bool:
        """True if this is a resource or resource reference."""
        return self._kind in (ViewKind.RESOURCE, ViewKind.RESOURCE_REF)

    @property
    def is_text(self) -> bool:
        """True if this is text or thinking content."""
        return self._kind in (ViewKind.TEXT, ViewKind.THINKING)

    @property
    def is_media(self) -> bool:
        """True if this is image, video, audio, or document."""
        return self._kind in (
            ViewKind.IMAGE,
            ViewKind.VIDEO,
            ViewKind.AUDIO,
            ViewKind.DOCUMENT,
        )

    # =========================================================================
    # Context Accessors
    # =========================================================================

    def _get_global_context(self) -> Optional[Any]:
        """Get the global context from PluginContext or direct context."""
        if self._ctx is None:
            return None
        # If ctx is a PluginContext, dig into global_context
        if hasattr(self._ctx, "global_context"):
            return self._ctx.global_context
        # Otherwise assume ctx is the global context directly
        return self._ctx

    @property
    def principal(self) -> Optional[Any]:
        """The principal (user/agent/service) making the request."""
        gc = self._get_global_context()
        return getattr(gc, "principal", None) if gc else None

    @property
    def roles(self) -> Set[str]:
        """Principal's roles."""
        p = self.principal
        if p and hasattr(p, "roles"):
            return p.roles
        return set()

    @property
    def permissions(self) -> Set[str]:
        """Principal's permissions."""
        p = self.principal
        if p and hasattr(p, "permissions"):
            return p.permissions
        return set()

    def has_role(self, role: str) -> bool:
        """Check if principal has a specific role.

        Args:
            role: The role to check for.

        Returns:
            True if the principal has the role.
        """
        p = self.principal
        if p and hasattr(p, "has_role"):
            return p.has_role(role)
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        """Check if principal has a specific permission.

        Args:
            permission: The permission to check for.

        Returns:
            True if the principal has the permission.
        """
        p = self.principal
        if p and hasattr(p, "has_permission"):
            return p.has_permission(permission)
        return permission in self.permissions

    @property
    def environment(self) -> Optional[str]:
        """Execution environment (production, staging, development)."""
        gc = self._get_global_context()
        return getattr(gc, "environment", None) if gc else None

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers associated with the request."""
        gc = self._get_global_context()
        return getattr(gc, "headers", {}) if gc else {}

    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Get an HTTP header value (case-insensitive).

        Args:
            name: Header name.
            default: Default value if header not found.

        Returns:
            Header value or default.
        """
        headers = self.headers
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def has_header(self, name: str) -> bool:
        """Check if a header exists (case-insensitive).

        Args:
            name: Header name to check.

        Returns:
            True if header exists.
        """
        return self.get_header(name) is not None

    @property
    def labels(self) -> Set[str]:
        """Data classification labels (PII, SECRET, CONFIDENTIAL, etc.)."""
        gc = self._get_global_context()
        labels: Set[str] = set(getattr(gc, "labels", set())) if gc else set()
        # Also check resource annotations
        if self._kind == ViewKind.RESOURCE and hasattr(self._obj, "annotations"):
            annotations = self._obj.annotations or {}
            if "labels" in annotations:
                labels.update(annotations["labels"])
        return labels

    def has_label(self, label: str) -> bool:
        """Check if target has a specific data label.

        Args:
            label: Label to check for (e.g., "PII", "SECRET").

        Returns:
            True if the label is present.
        """
        return label in self.labels

    @property
    def flow_direction(self) -> Optional[str]:
        """Data flow direction: 'inbound', 'outbound', 'internal'."""
        if not self._ctx:
            return None
        fd = getattr(self._ctx, "flow_direction", None)
        if fd is None:
            return None
        return fd.value if hasattr(fd, "value") else str(fd)

    @property
    def flow_source(self) -> Optional[str]:
        """Source of the data flow."""
        return getattr(self._ctx, "flow_source", None) if self._ctx else None

    @property
    def flow_destination(self) -> Optional[str]:
        """Destination of the data flow."""
        return getattr(self._ctx, "flow_destination", None) if self._ctx else None

    # =========================================================================
    # Universal Properties (computed on access)
    # =========================================================================

    @property
    def content(self) -> Optional[str]:
        """Text content for scanning (PII, secrets, etc.).

        Returns None if no text content is available.
        """
        if self._kind == ViewKind.TEXT:
            # _obj is the string content directly
            return self._obj if isinstance(self._obj, str) else str(self._obj)

        if self._kind == ViewKind.THINKING:
            # _obj is the string content directly
            return self._obj if isinstance(self._obj, str) else str(self._obj)

        if self._kind == ViewKind.RESOURCE:
            # _obj is a Resource object
            return getattr(self._obj, "content", None)

        if self._kind == ViewKind.TOOL_CALL:
            # _obj is a ToolCall object
            try:
                return json.dumps(self._obj.arguments)
            except (TypeError, ValueError):
                return str(self._obj.arguments)

        if self._kind == ViewKind.TOOL_RESULT:
            # _obj is a ToolResult object
            return getattr(self._obj, "content", None)

        if self._kind == ViewKind.PROMPT_REQUEST:
            # _obj is a PromptRequest object
            try:
                return json.dumps(self._obj.arguments)
            except (TypeError, ValueError):
                return str(self._obj.arguments)

        if self._kind == ViewKind.PROMPT_RESULT:
            # _obj is a PromptResult object
            return getattr(self._obj, "content", None)

        return None

    @property
    def uri(self) -> Optional[str]:
        """URI identifying this target.

        Tools get synthetic URIs like tool://namespace/name

        Returns:
            URI string or None if not applicable.
        """
        if self._kind == ViewKind.RESOURCE:
            return self._obj.uri

        if self._kind == ViewKind.RESOURCE_REF:
            return self._obj.uri

        if self._kind == ViewKind.TOOL_CALL:
            ns = self._obj.namespace or "_"
            return f"tool://{ns}/{self._obj.name}"

        if self._kind == ViewKind.TOOL_RESULT:
            return f"tool_result://{self._obj.tool_name}"

        if self._kind == ViewKind.PROMPT_REQUEST:
            server = self._obj.server_id or "_"
            return f"prompt://{server}/{self._obj.name}"

        if self._kind == ViewKind.PROMPT_RESULT:
            return f"prompt_result://{self._obj.prompt_name}"

        return None

    @property
    def action(self) -> Optional[ViewAction]:
        """The abstract action this target represents.

        Returns:
            The ViewAction, or None if not determinable.
        """
        if self._kind in (ViewKind.TEXT, ViewKind.THINKING):
            if self._ctx and hasattr(self._ctx, "get"):
                return self._ctx.get("action", ViewAction.SEND)
            return ViewAction.SEND

        if self._kind in (ViewKind.RESOURCE, ViewKind.RESOURCE_REF):
            return ViewAction.READ

        if self._kind == ViewKind.TOOL_CALL:
            return ViewAction.EXECUTE

        if self._kind == ViewKind.TOOL_RESULT:
            return ViewAction.RECEIVE

        if self._kind == ViewKind.PROMPT_REQUEST:
            return ViewAction.INVOKE

        if self._kind == ViewKind.PROMPT_RESULT:
            return ViewAction.GENERATE

        return None

    @property
    def size_bytes(self) -> Optional[int]:
        """Size of the target content in bytes."""
        if self._kind == ViewKind.RESOURCE:
            if self._obj.size_bytes is not None:
                return self._obj.size_bytes
            if self._obj.content:
                return len(self._obj.content.encode("utf-8"))
            if self._obj.blob:
                return len(self._obj.blob)

        content = self.content
        if content:
            return len(content.encode("utf-8"))

        return None

    @property
    def mime_type(self) -> Optional[str]:
        """MIME type if applicable."""
        if self._kind == ViewKind.RESOURCE:
            return self._obj.mime_type

        if self._kind == ViewKind.IMAGE:
            # _obj is now ImageSource directly
            if hasattr(self._obj, "media_type"):
                return self._obj.media_type
            return "image/*"

        return None

    @property
    def name(self) -> Optional[str]:
        """Human-readable name for this target."""
        if self._kind == ViewKind.RESOURCE:
            return self._obj.name

        if self._kind == ViewKind.RESOURCE_REF:
            return self._obj.name

        if self._kind == ViewKind.TOOL_CALL:
            return self._obj.name

        if self._kind == ViewKind.PROMPT_REQUEST:
            return self._obj.name

        if self._kind == ViewKind.PROMPT_RESULT:
            return self._obj.prompt_name

        return None

    # =========================================================================
    # Arguments Access (for TOOL_CALL and PROMPT_REQUEST)
    # =========================================================================

    @property
    def args(self) -> Optional[dict[str, Any]]:
        """Arguments dict for tool calls and prompt requests.

        Zero-copy: returns the underlying object's arguments directly.

        Returns:
            Arguments dict for TOOL_CALL/PROMPT_REQUEST, None otherwise.
        """
        if self._kind == ViewKind.TOOL_CALL:
            return self._obj.arguments
        if self._kind == ViewKind.PROMPT_REQUEST:
            return self._obj.arguments
        return None

    def get_arg(self, name: str, default: Any = None) -> Any:
        """Get a single argument value without copying.

        Args:
            name: Argument name.
            default: Value if argument doesn't exist.

        Returns:
            Argument value or default.
        """
        args = self.args
        if args is None:
            return default
        return args.get(name, default)

    def has_arg(self, name: str) -> bool:
        """Check if an argument exists.

        Args:
            name: Argument name to check.

        Returns:
            True if argument exists.
        """
        args = self.args
        return args is not None and name in args

    def iter_args(self) -> Iterator[tuple[str, Any]]:
        """Iterate over argument key-value pairs.

        Yields:
            Tuples of (arg_name, arg_value).
        """
        args = self.args
        if args:
            yield from args.items()

    def arg_names(self) -> set[str]:
        """Get the set of argument names.

        Returns:
            Set of argument names, empty set if no arguments.
        """
        args = self.args
        return set(args.keys()) if args else set()

    # =========================================================================
    # Type-Specific Property Access
    # =========================================================================

    def get_property(self, name: str, default: Any = None) -> Any:
        """Get a single type-specific property without allocating a dict.

        Zero-copy: directly accesses the underlying object's attribute.

        Available properties by kind:
            RESOURCE: resource_type, version, annotations
            TOOL_CALL: arguments, namespace, tool_id
            TOOL_RESULT: is_error, tool_name
            PROMPT_REQUEST: arguments, server_id
            PROMPT_RESULT: is_error, message_count

        Args:
            name: Property name to retrieve.
            default: Value to return if property doesn't exist.

        Returns:
            The property value or default.
        """
        if self._kind == ViewKind.RESOURCE:
            if name == "resource_type":
                return self._obj.resource_type
            if name == "version":
                return self._obj.version
            if name == "annotations":
                return self._obj.annotations

        elif self._kind == ViewKind.TOOL_CALL:
            if name == "arguments":
                return self._obj.arguments
            if name == "namespace":
                return self._obj.namespace
            if name == "tool_id":
                return self._obj.id

        elif self._kind == ViewKind.TOOL_RESULT:
            if name == "is_error":
                return self._obj.is_error
            if name == "tool_name":
                return self._obj.tool_name

        elif self._kind == ViewKind.PROMPT_REQUEST:
            if name == "arguments":
                return self._obj.arguments
            if name == "server_id":
                return self._obj.server_id

        elif self._kind == ViewKind.PROMPT_RESULT:
            if name == "is_error":
                return self._obj.is_error
            if name == "message_count":
                return len(self._obj.messages) if self._obj.messages else 0

        return default

    def has_property(self, name: str) -> bool:
        """Check if a property exists for this target kind without allocation.

        Args:
            name: Property name to check.

        Returns:
            True if the property exists for this target kind.
        """
        props_by_kind = {
            ViewKind.RESOURCE: {"resource_type", "version", "annotations"},
            ViewKind.TOOL_CALL: {"arguments", "namespace", "tool_id"},
            ViewKind.TOOL_RESULT: {"is_error", "tool_name"},
            ViewKind.PROMPT_REQUEST: {"arguments", "server_id"},
            ViewKind.PROMPT_RESULT: {"is_error", "message_count"},
        }
        return name in props_by_kind.get(self._kind, set())

    @property
    def properties(self) -> dict[str, Any]:
        """All type-specific properties as a dict.

        NOTE: This allocates a new dict on each call. For single property
        access, prefer get_property(name) which is zero-allocation.

        Returns:
            Dict of property name -> value for this target kind.
        """
        props: dict[str, Any] = {}

        if self._kind == ViewKind.RESOURCE:
            props["resource_type"] = self._obj.resource_type
            props["version"] = self._obj.version
            props["annotations"] = self._obj.annotations

        elif self._kind == ViewKind.TOOL_CALL:
            props["arguments"] = self._obj.arguments
            props["namespace"] = self._obj.namespace
            props["tool_id"] = self._obj.id

        elif self._kind == ViewKind.TOOL_RESULT:
            props["is_error"] = self._obj.is_error
            props["tool_name"] = self._obj.tool_name

        elif self._kind == ViewKind.PROMPT_REQUEST:
            props["arguments"] = self._obj.arguments
            props["server_id"] = self._obj.server_id

        elif self._kind == ViewKind.PROMPT_RESULT:
            props["is_error"] = self._obj.is_error
            props["message_count"] = len(self._obj.messages) if self._obj.messages else 0

        return props

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def has_content(self) -> bool:
        """Check if this target has text content for scanning.

        Returns:
            True if content is available.
        """
        return self.content is not None

    def matches_uri_pattern(self, pattern: str) -> bool:
        """Check if URI matches a glob-style pattern.

        Args:
            pattern: Glob pattern (supports * and ** wildcards).

        Returns:
            True if URI matches the pattern.
        """
        uri = self.uri
        if not uri:
            return False

        # Convert glob to regex
        regex = pattern.replace("**", "<<<DOUBLE>>>")
        regex = regex.replace("*", "[^/]*")
        regex = regex.replace("<<<DOUBLE>>>", ".*")
        regex = f"^{regex}$"

        return bool(re.match(regex, uri))

    def __repr__(self) -> str:
        """String representation of the view."""
        role_part = f", role={self._role.value}" if self._role else ""
        uri_part = f", uri={self.uri}" if self.uri else ""
        pre_post = "pre" if self.is_pre else "post" if self.is_post else "?"
        return f"MessageView(kind={self._kind.value}{role_part}, {pre_post}{uri_part})"

    # =========================================================================
    # Serialization (for OPA, external policy engines)
    # =========================================================================

    def to_dict(self, include_content: bool = True, include_context: bool = True) -> dict[str, Any]:
        """Serialize the view to a JSON-compatible dictionary.

        This method is designed for sending to external policy engines like OPA,
        Cedar, or other HTTP-based decision services.

        Args:
            include_content: Include text content (may be large).
            include_context: Include principal/environment context.

        Returns:
            JSON-serializable dictionary with view properties.

        Example:
            >>> view_dict = view.to_dict()
            >>> # Send to OPA
            >>> response = httpx.post(opa_url, json={"input": view_dict})
        """
        result: dict[str, Any] = {
            "kind": self._kind.value,
            "is_pre": self.is_pre,
            "is_post": self.is_post,
        }

        # Role
        if self._role is not None:
            result["role"] = self._role.value

        # URI and name
        if self.uri:
            result["uri"] = self.uri
        if self.name:
            result["name"] = self.name

        # Action
        if self.action:
            result["action"] = self.action.value

        # Content (optional, can be large)
        if include_content:
            content = self.content
            if content is not None:
                result["content"] = content
            size = self.size_bytes
            if size is not None:
                result["size_bytes"] = size

        # MIME type
        if self.mime_type:
            result["mime_type"] = self.mime_type

        # Arguments for tool calls and prompts
        args = self.args
        if args is not None:
            result["arguments"] = args

        # Type-specific properties
        props = self.properties
        if props:
            result["properties"] = props

        # Context (optional)
        if include_context:
            ctx_dict: dict[str, Any] = {}

            # Principal info
            p = self.principal
            if p:
                principal_dict: dict[str, Any] = {}
                if hasattr(p, "id"):
                    principal_dict["id"] = p.id
                if hasattr(p, "type"):
                    principal_dict["type"] = p.type.value if hasattr(p.type, "value") else str(p.type)
                if hasattr(p, "roles"):
                    principal_dict["roles"] = list(p.roles)
                if hasattr(p, "permissions"):
                    principal_dict["permissions"] = list(p.permissions)
                if hasattr(p, "teams"):
                    principal_dict["teams"] = list(p.teams)
                if hasattr(p, "tenant_id") and p.tenant_id:
                    principal_dict["tenant_id"] = p.tenant_id
                ctx_dict["principal"] = principal_dict

            # Environment
            env = self.environment
            if env:
                ctx_dict["environment"] = env

            # Labels
            labels = self.labels
            if labels:
                ctx_dict["labels"] = list(labels)

            # Headers (be selective - don't include auth tokens)
            headers = self.headers
            if headers:
                safe_headers = {
                    k: v for k, v in headers.items()
                    if k.lower() not in ("authorization", "x-api-key", "cookie")
                }
                if safe_headers:
                    ctx_dict["headers"] = safe_headers

            if ctx_dict:
                result["context"] = ctx_dict

        return result

    def to_opa_input(self, include_content: bool = True) -> dict[str, Any]:
        """Serialize to OPA-compatible input format.

        Wraps the view in the standard OPA input envelope.

        Args:
            include_content: Include text content in the input.

        Returns:
            Dict in format: {"input": {...view data...}}

        Example:
            >>> opa_input = view.to_opa_input()
            >>> response = httpx.post(
            ...     "http://localhost:8181/v1/data/policy/allow",
            ...     json=opa_input
            ... )
        """
        return {"input": self.to_dict(include_content=include_content)}


# =============================================================================
# Message Integration - Iterator Function
# =============================================================================


def iter_message_views(message: "Message", ctx: Optional[Any] = None) -> Iterator[MessageView]:
    """Iterate over a message yielding MessageViews.

    Memory-efficient: only one view exists at a time.
    Each view carries the parent message's role for direction determination.

    Args:
        message: The message to iterate over.
        ctx: Optional context passed to each view.

    Yields:
        MessageView for each component in the message.
    """
    from .models import ContentType, Resource, ResourceReference, PromptRequest, PromptResult

    role = message.role

    # Handle string content
    if isinstance(message.content, str):
        yield MessageView(message.content, ViewKind.TEXT, role, ctx)
    else:
        # Handle multimodal content parts - all use .content field now
        for part in message.content:
            if part.type == ContentType.TEXT:
                yield MessageView(part.content, ViewKind.TEXT, role, ctx)

            elif part.type == ContentType.THINKING:
                yield MessageView(part.content, ViewKind.THINKING, role, ctx)

            elif part.type == ContentType.RESOURCE:
                # Distinguish between Resource and ResourceReference
                if isinstance(part.content, Resource):
                    yield MessageView(part.content, ViewKind.RESOURCE, role, ctx)
                elif isinstance(part.content, ResourceReference):
                    yield MessageView(part.content, ViewKind.RESOURCE_REF, role, ctx)

            elif part.type == ContentType.TOOL_CALL:
                yield MessageView(part.content, ViewKind.TOOL_CALL, role, ctx)

            elif part.type == ContentType.TOOL_RESULT:
                yield MessageView(part.content, ViewKind.TOOL_RESULT, role, ctx)

            elif part.type == ContentType.PROMPT:
                # Distinguish between PromptRequest and PromptResult
                if isinstance(part.content, PromptRequest):
                    yield MessageView(part.content, ViewKind.PROMPT_REQUEST, role, ctx)
                elif isinstance(part.content, PromptResult):
                    yield MessageView(part.content, ViewKind.PROMPT_RESULT, role, ctx)

            elif part.type == ContentType.IMAGE:
                yield MessageView(part.content, ViewKind.IMAGE, role, ctx)

            elif part.type == ContentType.VIDEO:
                yield MessageView(part.content, ViewKind.VIDEO, role, ctx)

            elif part.type == ContentType.AUDIO:
                yield MessageView(part.content, ViewKind.AUDIO, role, ctx)

            elif part.type == ContentType.DOCUMENT:
                yield MessageView(part.content, ViewKind.DOCUMENT, role, ctx)
