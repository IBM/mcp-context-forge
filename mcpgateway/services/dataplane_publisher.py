# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Experimental Dataplane publisher service for periodically exporting user configuration to Redis.
NOTE: This publisher backs dataplane wip feature and it is disabled by default.
Be careful not to overfit production-grade assumptions onto the design.
"""

# Standard
import asyncio
from collections import defaultdict
import logging
import os
import socket
from typing import Any, TypedDict

# Third-Party
import msgpack
from sqlalchemy import select

# First-Party
from mcpgateway.db import (
    EmailTeamMember,
    EmailUser,
    fresh_db_session,
)
from mcpgateway.db import (
    server_prompt_association,
    server_resource_association,
    server_tool_association,
)
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)

USER_CONFIG_KEY = "UserConfig"
REDIS_PUBLISHER_TIME = 60  # Publish interval in seconds
# Keys are not deleted explicitly; stale configs expire via Redis TTL.
PUBLISHER_TTL = 70

# Worker ID for multi-worker coordination (same pattern as session_affinity.py)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
PUBLISHER_LOCK_KEY = "mcpgw:dataplane_publisher:lock"


class BackendConfig(TypedDict):
    """Backend gateway configuration for dataplane routing."""

    name: str
    url: str
    transport: str
    passthrough_headers: list[str] | None
    allowed_tool_names: list[str]
    allowed_resource_names: list[str]
    allowed_prompt_names: list[str]


class VirtualHostConfig(TypedDict):
    """Virtual host configuration mapping backend IDs to their configs."""

    backends: dict[str, BackendConfig]


class UserConfig(TypedDict):
    """User-specific configuration mapping virtual host IDs to their configs."""

    virtual_hosts: dict[str, VirtualHostConfig]


BackendItems = dict[str, list[str]]
BackendItemsByServer = dict[str, dict[str, BackendItems]]


class DataplanePublisherService:
    """Publishes user server configurations to Redis for dataplane consumption."""

    def __init__(self) -> None:
        """Initialize the publisher state and dependent services."""
        self.task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background publisher task."""
        if self.task is not None:
            logger.warning("Dataplane publisher is already running.")
            return
        self._shutdown_event.clear()
        self.task = asyncio.create_task(self.publish_to_redis())
        logger.info("Dataplane publisher started.")

    async def shutdown(self) -> None:
        """Gracefully shutdown the publisher."""
        if self.task is None:
            return
        logger.info("Shutting down dataplane publisher.")
        self._shutdown_event.set()
        try:
            await asyncio.wait_for(self.task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning("Dataplane publisher shutdown timed out; cancelling task.")
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        self.task = None
        logger.info("Dataplane publisher stopped.")

    async def fetch_payload(self) -> dict[str, dict[str, dict[str, Any]]] | None:
        """Fetch the payload to publish to Redis. Returns None on error."""
        user_data = await self.get_data_from_db()
        if user_data is None:
            return None
        return self.create_payload(user_data)

    async def publish_to_redis(self) -> None:
        """Continuously publish user configuration payloads to Redis."""
        while not self._shutdown_event.is_set():
            redis = await get_redis_client()
            if redis is None:
                logger.error("Redis client is unavailable; retrying in %s seconds.", REDIS_PUBLISHER_TIME)
                await asyncio.sleep(REDIS_PUBLISHER_TIME)
                continue

            acquired = False
            try:
                # Try to acquire lock (atomic SET NX EX)
                lock_ttl = REDIS_PUBLISHER_TIME + 30  # Lock expires 30s after publish interval
                acquired = await redis.set(
                    PUBLISHER_LOCK_KEY,
                    WORKER_ID,
                    nx=True,  # Only set if not exists
                    ex=lock_ttl,  # Auto-expire if worker crashes
                )

                if not acquired:
                    # Another worker holds the lock - skip this cycle
                    logger.debug("Another worker holds publisher lock, skipping cycle")
                    await asyncio.sleep(REDIS_PUBLISHER_TIME)
                    continue

                # We hold the lock - publish data
                logger.info("Worker %s publishing dataplane payload...", WORKER_ID)
                payload = await self.fetch_payload()

                if payload is None:
                    logger.warning("Skipping publish cycle due to data fetch failure - keeping existing Redis data")
                else:
                    pipe = redis.pipeline()
                    for key, config in payload.items():
                        key = msgpack.dumps((USER_CONFIG_KEY, key), use_bin_type=True)
                        pipe.set(
                            key,
                            msgpack.dumps(config, use_bin_type=True),
                            ex=PUBLISHER_TTL,
                        )
                    try:
                        await pipe.execute()
                        logger.info("Published %d user configs", len(payload))
                    except Exception as e:
                        logger.error("Could not write dataplane payload to Redis: %s", e)
            except Exception as e:
                logger.error("Error during publish: %s", e)
            finally:
                if acquired:
                    # Release lock if we still own it (CAS to prevent stealing)
                    release_script = """
                    if redis.call('GET', KEYS[1]) == ARGV[1] then
                      redis.call('DEL', KEYS[1])
                      return 1
                    end
                    return 0
                    """
                    try:
                        await redis.eval(release_script, 1, PUBLISHER_LOCK_KEY, WORKER_ID)
                    except Exception as e:
                        logger.warning("Failed to release lock: %s", e)

            # Wait for next cycle
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=REDIS_PUBLISHER_TIME)
                break  # Shutdown signaled
            except asyncio.TimeoutError:
                continue

    def create_payload(
        self,
        data: dict[str, dict[str, Any]],
    ) -> dict[str, UserConfig]:
        """
        Build dataplane payload from already-filtered per-user data.
        """

        result: dict[str, UserConfig] = {}

        for user_email, user_data in data.items():
            servers = user_data["servers"]
            gateways = user_data["gateways"]
            prompts = user_data["prompts"]
            resources = user_data["resources"]
            resource_map = {resource["id"]: resource["name"] for resource in resources}

            prompt_map = {prompt["id"]: prompt["name"] for prompt in prompts}

            gateway_base = {
                gateway["id"]: {
                    "name": gateway["name"],
                    "url": gateway["url"],
                    "transport": gateway["transport"],
                    "passthrough_headers": gateway["passthrough_headers"],
                }
                for gateway in gateways
            }

            virtual_hosts: dict[str, VirtualHostConfig] = {}

            for server in servers:
                backends: dict[str, BackendConfig] = {}

                for gateway_id, backend_items in server["backend_items"].items():
                    gateway_config = gateway_base.get(gateway_id)
                    if gateway_config is None:
                        continue

                    allowed_resource_names = [resource_map[resource_id] for resource_id in backend_items["resources"] if resource_id in resource_map]
                    allowed_prompt_names = [prompt_map[prompt_id] for prompt_id in backend_items["prompts"] if prompt_id in prompt_map]
                    if not backend_items["tools"] and not allowed_resource_names and not allowed_prompt_names:
                        continue

                    backends[gateway_id] = {
                        **gateway_config,
                        "allowed_tool_names": backend_items["tools"],
                        "allowed_resource_names": allowed_resource_names,
                        "allowed_prompt_names": allowed_prompt_names,
                    }

                virtual_hosts[server["id"]] = {"backends": backends}

            result[user_email] = {"virtual_hosts": virtual_hosts}

        return result

    async def get_data_from_db(self) -> dict[str, Any] | None:
        """Fetch active users and dataplane data with bulk minimal-column queries."""
        with fresh_db_session() as db:
            try:
                user_rows = db.execute(select(EmailUser.email, EmailUser.is_admin).where(EmailUser.is_active.is_(True))).all()
                userteam_rows = db.execute(select(EmailTeamMember.user_email, EmailTeamMember.team_id).where(EmailTeamMember.is_active.is_(True))).all()

                user_teams_map: dict[str, set[str]] = defaultdict(set)
                user_admin_map: dict[str, bool] = {}
                for user_email, is_admin in user_rows:
                    user_teams_map.setdefault(user_email, set())
                    user_admin_map[user_email] = is_admin

                for user_email, team_id in userteam_rows:
                    if user_email in user_admin_map:
                        user_teams_map[user_email].add(team_id)

                if not user_teams_map:
                    return {}

                server_rows = db.execute(select(DbServer.id, DbServer.owner_email, DbServer.team_id, DbServer.visibility).where(DbServer.enabled.is_(True))).all()
                gateway_rows = db.execute(
                    select(
                        DbGateway.id,
                        DbGateway.name,
                        DbGateway.url,
                        DbGateway.transport,
                        DbGateway.passthrough_headers,
                        DbGateway.owner_email,
                        DbGateway.team_id,
                        DbGateway.visibility,
                    ).where(DbGateway.enabled.is_(True))
                ).all()
                prompt_rows = db.execute(select(DbPrompt.id, DbPrompt.name, DbPrompt.owner_email, DbPrompt.team_id, DbPrompt.visibility).where(DbPrompt.enabled.is_(True))).all()
                resource_rows = db.execute(
                    select(DbResource.id, DbResource.name, DbResource.owner_email, DbResource.team_id, DbResource.visibility).where(
                        DbResource.enabled.is_(True),
                        DbResource.uri_template.is_(None),
                    )
                ).all()
                tool_rows = db.execute(select(DbTool.id, DbTool.name, DbTool.owner_email, DbTool.team_id, DbTool.visibility).where(DbTool.enabled.is_(True))).all()
                backend_items_by_server = self._get_backend_items_by_server(db)

                return {
                    user_email: self._build_user_data(
                        user_email,
                        teams,
                        user_admin_map.get(user_email, False),
                        server_rows,
                        gateway_rows,
                        prompt_rows,
                        resource_rows,
                        tool_rows,
                        backend_items_by_server,
                    )
                    for user_email, teams in user_teams_map.items()
                }

            except Exception as err:
                logger.error("Could not build dataplane payload data from the database: %s", err)
                return None

    def _build_user_data(
        self,
        user_email: str,
        team_ids: set[str],
        is_admin: bool,
        server_rows: list[Any],
        gateway_rows: list[Any],
        prompt_rows: list[Any],
        resource_rows: list[Any],
        tool_rows: list[Any],
        backend_items_by_server: BackendItemsByServer,
    ) -> dict[str, Any]:
        """Build already-filtered dataplane data for one user."""
        tool_name_by_id = {tool.id: tool.name for tool in tool_rows if self._filter_for_user(tool, user_email, team_ids, is_admin=is_admin)}

        return {
            "servers": [
                {
                    "id": server.id,
                    "backend_items": self._filter_backend_items_for_user(backend_items_by_server.get(server.id, {}), tool_name_by_id),
                }
                for server in server_rows
                if self._filter_for_user(server, user_email, team_ids, is_admin=is_admin)
            ],
            "gateways": [
                {
                    "id": gateway.id,
                    "name": gateway.name,
                    "url": gateway.url,
                    "transport": gateway.transport,
                    "passthrough_headers": gateway.passthrough_headers,
                }
                for gateway in gateway_rows
                if self._filter_for_user(gateway, user_email, team_ids, is_admin=is_admin)
            ],
            "prompts": [{"id": prompt.id, "name": prompt.name} for prompt in prompt_rows if self._filter_for_user(prompt, user_email, team_ids, is_admin=is_admin)],
            "resources": [{"id": resource.id, "name": resource.name} for resource in resource_rows if self._filter_for_user(resource, user_email, team_ids, is_admin=is_admin)],
        }

    @staticmethod
    def _filter_for_user(row: Any, user_email: str, team_ids: set[str], is_admin: bool = False) -> bool:
        """Return whether a visibility-scoped row is visible to a dataplane user."""
        if is_admin:
            return True
        visibility = row.visibility
        if visibility == "public":
            return True
        if visibility == "private":
            return row.owner_email == user_email
        return row.team_id in team_ids and visibility == "team"

    @staticmethod
    def _filter_backend_items_for_user(backend_items_by_gateway: dict[str, BackendItems], tool_name_by_id: dict[str, str]) -> dict[str, BackendItems]:
        """Filter backend tool IDs for one user and convert visible tools to names."""
        return {
            gateway_id: {
                "tools": [tool_name_by_id[tool_id] for tool_id in backend_items["tools"] if tool_id in tool_name_by_id],
                "resources": list(backend_items["resources"]),
                "prompts": list(backend_items["prompts"]),
            }
            for gateway_id, backend_items in backend_items_by_gateway.items()
        }

    def _get_backend_items_by_server(self, db: Any) -> BackendItemsByServer:
        """Fetch tools, resources, and prompts grouped by server and backend gateway."""
        backend_items_by_server: BackendItemsByServer = defaultdict(dict)
        self._add_tools_to_backends(db, backend_items_by_server)
        self._add_resources_to_backends(db, backend_items_by_server)
        self._add_prompts_to_backends(db, backend_items_by_server)
        return backend_items_by_server

    def _add_tools_to_backends(self, db: Any, backend_items_by_server: BackendItemsByServer) -> None:
        """Add active server tools to their backend gateway buckets."""
        rows = db.execute(select(server_tool_association.c.server_id, DbTool.id, DbTool.gateway_id).join(DbTool, DbTool.id == server_tool_association.c.tool_id).where(DbTool.enabled.is_(True))).all()
        for server_id, tool_id, gateway_id in rows:
            if gateway_id is None:
                continue
            backend_items = backend_items_by_server[server_id].setdefault(gateway_id, {"tools": [], "resources": [], "prompts": []})
            backend_items["tools"].append(tool_id)

    def _add_resources_to_backends(self, db: Any, backend_items_by_server: BackendItemsByServer) -> None:
        """Add active server resources to their backend gateway buckets."""
        rows = db.execute(
            select(server_resource_association.c.server_id, DbResource.id, DbResource.gateway_id)
            .join(DbResource, DbResource.id == server_resource_association.c.resource_id)
            .where(DbResource.enabled.is_(True))
        ).all()
        for server_id, resource_id, gateway_id in rows:
            if gateway_id is None:
                continue
            backend_items = backend_items_by_server[server_id].setdefault(gateway_id, {"tools": [], "resources": [], "prompts": []})
            backend_items["resources"].append(resource_id)

    def _add_prompts_to_backends(self, db: Any, backend_items_by_server: BackendItemsByServer) -> None:
        """Add active server prompts to their backend gateway buckets."""
        rows = db.execute(
            select(server_prompt_association.c.server_id, DbPrompt.id, DbPrompt.gateway_id).join(DbPrompt, DbPrompt.id == server_prompt_association.c.prompt_id).where(DbPrompt.enabled.is_(True))
        ).all()
        for server_id, prompt_id, gateway_id in rows:
            if gateway_id is None:
                continue
            backend_items = backend_items_by_server[server_id].setdefault(gateway_id, {"tools": [], "resources": [], "prompts": []})
            backend_items["prompts"].append(prompt_id)
