# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/completion_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Completion Service Implementation.
This module implements argument completion according to the MCP specification.
It handles completion suggestions for prompt arguments and resource URIs.

Examples:
    >>> from mcpgateway.services.completion_service import CompletionService, CompletionError
    >>> service = CompletionService()
    >>> isinstance(service, CompletionService)
    True
    >>> service._custom_completions
    {}
"""

# Standard
import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

# Third-Party
from mcp import MCPError as McpError
from mcp.types import PromptReference, ResourceTemplateReference
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.models import CompleteResult
from mcpgateway.config import settings
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.upstream_session_registry import (
    _categorize_upstream_error,
    downstream_session_id_from_request_context as _downstream_session_id_from_request,
    get_upstream_session_registry,
    RegistryNotInitializedError,
    TransportType,
)
from mcpgateway.utils.gateway_access import build_gateway_auth_headers
from mcpgateway.utils.mcp_proxy_client import mcp_proxy_client
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.url_auth import apply_query_param_auth

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CompletionError(Exception):
    """Base class for completion errors.

    Examples:
        >>> from mcpgateway.services.completion_service import CompletionError
        >>> err = CompletionError("Invalid reference")
        >>> str(err)
        'Invalid reference'
        >>> isinstance(err, Exception)
        True
    """


class CompletionNotSupportedError(CompletionError):
    """Upstream server does not advertise the ``completions`` capability.

    Maps to JSON-RPC ``-32601`` (Method not found) so the caller receives the
    same answer the upstream itself would have given.
    """


class CompletionInvalidParamsError(CompletionError):
    """Request names an unknown prompt/resource or omits a required argument.

    Maps to JSON-RPC ``-32602`` (Invalid params).
    """


class CompletionInternalError(CompletionError):
    """Upstream transport failure or an unexpected error while completing.

    Maps to JSON-RPC ``-32603`` (Internal error).
    """


#: JSON-RPC error code for each completion error class, most specific first.
COMPLETION_ERROR_CODES = (
    (CompletionNotSupportedError, -32601),
    (CompletionInvalidParamsError, -32602),
    (CompletionInternalError, -32603),
)

#: Upstream JSON-RPC error code -> the completion error class that reproduces it.
_UPSTREAM_CODE_TO_ERROR = {
    -32601: CompletionNotSupportedError,
    -32602: CompletionInvalidParamsError,
}


def completion_error_code(exc: CompletionError) -> int:
    """Map a completion error to its MCP JSON-RPC error code.

    Args:
        exc: The completion error to classify.

    Returns:
        The matching MCP JSON-RPC error code, defaulting to ``-32603``
        (Internal error) for an unclassified :class:`CompletionError`.

    Examples:
        >>> completion_error_code(CompletionNotSupportedError("x"))
        -32601
        >>> completion_error_code(CompletionInvalidParamsError("x"))
        -32602
        >>> completion_error_code(CompletionInternalError("x"))
        -32603
        >>> completion_error_code(CompletionError("x"))
        -32603
    """
    for error_type, code in COMPLETION_ERROR_CODES:
        if isinstance(exc, error_type):
            return code
    return -32603


class CompletionService:
    """MCP completion service.

    Handles argument completion for:
    - Prompt arguments based on schema
    - Resource URIs with templates
    - Custom completion sources
    """

    def __init__(self):
        """Initialize completion service.

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> hasattr(service, '_custom_completions')
            True
            >>> service._custom_completions
            {}
        """
        self._custom_completions: Dict[str, List[str]] = {}

    async def initialize(self) -> None:
        """Initialize completion service."""
        logger.info("Initializing completion service")

    async def shutdown(self) -> None:
        """Shutdown completion service."""
        logger.info("Shutting down completion service")
        self._custom_completions.clear()

    @staticmethod
    def _gateway_connection(gateway: Any) -> tuple:
        """Resolve the URL, auth headers and decoded query-param auth for a gateway.

        Args:
            gateway: The owning gateway ORM/model instance.

        Returns:
            A ``(gateway_url, headers, auth_query_params_decrypted)`` tuple.

        Raises:
            CompletionInternalError: If query-parameter auth cannot be decoded.
        """
        gateway_url = str(gateway.url)
        headers = build_gateway_auth_headers(gateway)
        auth_query_params_decrypted: Optional[Dict[str, str]] = None

        if getattr(gateway, "auth_type", None) == "query_param" and getattr(gateway, "auth_query_params", None):
            auth_query_params_decrypted = {}
            for param_key, encrypted_value in (gateway.auth_query_params or {}).items():
                try:
                    decoded = decode_auth(encrypted_value)
                    auth_query_params_decrypted[param_key] = decoded.get(param_key, "")
                except Exception as exc:
                    raise CompletionInternalError(f"Failed to decode query-parameter auth for gateway '{getattr(gateway, 'id', '')}'") from exc
            if auth_query_params_decrypted:
                gateway_url = apply_query_param_auth(gateway_url, auth_query_params_decrypted)

        return gateway_url, headers, auth_query_params_decrypted

    @asynccontextmanager
    async def _acquire_upstream_session(self, gateway: Any) -> AsyncIterator[Any]:
        """Yield an initialized MCP client session for ``gateway``.

        Reuses the upstream session pinned to the current downstream
        ``Mcp-Session-Id`` when one is in scope (#4205); otherwise opens a
        short-lived session via ``mcp_proxy_client()``, which negotiates the
        protocol era the same way the registry path does (``mode=`` resolves
        to ``settings.mcp_client_connect_mode`` by default) — this fallback is
        not pinned to the legacy handshake.

        Args:
            gateway: The owning gateway ORM/model instance.

        Yields:
            A client session exposing ``.server_capabilities``,
            ``.protocol_version``, and ``.complete(...)``.
        """
        gateway_url, headers, _auth_query_params = self._gateway_connection(gateway)

        gateway_id = str(getattr(gateway, "id", ""))
        transport = str(getattr(gateway, "transport", "streamable_http") or "streamable_http").lower()
        registry_transport_type = TransportType.SSE if transport == "sse" else TransportType.STREAMABLE_HTTP

        downstream_session_id = _downstream_session_id_from_request()
        if downstream_session_id and gateway_id:
            try:
                registry = get_upstream_session_registry()
            except RegistryNotInitializedError:
                registry = None
            if registry is not None:
                async with registry.acquire(
                    downstream_session_id=downstream_session_id,
                    gateway_id=gateway_id,
                    url=gateway_url,
                    headers=headers,
                    transport_type=registry_transport_type,
                ) as upstream:
                    yield upstream.session
                    return

        async with mcp_proxy_client(
            url=gateway_url,
            headers=headers,
            timeout=settings.health_check_timeout,
            transport="sse" if transport == "sse" else "streamablehttp",
        ) as client:
            yield client.session

    @staticmethod
    def _unwrap_exception(exc: BaseException) -> BaseException:
        """Unwrap nested BaseExceptionGroup layers down to the first real error.

        ``mcp_proxy_client``/registry acquisition and ``ClientSession`` are
        each anyio task groups, so a body exception surfaces as an
        ExceptionGroup.

        Args:
            exc: The caught exception, possibly a ``BaseExceptionGroup``.

        Returns:
            The first non-group exception found, or ``exc`` itself if it is
            not a ``BaseExceptionGroup``.
        """
        root: BaseException = exc
        while isinstance(root, BaseExceptionGroup) and root.exceptions:
            root = root.exceptions[0]
        return root

    @staticmethod
    def _error_from_upstream(exc: "McpError", gateway_id: str) -> "CompletionError":
        """Translate an upstream MCPError into the matching completion error.

        Issue #6629 requires the caller to receive "the same answer the
        upstream itself would give", so the upstream's own JSON-RPC code
        decides the class rather than every upstream failure collapsing to
        an internal error.

        Args:
            exc: The upstream ``MCPError``.
            gateway_id: Owning gateway id, included in the message for
                troubleshooting.

        Returns:
            The :class:`CompletionError` subclass matching the upstream's
            JSON-RPC error code.
        """
        code = getattr(getattr(exc, "error", None), "code", None)
        message = getattr(getattr(exc, "error", None), "message", None) or str(exc)
        error_type = _UPSTREAM_CODE_TO_ERROR.get(code, CompletionInternalError)
        return error_type(f"Upstream gateway '{gateway_id}' returned an error: {message}")

    async def _forward_completion_upstream(
        self,
        gateway: Any,
        ref: Any,
        argument: Dict[str, str],
        context: Optional[Dict[str, Any]] = None,
    ) -> CompleteResult:
        """Forward a completion/complete request to the owning upstream server.

        Args:
            gateway: The owning gateway ORM/model instance.
            ref: The MCP ``ref/prompt`` or ``ref/resource`` reference.
            argument: ``{"name": ..., "value": ...}`` argument being completed.
            context: Optional completion context (``{"arguments": {...}}``).

        Returns:
            The upstream's completion result, translated to this gateway's
            :class:`CompleteResult`.

        Raises:
            CompletionInternalError: Gateway metadata is missing, the context
                is malformed, or the upstream call failed for a non-MCP
                reason.
            CompletionInvalidParamsError: The completion context is malformed.
            CompletionNotSupportedError: The upstream does not advertise the
                ``completions`` capability.
        """
        if gateway is None:
            raise CompletionInternalError("Federated record is missing gateway metadata")

        gateway_id = str(getattr(gateway, "id", ""))
        raw_context = context or {}
        if not isinstance(raw_context, dict):
            raise CompletionInvalidParamsError("Completion context must be an object")
        context_arguments = raw_context.get("arguments") or None
        if context_arguments is not None and not isinstance(context_arguments, dict):
            raise CompletionInvalidParamsError("Completion context arguments must be an object")

        auth_query_params: Optional[Dict[str, str]] = None

        try:
            _, _, auth_query_params = self._gateway_connection(gateway)
            async with self._acquire_upstream_session(gateway) as session:
                capabilities = session.server_capabilities
                if capabilities is None or getattr(capabilities, "completions", None) is None:
                    raise CompletionNotSupportedError(f"Upstream gateway '{gateway_id}' does not support completions")

                remote_result = await session.complete(ref, argument, context_arguments)
        except BaseException as exc:  # noqa: BLE001 - anyio wraps handler errors in ExceptionGroup
            root = self._unwrap_exception(exc)
            if isinstance(root, CompletionError):
                raise root from exc
            if isinstance(root, McpError):
                raise self._error_from_upstream(root, gateway_id) from exc
            if isinstance(root, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            # Reuse the registry's shared categorizer for the generic path
            # instead of a bespoke unwrap + sanitize_exception_message call
            # (spec §3): its 3rd tuple element is already the sanitized
            # message.
            _category, _exc_type, sanitized_error, _count = _categorize_upstream_error(root, auth_query_params)
            raise CompletionInternalError(f"Failed to forward completion to gateway '{gateway_id}': {sanitized_error}") from exc

        completion = getattr(remote_result, "completion", None)
        if completion is None:
            raise CompletionInternalError("Upstream returned a completion result without a completion payload")

        values = list(getattr(completion, "values", None) or [])
        total = getattr(completion, "total", None)
        # SDK 2.0's Completion model attribute is `has_more` (snake_case);
        # the camelCase `hasMore` only exists as a wire/serialization alias
        # (see spec §2 row 11) — reading `hasMore` here silently returns
        # None always.
        has_more = getattr(completion, "has_more", None)
        return CompleteResult(
            completion={
                "values": values,
                "total": total,
                "hasMore": has_more if has_more is not None else (total is not None and total > len(values)),
            }
        )

    async def handle_completion(
        self,
        db: Session,
        request: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> CompleteResult:
        """Handle completion request.

        Args:
            db: Database session
            request: Completion request
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)

        Returns:
            Completion result with suggestions

        Raises:
            CompletionError: If completion fails

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> from unittest.mock import MagicMock
            >>> service = CompletionService()
            >>> db = MagicMock()
            >>> request = {'ref': {'type': 'ref/prompt', 'name': 'prompt1'}, 'argument': {'name': 'arg1', 'value': ''}}
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.handle_completion(db, request))
            ... except Exception:
            ...     pass
        """
        try:
            # Get reference and argument info
            ref = request.get("ref", {})
            ref_type = ref.get("type")
            arg = request.get("argument", {})
            arg_name = arg.get("name")
            arg_value = arg.get("value", "")

            if not ref_type or not arg_name:
                raise CompletionInvalidParamsError("Missing reference type or argument name")

            context = request.get("context")

            # Handle different reference types
            if ref_type == "ref/prompt":
                result = await self._complete_prompt_argument(db, ref, arg_name, arg_value, user_email=user_email, token_teams=token_teams, context=context)
            elif ref_type == "ref/resource":
                result = await self._complete_resource_uri(db, ref, arg_value, user_email=user_email, token_teams=token_teams, arg_name=arg_name, context=context)
            else:
                raise CompletionInvalidParamsError(f"Invalid reference type: {ref_type}")

            return result

        except CompletionError as e:
            # Preserve the specific error class so callers can map it to the
            # correct JSON-RPC code (-32601 / -32602 / -32603).
            logger.error("Completion error: %s", e)
            raise
        except Exception as e:
            logger.error("Completion error: %s", e)
            raise CompletionInternalError(str(e)) from e

    async def _resolve_team_ids(self, db: Session, user_email: Optional[str], token_teams: Optional[List[str]]) -> List[str]:
        """Resolve effective team IDs for scoped visibility checks.

        Args:
            db: Database session
            user_email: Caller email for DB-based team lookup when token teams are not explicit
            token_teams: Explicit token team scope when present

        Returns:
            Effective team IDs used to build visibility filters.
        """
        if token_teams is not None:
            return token_teams
        if not user_email:
            return []

        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        return [team.id for team in user_teams]

    @staticmethod
    def _apply_visibility_scope(stmt, model, user_email: Optional[str], token_teams: Optional[List[str]], team_ids: List[str], db: Session):
        """Thin passthrough to :meth:`BaseService._apply_visibility_scope`.

        Kept as a method on this class for API stability with existing
        callers; the actual logic (including the admin-bypass caller
        contract) lives in :class:`BaseService`.

        Args:
            stmt: SQLAlchemy statement to constrain
            model: ORM model with visibility/team/owner columns
            user_email: Caller email used for owner visibility
            token_teams: Explicit token team scope when present
            team_ids: Effective team IDs for team visibility
            db: Required session for the admin bypass check.

        Returns:
            Scoped SQLAlchemy statement.
        """
        # First-Party
        from mcpgateway.services.base_service import BaseService  # pylint: disable=import-outside-toplevel

        return BaseService._apply_visibility_scope(stmt, model, user_email, token_teams, team_ids, db)  # pylint: disable=protected-access

    @staticmethod
    def _is_federated(record: Any) -> bool:
        """Return whether a catalog record is owned by an upstream gateway.

        Args:
            record: A DB-backed prompt or resource row.

        Returns:
            ``True`` if the record has a non-empty ``gateway_id``.
        """
        return bool(getattr(record, "gateway_id", None))

    async def _complete_prompt_argument(
        self,
        db: Session,
        ref: Dict[str, Any],
        arg_name: str,
        arg_value: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> CompleteResult:
        """Complete prompt argument value.

        For a federated prompt, forwards the request to the owning upstream
        server. If the upstream does not advertise the (optional)
        ``completions`` capability, falls back to the locally-synced
        ``argument_schema`` (enum / custom completions) instead of raising.

        Args:
            db: Database session
            ref: Prompt reference
            arg_name: Argument name
            arg_value: Current argument value
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)
            context: Optional completion context (``{"arguments": {...}}``)
                forwarded to a federated prompt's upstream.

        Returns:
            Completion suggestions

        Raises:
            CompletionInvalidParamsError: If the prompt name is missing, the
                prompt is not found, or the argument is not found.

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService, CompletionInvalidParamsError
            >>> from unittest.mock import MagicMock
            >>> import asyncio
            >>> service = CompletionService()
            >>> db = MagicMock()

            >>> # Test missing prompt name
            >>> ref = {}
            >>> try:
            ...     asyncio.run(service._complete_prompt_argument(db, ref, 'arg1', 'val'))
            ... except CompletionInvalidParamsError as e:
            ...     str(e)
            'Missing prompt name'

            >>> # Test custom completions
            >>> service.register_completions('color', ['red', 'green', 'blue'])
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock(
            ...     argument_schema={'properties': {'color': {'name': 'color'}}}, gateway_id=None
            ... )
            >>> result = asyncio.run(service._complete_prompt_argument(
            ...     db, {'name': 'test'}, 'color', 'r'
            ... ))
            >>> result.completion['values']
            ['red', 'green']
        """
        # Get prompt
        prompt_name = ref.get("name")
        if not prompt_name:
            raise CompletionInvalidParamsError("Missing prompt name")

        # Only consider prompts that are enabled and visible to caller
        team_ids = await self._resolve_team_ids(db, user_email, token_teams)
        stmt = select(DbPrompt).where(DbPrompt.name == prompt_name).where(DbPrompt.enabled)  # pylint: disable=comparison-with-callable
        stmt = self._apply_visibility_scope(stmt, DbPrompt, user_email=user_email, token_teams=token_teams, team_ids=team_ids, db=db)
        stmt = stmt.order_by(desc(DbPrompt.created_at), desc(DbPrompt.id)).limit(1)
        prompt = db.execute(stmt).scalar_one_or_none()

        if not prompt:
            raise CompletionInvalidParamsError(f"Prompt not found: {prompt_name}")

        if self._is_federated(prompt):
            remote_name = getattr(prompt, "original_name", None) or prompt.name
            try:
                return await self._forward_completion_upstream(
                    getattr(prompt, "gateway", None),
                    PromptReference(type="ref/prompt", name=remote_name),
                    {"name": arg_name, "value": arg_value},
                    context,
                )
            except CompletionNotSupportedError:
                logger.info(
                    "Upstream gateway for federated prompt '%s' does not support completions; falling back to the locally-synced argument schema",
                    prompt_name,
                )

        # Find argument in schema
        arg_schema = None
        for arg in prompt.argument_schema.get("properties", {}).values():
            if arg.get("name") == arg_name:
                arg_schema = arg
                break

        if not arg_schema:
            raise CompletionInvalidParamsError(f"Argument not found: {arg_name}")

        # Get enum values if defined
        if "enum" in arg_schema:
            values = [v for v in arg_schema["enum"] if arg_value.lower() in str(v).lower()]
            return CompleteResult(
                completion={
                    "values": values[:100],
                    "total": len(values),
                    "hasMore": len(values) > 100,
                }
            )

        # Check custom completions
        if arg_name in self._custom_completions:
            values = [v for v in self._custom_completions[arg_name] if arg_value.lower() in v.lower()]
            return CompleteResult(
                completion={
                    "values": values[:100],
                    "total": len(values),
                    "hasMore": len(values) > 100,
                }
            )

        # No completions available
        return CompleteResult(completion={"values": [], "total": 0, "hasMore": False})

    async def _complete_resource_uri(
        self,
        db: Session,
        ref: Dict[str, Any],
        arg_value: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        arg_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> CompleteResult:
        """Complete resource URI.

        Federated resource *templates* are completed by their owning
        upstream; plain (non-template) resources are never forwarded — only
        rows with a non-null ``uri_template`` are forwarding candidates.

        Args:
            db: Database session
            ref: Resource reference
            arg_value: Current URI value
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)
            arg_name: Argument name being completed (forwarded to the
                upstream for a federated resource template; defaults to
                ``"uri"`` when not supplied).
            context: Optional completion context (``{"arguments": {...}}``)
                forwarded to a federated resource template's upstream.

        Returns:
            URI completion suggestions

        Raises:
            CompletionInvalidParamsError: If URI template is missing

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService, CompletionInvalidParamsError
            >>> from unittest.mock import MagicMock
            >>> import asyncio
            >>> service = CompletionService()
            >>> db = MagicMock()

            >>> # Test missing URI template
            >>> ref = {}
            >>> try:
            ...     asyncio.run(service._complete_resource_uri(db, ref, 'test'))
            ... except CompletionInvalidParamsError as e:
            ...     str(e)
            'Missing URI template'

            >>> # Test resource filtering (no federated owner -> local listing)
            >>> ref = {'uri': 'template://'}
            >>> mock_resources = [
            ...     MagicMock(uri='file://doc1.txt'),
            ...     MagicMock(uri='file://doc2.txt'),
            ...     MagicMock(uri='http://example.com')
            ... ]
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.execute.return_value.scalars.return_value.all.return_value = mock_resources
            >>> result = asyncio.run(service._complete_resource_uri(db, ref, 'doc'))
            >>> len(result.completion['values'])
            2
            >>> 'file://doc1.txt' in result.completion['values']
            True
        """
        # Get base URI template
        uri_template = ref.get("uri")
        if not uri_template:
            raise CompletionInvalidParamsError("Missing URI template")

        team_ids = await self._resolve_team_ids(db, user_email, token_teams)

        owner_stmt = select(DbResource).where(DbResource.enabled).where(DbResource.uri_template.is_not(None)).where(DbResource.uri_template == uri_template)  # pylint: disable=comparison-with-callable
        owner_stmt = self._apply_visibility_scope(owner_stmt, DbResource, user_email=user_email, token_teams=token_teams, team_ids=team_ids, db=db)
        owner_stmt = owner_stmt.order_by(desc(DbResource.created_at), desc(DbResource.id)).limit(1)
        owning_resource = db.execute(owner_stmt).scalar_one_or_none()

        if owning_resource is not None and self._is_federated(owning_resource):
            return await self._forward_completion_upstream(
                getattr(owning_resource, "gateway", None),
                ResourceTemplateReference(type="ref/resource", uri=uri_template),
                {"name": arg_name or "uri", "value": arg_value},
                context,
            )

        # List matching resources visible to caller
        stmt = select(DbResource).where(DbResource.enabled)
        stmt = self._apply_visibility_scope(stmt, DbResource, user_email=user_email, token_teams=token_teams, team_ids=team_ids, db=db)
        resources = db.execute(stmt).scalars().all()

        # Filter by URI pattern
        matches = []
        for resource in resources:
            if arg_value.lower() in resource.uri.lower():
                matches.append(resource.uri)

        return CompleteResult(
            completion={
                "values": matches[:100],
                "total": len(matches),
                "hasMore": len(matches) > 100,
            }
        )

    def register_completions(self, arg_name: str, values: List[str]) -> None:
        """Register custom completion values.

        Args:
            arg_name: Argument name
            values: Completion values

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> service.register_completions('arg1', ['a', 'b'])
            >>> service._custom_completions['arg1']
            ['a', 'b']
            >>> service.register_completions('arg2', ['x', 'y', 'z'])
            >>> len(service._custom_completions)
            2
            >>> service.register_completions('arg1', ['c'])  # Overwrite
            >>> service._custom_completions['arg1']
            ['c']
        """
        self._custom_completions[arg_name] = list(values)

    def unregister_completions(self, arg_name: str) -> None:
        """Unregister custom completion values.

        Args:
            arg_name: Argument name

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> service.register_completions('arg1', ['a', 'b'])
            >>> service.unregister_completions('arg1')
            >>> 'arg1' in service._custom_completions
            False
        """
        self._custom_completions.pop(arg_name, None)
