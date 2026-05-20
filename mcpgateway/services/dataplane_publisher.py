# type: ignore
import asyncio
import logging
from pprint import pprint
import orjson
from sqlalchemy import select
from sqlalchemy.orm import joinedload
import msgpack
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, Server, fresh_db_session
from mcpgateway.utils.redis_client import get_redis_client
import json
import hashlib
logger = logging.getLogger(__name__)

USER_CONFIG_KEY = "UserConfig"


def create_virtual_hosts(servers):
    virtual_hosts = {
        str(server.id): {
            "backends": create_backends(server)
        }
        for server in servers
    }
    return virtual_hosts


def create_backends(server):
    return {
        str(tool.id): {
            "name": tool.name or "",
            "originalName": tool.original_name or "",
            "_computedName": tool._computed_name or "",
            "description": tool.description or "",
            "url": str(tool.url) if tool.url else "",
            "pluginChainPost": tool.plugin_chain_post or "",
            "pluginChainPre": tool.plugin_chain_pre or "",
            "requestType": tool.request_type or "STREAMABLEHTTP",
            "integrationType": tool.integration_type or "MCP",
            "exposePassthrough": bool(tool.expose_passthrough),
            "headerMapping": tool.header_mapping or "",
            "headers": tool.headers or "",
            "reachable": "true" if tool.reachable else "false",
            "enabled": "true" if tool.enabled else "false",
            "visibility": tool.visibility or "",
            "teamId": tool.team_id or "",
            "gatewayId": tool.gateway_id or ""
        }
        for tool in getattr(server, "tools", []) or []
    }


class DataplanePublisherService:

    async def start(self):
        self.task = asyncio.create_task(self.publish_to_redis())


    def create_payload(self, users):
        payload = {}
        for user in users:
            key = msgpack.dumps({"UserConfig": user["email"]}, strict_types=True, use_bin_type=True)
            payload[key] = {
                "virtualHosts": create_virtual_hosts(user["servers"])
            }
        return payload

    async def get_data_from_db(self):
        with fresh_db_session() as db:
            result = db.execute(
                select(EmailUser.email, Server)
                .outerjoin(Server, EmailUser.email == Server.owner_email)
                .options(joinedload(Server.tools))
                .where(EmailUser.is_active == True)  # noqa: E712
                .order_by(EmailUser.email, Server.name)
            ).unique().all()

            users_with_servers = {}
            for email, server in result:
                if email not in users_with_servers:
                    users_with_servers[email] = {
                        'email': email,
                        'servers': []
                    }
                if server:
                    users_with_servers[email]['servers'].append(server)
            return list(users_with_servers.values())

    async def publish_to_redis(self):
        if not settings.dataplane_publisher:
            logger.info("Dataplane publisher disabled, skipping Redis sync")
            return

        logger.info("Starting dataplane publisher service")
        while True:
            try:
                redis = await get_redis_client()
                if redis is None:
                    logger.error("Redis client unavailable, retrying in 10 seconds")
                    await asyncio.sleep(10)
                    continue

                users = await self.get_data_from_db()
                logger.debug(f"Retrieved {len(users)} users from database")

                payload = self.create_payload(users)

                pipe = redis.pipeline()
                for email, config in payload.items():
                    pipe.set(
                        email,
                        msgpack.dumps(config, use_bin_type=True),
                        ex=20,
                    )
                await pipe.execute()
                logger.info(f"Published configurations for {len(payload)} users to Redis")

            except Exception as e:
                logger.error(f"Error publishing to Redis: {e}", exc_info=True)

            await asyncio.sleep(15)


    async def remove_user_config(self, user_email):
        if not settings.dataplane_publisher:
            return

        redis = await get_redis_client()
        if redis is None:
            return

        await redis.hdel(USER_CONFIG_KEY, user_email)
        logger.info(f"Removed Redis config for user: {user_email}")
