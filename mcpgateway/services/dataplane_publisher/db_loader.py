# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher/db_loader.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Database loader and visibility projector for the dataplane publisher.
"""

# Standard
from collections import defaultdict
import logging

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import (
    EmailTeamMember,
    EmailUser,
    fresh_db_session,
    server_prompt_association,
    server_resource_association,
    server_tool_association,
)
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.dataplane_publisher.dataplane_schema import (
    BackendConfig,
    GatewayBaseConfig,
    ServiceRoute,
    UserConfig,
    VirtualHostConfig,
)
from mcpgateway.services.dataplane_publisher.models import (
    BackendItemsByServer,
    ControlPlaneData,
    UserScope,
    VisibilityIndex,
)

logger = logging.getLogger(__name__)


def load_db_data() -> ControlPlaneData:
    """Read current data in bulk and release the database session."""
    with fresh_db_session() as db:
        users = load_users(db)
        if not users:
            return ControlPlaneData()

        servers = db.execute(select(DbServer.id, DbServer.owner_email, DbServer.team_id, DbServer.visibility).where(DbServer.enabled.is_(True))).all()

        gateways = db.execute(
            select(
                DbGateway.id,
                DbGateway.name,
                DbGateway.url,
                DbGateway.transport,
                DbGateway.passthrough_headers,
                DbGateway.add_headers,
                DbGateway.remove_headers,
                DbGateway.owner_email,
                DbGateway.team_id,
                DbGateway.visibility,
                DbGateway.capabilities,
            ).where(DbGateway.enabled.is_(True))
        ).all()

        prompts = db.execute(select(DbPrompt.id, DbPrompt.name, DbPrompt.original_name, DbPrompt.owner_email, DbPrompt.team_id, DbPrompt.visibility).where(DbPrompt.enabled.is_(True))).all()

        resources = db.execute(
            select(DbResource.id, DbResource.name, DbResource.uri, DbResource.owner_email, DbResource.team_id, DbResource.visibility).where(
                DbResource.enabled.is_(True), DbResource.uri_template.is_(None)
            )
        ).all()

        tools = db.execute(select(DbTool.id, DbTool.name, DbTool.original_name, DbTool.input_schema, DbTool.owner_email, DbTool.team_id, DbTool.visibility).where(DbTool.enabled.is_(True))).all()

        backend_items = load_backend_items(db)

    return ControlPlaneData(
        users=users,
        servers=VisibilityIndex.build(servers),
        gateways=VisibilityIndex.build(gateways),
        tools=VisibilityIndex.build(tools),
        prompts=VisibilityIndex.build(prompts),
        resources=VisibilityIndex.build(resources),
        backend_items=backend_items,
    )


def load_users(db: Session) -> tuple[UserScope, ...]:
    """Load active users and their active memberships"""
    users = db.execute(select(EmailUser.id, EmailUser.email, EmailUser.is_admin).where(EmailUser.is_active.is_(True))).all()

    memberships = db.execute(select(EmailTeamMember.user_email, EmailTeamMember.team_id).where(EmailTeamMember.is_active.is_(True))).all()
    teams_by_email: dict[str, set[str]] = defaultdict(set)

    for email, team_id in memberships:
        teams_by_email[email].add(team_id)

    return tuple(UserScope(id=str(user_id), email=email, is_admin=is_admin, team_ids=frozenset(teams_by_email[email])) for user_id, email, is_admin in users)


def load_backend_items(db: Session) -> BackendItemsByServer:
    """
    Read active resource associations and
    return resource IDs grouped by server and gateway
    """
    result: BackendItemsByServer = {}

    # server_tool_association is a table in DB
    associations = [
        ("tools", server_tool_association, DbTool, server_tool_association.columns.tool_id),
        ("resources", server_resource_association, DbResource, server_resource_association.columns.resource_id),
        ("prompts", server_prompt_association, DbPrompt, server_prompt_association.columns.prompt_id),
    ]
    for kind, association, model, item_id_column in associations:
        rows = db.execute(select(association.columns.server_id, model.id, model.gateway_id).join(model, model.id == item_id_column).where(model.enabled.is_(True))).all()

        for server_id, item_id, gateway_id in rows:
            if gateway_id is not None:
                backend = result.setdefault(server_id, {}).setdefault(gateway_id, {"tools": [], "resources": [], "prompts": []})
                backend[kind].append(item_id)
    return result


def get_user_configs() -> dict[str, UserConfig]:
    """Build UserConfig records keyed by active user UUID."""
    return UserConfigBuilder(load_db_data()).build_payload()


def add_unique_route(routes: dict[str, ServiceRoute], ambiguous: set[str], name: str, gateway_id: str, upstream_name: str, server_id: str, route_kind: str) -> None:
    """Exclude conflicting routes for the entire virtual host.

    Args:
        routes: Current route map.
        ambiguous: Names already excluded by a conflict.
        name: Exposed route name.
        gateway_id: Backend identity.
        upstream_name: Original upstream identifier.
        server_id: Virtual server identity for diagnostics.
        route_kind: Resource category for diagnostics.
    """
    if name in ambiguous:
        return
    target: ServiceRoute = {"backend_name": gateway_id, "upstream_name": upstream_name}
    previous = routes.get(name)
    if previous is not None and previous != target:
        del routes[name]
        ambiguous.add(name)
        logger.warning("Omitting ambiguous dataplane %s route %r on virtual host %s", route_kind, name, server_id)
        return
    routes[name] = target


class UserConfigBuilder:
    """Prepare shared metadata once and build configurations from visible server associations.

    Treat db_data and shared nested metadata as read-only until encoding completes.
    """

    def __init__(self, db_data: ControlPlaneData) -> None:
        """Prepare reusable metadata for one publication cycle.

        Args:
            db_data: Detached resource indexes and active users.
        """
        self.db_data = db_data
        self.gateway_configs_by_id: dict[str, GatewayBaseConfig] = {
            gateway.id: {
                "name": gateway.name,
                "url": gateway.url,
                "mcp_protocol_version": "",
                "passthrough_headers": gateway.passthrough_headers or [],
                "add_headers": gateway.add_headers or {},
                "remove_headers": gateway.remove_headers or [],
                "completion": {},
                "capabilities": gateway.capabilities or {},
            }
            for gateway in db_data.gateways.rows_by_id.values()
            if (gateway.transport or "").upper() == "STREAMABLEHTTP"
        }
        self.valid_tools_by_id = {}
        for tool in db_data.tools.rows_by_id.values():
            if isinstance(tool.input_schema, dict):
                self.valid_tools_by_id[tool.id] = tool
            else:
                logger.warning("Excluding tool %s from the dataplane db_data because its input schema is not an object", tool.id)
        self.resource_uris_by_id = {resource.id: resource.uri for resource in db_data.resources.rows_by_id.values() if resource.uri}

    def build_user_config(self, user: UserScope) -> UserConfig:
        """Build one user configuration through indexed visibility.

        Args:
            user: User identity and memberships.

        Returns:
            Routing configuration for the user.
        """
        visible_gateway_ids = self.db_data.gateways.visible_ids(user)
        visible_tool_ids = self.db_data.tools.visible_ids(user)
        visible_prompt_ids = self.db_data.prompts.visible_ids(user)
        visible_resource_ids = self.db_data.resources.visible_ids(user)
        virtual_hosts: dict[str, VirtualHostConfig] = {}
        for server_id in sorted(self.db_data.servers.visible_ids(user)):
            host = self.build_virtual_host(server_id, visible_gateway_ids, visible_tool_ids, visible_prompt_ids, visible_resource_ids)
            if host is not None:
                virtual_hosts[server_id] = host
        return {"virtual_hosts": virtual_hosts}

    def build_virtual_host(self, server_id: str, visible_gateway_ids: set[str], visible_tool_ids: set[str], visible_prompt_ids: set[str], visible_resource_ids: set[str]) -> VirtualHostConfig | None:
        """Build routes directly from a visible server's db_data associations.

        Args:
            server_id: Visible virtual server identity.
            visible_gateway_ids: Gateway IDs visible to the user.
            visible_tool_ids: Tool IDs visible to the user.
            visible_prompt_ids: Prompt IDs visible to the user.
            visible_resource_ids: Resource IDs visible to the user.

        Returns:
            Virtual host configuration, or None when no backend has publishable items.
        """
        backends: dict[str, BackendConfig] = {}
        tool_routes: dict[str, ServiceRoute] = {}
        resource_routes: dict[str, ServiceRoute] = {}
        prompt_routes: dict[str, ServiceRoute] = {}
        ambiguous_tools: set[str] = set()
        ambiguous_resources: set[str] = set()
        ambiguous_prompts: set[str] = set()
        for gateway_id, items in self.db_data.backend_items.get(server_id, {}).items():
            if gateway_id not in visible_gateway_ids or gateway_id not in self.gateway_configs_by_id:
                continue
            tools = [self.valid_tools_by_id[tool_id] for tool_id in items["tools"] if tool_id in visible_tool_ids and tool_id in self.valid_tools_by_id]
            prompts = [self.db_data.prompts.rows_by_id[prompt_id] for prompt_id in items["prompts"] if prompt_id in visible_prompt_ids]
            uris = [self.resource_uris_by_id[resource_id] for resource_id in items["resources"] if resource_id in visible_resource_ids and resource_id in self.resource_uris_by_id]
            if not tools and not prompts and not uris:
                continue
            backends[gateway_id] = {**self.gateway_configs_by_id[gateway_id], "tool_schemas": {tool.original_name: tool.input_schema for tool in tools}}
            upstream_tool_names_by_name = {tool.name: tool.original_name for tool in tools}
            for name, original_name in upstream_tool_names_by_name.items():
                add_unique_route(tool_routes, ambiguous_tools, name, gateway_id, original_name, server_id, "tool")
            for uri in uris:
                add_unique_route(resource_routes, ambiguous_resources, uri, gateway_id, uri, server_id, "resource")
            for prompt in prompts:
                add_unique_route(prompt_routes, ambiguous_prompts, prompt.name, gateway_id, prompt.original_name, server_id, "prompt")
        if not backends:
            return None
        return {"backends": backends, "tools": tool_routes, "resources": resource_routes, "resource_templates": {}, "prompts": prompt_routes}

    def build_payload(self) -> dict[str, UserConfig]:
        """Build configurations for every active user using shared resource metadata."""
        return {user.id: self.build_user_config(user) for user in self.db_data.users}
