"""Typed, deterministic Praxis source snapshots from ContextForge state."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from typing import assert_never
from urllib.parse import parse_qsl, urlsplit

from cpex.framework.models import Config
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mcpgateway.db import Gateway, PraxisTarget, PraxisTargetServer, Prompt, Resource, Server, Tool, ToolPluginBinding, server_prompt_association, server_resource_association, server_tool_association
from mcpgateway.plugins.binding_compiler import BindingCompilationError, BindingCompilationInput, BindingSource, ToolBinding, compile_tool_bindings
from mcpgateway.services._praxis_source_types import ServerGraph as _ServerGraph, SourceRefusal as _SourceRefusal, ToolContext as _ToolContext
from mcpgateway.services.praxis_config_models import PraxisConfigSourceSnapshot, PraxisGatewaySource, PraxisPromptSource, PraxisResourceSource, PraxisServerSource
from mcpgateway.services.praxis_config_models import PraxisSourceError, PraxisSourceErrorCode, PraxisSourceStatus, PraxisToolRuntimeOverrides, PraxisToolSource
from mcpgateway.utils.header_filtering import filter_sensitive_headers
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS


class PraxisConfigSourceService:
    """Assemble source state in one backend-specific consistent read transaction."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        operator_config: Config,
        runtime_overrides: tuple[PraxisToolRuntimeOverrides, ...] = (),
    ) -> None:
        """Store the database and compiler inputs used for each fresh snapshot."""
        self._session_factory = session_factory
        self._operator_config = operator_config
        grouped_overrides = defaultdict(list)
        for observation in runtime_overrides:
            grouped_overrides[(observation.scope, observation.tool_name)].extend(observation.overrides)
        self._runtime_overrides = {
            key: tuple(sorted(values, key=lambda item: (item.plugin_id, item.redis_mode or "", item.local_mode or ""))) for key, values in grouped_overrides.items()
        }

    def snapshot(self, target_id: str) -> PraxisConfigSourceSnapshot:
        """Read and validate one target's complete representable source state."""
        outcome = self._read_snapshot(target_id)
        match outcome:
            case PraxisConfigSourceSnapshot():
                return outcome
            case PraxisSourceErrorCode():
                raise PraxisSourceError(outcome) from None
            case unreachable:
                assert_never(unreachable)

    def snapshot_in_session(self, session: Session, target_id: str) -> PraxisConfigSourceSnapshot:
        """Validate assignment state inside its caller-owned transaction."""
        try:
            return self._assemble(session, target_id)
        except _SourceRefusal as error:
            raise PraxisSourceError(error.code) from None
        except (BindingCompilationError, ValidationError, TypeError):
            raise PraxisSourceError(PraxisSourceErrorCode.INVALID_SOURCE) from None

    def _read_snapshot(self, target_id: str) -> PraxisConfigSourceSnapshot | PraxisSourceErrorCode:
        with self._session_factory() as session:
            dialect = session.get_bind().dialect.name
            begin = "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ" if dialect == "postgresql" else "BEGIN"
            session.execute(text(begin))
            try:
                snapshot = self._assemble(session, target_id)
            except _SourceRefusal as error:
                session.rollback()
                return error.code
            except (BindingCompilationError, ValidationError, TypeError):
                session.rollback()
                return PraxisSourceErrorCode.INVALID_SOURCE
            session.commit()
            return snapshot

    def shadow_status(self, target_id: str) -> PraxisSourceStatus:
        """Return a sanitized representability result without weakening render refusal."""
        try:
            snapshot = self.snapshot(target_id)
        except PraxisSourceError as error:
            return PraxisSourceStatus(target_id=target_id, representable=False, reasons=(error.code,))
        return PraxisSourceStatus(target_id=target_id, representable=True, source_fingerprint=snapshot.source_fingerprint)

    def _assemble(self, session: Session, target_id: str) -> PraxisConfigSourceSnapshot:
        if session.get(PraxisTarget, target_id) is None:
            raise _SourceRefusal(PraxisSourceErrorCode.TARGET_NOT_FOUND)
        assignment_rows = session.execute(
            select(PraxisTargetServer.server_id, Server).outerjoin(Server, Server.id == PraxisTargetServer.server_id).where(PraxisTargetServer.target_id == target_id)
        ).all()
        if any(server is None for _, server in assignment_rows):
            raise _SourceRefusal(PraxisSourceErrorCode.DANGLING_ASSOCIATION)
        servers = [server for _, server in assignment_rows if server is not None and server.enabled]
        server_ids = tuple(server.id for server in servers)
        tool_rows = session.execute(
            select(server_tool_association.c.server_id, Tool).outerjoin(Tool, Tool.id == server_tool_association.c.tool_id).where(server_tool_association.c.server_id.in_(server_ids))
        ).all()
        resource_rows = session.execute(
            select(server_resource_association.c.server_id, Resource).outerjoin(Resource, Resource.id == server_resource_association.c.resource_id).where(server_resource_association.c.server_id.in_(server_ids))
        ).all()
        prompt_rows = session.execute(
            select(server_prompt_association.c.server_id, Prompt).outerjoin(Prompt, Prompt.id == server_prompt_association.c.prompt_id).where(server_prompt_association.c.server_id.in_(server_ids))
        ).all()
        if any(entity is None for rows in (tool_rows, resource_rows, prompt_rows) for _, entity in rows):
            raise _SourceRefusal(PraxisSourceErrorCode.DANGLING_ASSOCIATION)

        tools_by_server: dict[str, list[Tool]] = defaultdict(list)
        resources_by_server: dict[str, list[Resource]] = defaultdict(list)
        prompts_by_server: dict[str, list[Prompt]] = defaultdict(list)
        for server_id, tool in tool_rows:
            if tool is not None and tool.enabled:
                tools_by_server[server_id].append(tool)
        for server_id, resource in resource_rows:
            if resource is not None and resource.enabled:
                resources_by_server[server_id].append(resource)
        for server_id, prompt in prompt_rows:
            if prompt is not None and prompt.enabled:
                prompts_by_server[server_id].append(prompt)

        entities = [*tools_by_server.values(), *resources_by_server.values(), *prompts_by_server.values()]
        gateway_ids = {entity.gateway_id for group in entities for entity in group if entity.gateway_id is not None}
        gateways = {gateway.id: gateway for gateway in session.scalars(select(Gateway).where(Gateway.id.in_(gateway_ids))).all()}
        if gateways.keys() != gateway_ids:
            raise _SourceRefusal(PraxisSourceErrorCode.DANGLING_ASSOCIATION)

        sources = tuple(
            self._server_source(session, _ServerGraph(server, gateways, tools_by_server[server.id], resources_by_server[server.id], prompts_by_server[server.id]))
            for server in sorted(servers, key=lambda item: item.id)
        )
        canonical = json.dumps({"target_id": target_id, "servers": [source.model_dump(mode="json") for source in sources]}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        return PraxisConfigSourceSnapshot(target_id=target_id, source_fingerprint=hashlib.sha256(canonical).hexdigest(), servers=sources)

    def _server_source(
        self,
        session: Session,
        graph: _ServerGraph,
    ) -> PraxisServerSource:
        server, gateways, tools, resources, prompts = graph.server, graph.gateways, graph.tools, graph.resources, graph.prompts
        scope = self._scope(server.visibility, server.team_id)
        if server.oauth_enabled or server.oauth_config:
            raise _SourceRefusal(PraxisSourceErrorCode.OAUTH_MATERIAL)
        for entity in (*tools, *resources, *prompts):
            self._assert_scope(entity.visibility, entity.team_id, scope)
        all_tool_sources = {tool.id: self._tool_source(_ToolContext(session, tool, scope)) for tool in sorted(tools, key=lambda item: item.id)}
        referenced = {entity.gateway_id for entity in (*tools, *resources, *prompts) if entity.gateway_id is not None}
        publishable: dict[str, Gateway] = {}
        for gateway_id in sorted(referenced):
            gateway = gateways[gateway_id]
            self._assert_scope(gateway.visibility, gateway.team_id, scope)
            self._assert_gateway_safe(gateway)
            if gateway.enabled and gateway.transport.upper() == "STREAMABLEHTTP":
                publishable[gateway.id] = gateway
        tool_sources = tuple(all_tool_sources[tool.id] for tool in sorted(tools, key=lambda item: item.id) if tool.gateway_id in publishable)
        resource_sources = tuple(
            PraxisResourceSource(id=item.id, name=item.name, uri=item.uri, gateway_id=item.gateway_id or "")
            for item in sorted(resources, key=lambda entity: entity.id)
            if item.gateway_id in publishable
        )
        prompt_sources = tuple(
            PraxisPromptSource(id=item.id, name=item.name, gateway_id=item.gateway_id or "")
            for item in sorted(prompts, key=lambda entity: entity.id)
            if item.gateway_id in publishable
        )
        used_gateway_ids = {item.gateway_id for item in (*tool_sources, *resource_sources, *prompt_sources)}
        gateway_sources = tuple(self._gateway_source(publishable[gateway_id]) for gateway_id in sorted(used_gateway_ids))
        return PraxisServerSource(id=server.id, name=server.name, scope=scope, gateways=gateway_sources, tools=tool_sources, resources=resource_sources, prompts=prompt_sources)

    def _tool_source(self, context: _ToolContext) -> PraxisToolSource:
        session, tool, scope = context.session, context.tool, context.scope
        if tool.auth_type or tool.auth_value:
            raise _SourceRefusal(PraxisSourceErrorCode.AUTH_MATERIAL)
        headers = tool.headers or {}
        if filter_sensitive_headers(headers) != headers:
            raise _SourceRefusal(PraxisSourceErrorCode.SECRET_HEADER)
        if tool.plugin_chain_pre or tool.plugin_chain_post:
            raise _SourceRefusal(PraxisSourceErrorCode.RUNTIME_OVERRIDE)
        binding_rows = session.scalars(
            select(ToolPluginBinding).where(ToolPluginBinding.team_id == scope, ToolPluginBinding.tool_name.in_((tool.original_name, "*")))
        ).all() if scope != "platform" else []
        try:
            bindings = tuple(
                ToolBinding(plugin_id=row.plugin_id, tool_name=row.tool_name, mode=row.mode, priority=row.priority, config=row.config, on_error=row.on_error, source=BindingSource.TOOL)
                for row in binding_rows
            )
            compiled = compile_tool_bindings(
                BindingCompilationInput(
                    operator_config=self._operator_config,
                    tool_name=tool.original_name,
                    bindings=bindings,
                    runtime_overrides=self._runtime_overrides.get((scope, tool.original_name), ()),
                )
            )
        except BindingCompilationError:
            source_error = _SourceRefusal(PraxisSourceErrorCode.RUNTIME_OVERRIDE if self._runtime_overrides.get((scope, tool.original_name)) else PraxisSourceErrorCode.INVALID_BINDING)
        except ValidationError:
            source_error = _SourceRefusal(PraxisSourceErrorCode.INVALID_BINDING)
        else:
            return PraxisToolSource(id=tool.id, name=tool.original_name, gateway_id=tool.gateway_id or "", headers=headers, compiled_config=compiled)
        raise source_error from None

    @staticmethod
    def _scope(visibility: str, team_id: str | None) -> str:
        if visibility == "private":
            raise _SourceRefusal(PraxisSourceErrorCode.OWNER_PRIVATE)
        if visibility == "team":
            if team_id is None:
                raise _SourceRefusal(PraxisSourceErrorCode.SCOPE_MISMATCH)
            return team_id
        return "platform"

    @staticmethod
    def _assert_scope(visibility: str, team_id: str | None, server_scope: str) -> None:
        entity_scope = PraxisConfigSourceService._scope(visibility, team_id)
        if entity_scope not in ("platform", server_scope):
            raise _SourceRefusal(PraxisSourceErrorCode.SCOPE_MISMATCH)

    @staticmethod
    def _assert_gateway_safe(gateway: Gateway) -> None:
        parsed = urlsplit(gateway.url)
        if parsed.username is not None or parsed.password is not None:
            raise _SourceRefusal(PraxisSourceErrorCode.URL_USERINFO)
        if any(name.casefold() in STATIC_SENSITIVE_PARAMS or name in STATIC_SENSITIVE_PARAMS for name, _ in parse_qsl(parsed.query, keep_blank_values=True)) or gateway.auth_query_params:
            raise _SourceRefusal(PraxisSourceErrorCode.CREDENTIAL_QUERY)
        if gateway.auth_type or gateway.auth_value:
            raise _SourceRefusal(PraxisSourceErrorCode.AUTH_MATERIAL)
        if gateway.oauth_config:
            raise _SourceRefusal(PraxisSourceErrorCode.OAUTH_MATERIAL)
        if gateway.client_cert or gateway.client_key:
            raise _SourceRefusal(PraxisSourceErrorCode.KEY_MATERIAL)
        if filter_sensitive_headers(gateway.add_headers or {}) != (gateway.add_headers or {}):
            raise _SourceRefusal(PraxisSourceErrorCode.SECRET_HEADER)
        if gateway.gateway_mode != "cache" or gateway.identity_propagation:
            raise _SourceRefusal(PraxisSourceErrorCode.RUNTIME_OVERRIDE)

    @staticmethod
    def _gateway_source(gateway: Gateway) -> PraxisGatewaySource:
        return PraxisGatewaySource(
            id=gateway.id,
            name=gateway.name,
            url=gateway.url,
            transport="STREAMABLEHTTP",
            passthrough_headers=tuple(sorted(gateway.passthrough_headers or ())),
            add_headers=dict(sorted((gateway.add_headers or {}).items())),
            remove_headers=tuple(sorted(gateway.remove_headers or ())),
            capabilities=gateway.capabilities or {},
        )


__all__ = (
    "PraxisConfigSourceService",
    "PraxisConfigSourceSnapshot",
    "PraxisGatewaySource",
    "PraxisPromptSource",
    "PraxisResourceSource",
    "PraxisServerSource",
    "PraxisSourceError",
    "PraxisSourceErrorCode",
    "PraxisSourceStatus",
    "PraxisToolRuntimeOverrides",
    "PraxisToolSource",
)
