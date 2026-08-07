# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/issue_5247/manual/register_local_gateway.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Register a gateway pointed at a local mock MCP server for e2e scenarios 2 and 3a (#5247).

The real HTTP registration endpoint correctly enforces SSRF protection and rejects any
localhost/private-network URL (verified directly against SecurityValidator.validate_url --
this is a deliberate, working security control, not a bug). To point a scenario at a
locally-run mock MCP server, this script calls the real GatewayService.register_gateway()
business logic directly with a GatewayCreate built via model_construct() (bypasses only the
Pydantic field validators, not the service's own encryption/discovery/DB logic). Everything
downstream of registration -- and the actual POST /gateways/{id}/tools/refresh call this PR
fixes -- goes through the unmodified, real public HTTP endpoint in run_e2e.py.

Usage: register_local_gateway.py <name> <url> <auth_type> <auth_json>
  auth_type: "oauth" -> auth_json is the oauth_config dict
  auth_type: "basic" -> auth_json is {"username": ..., "password": ...}
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # tests/e2e/issue_5247/manual/ -> repo root

from mcpgateway.db import SessionLocal  # noqa: E402
from mcpgateway.schemas import GatewayCreate  # noqa: E402
from mcpgateway.services.gateway_service import GatewayService  # noqa: E402


async def main():
    name = sys.argv[1]
    url = sys.argv[2]
    auth_type = sys.argv[3]
    auth_json = json.loads(sys.argv[4])

    kwargs = dict(
        name=name,
        url=url,
        description=None,
        transport="SSE",
        passthrough_headers=None,
        auth_type=auth_type,
        auth_username=None,
        auth_password=None,
        auth_token=None,
        auth_header_key=None,
        auth_header_value=None,
        auth_headers=None,
        oauth_config=None,
        auth_query_param_key=None,
        auth_query_param_value=None,
        auth_value=None,
        one_time_auth=False,
    )
    if auth_type == "oauth":
        kwargs["oauth_config"] = auth_json
    elif auth_type == "basic":
        kwargs["auth_username"] = auth_json["username"]
        kwargs["auth_password"] = auth_json["password"]

    gateway = GatewayCreate.model_construct(**kwargs)

    db = SessionLocal()
    try:
        service = GatewayService()
        created = await service.register_gateway(
            db,
            gateway,
            created_by="admin@example.com",
            created_via="api",
            visibility="public",
        )
        print(json.dumps({"id": created.id, "name": created.name}))
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
