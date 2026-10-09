# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/mcp_catalog_snapshot.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Bound direct-proxy catalog collection and Redis snapshot storage.
"""

# Standard
from contextlib import asynccontextmanager
import math
from typing import Any, AsyncIterator
import uuid

# Third-Party
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.validation.jsonrpc import JSONRPCError

# Accounting and pages share one eviction unit. Losing accounting also removes every snapshot.
_STATE = r"""
local key = KEYS[1]
local now = tonumber(redis.call('TIME')[1])
local leases = cjson.decode(redis.call('HGET', key, 'leases') or '{}')
local bytes, collectors, count, deadline = 0, 0, 0, now + 1
for id, lease in pairs(leases) do
    if lease[1] <= now then
        redis.call('HDEL', key, id .. ':manifest')
        for page = 0, lease[3] - 1 do
            redis.call('HDEL', key, id .. ':' .. page)
        end
        leases[id] = nil
    else
        bytes = bytes + lease[2]
        count = count + 1
        if lease[3] == -1 then collectors = collectors + 1 end
        deadline = math.max(deadline, lease[1])
    end
end
local function save()
    redis.call('HSET', key, 'leases', cjson.encode(leases))
    redis.call('EXPIREAT', key, deadline)
end
local function headroom(required)
    local info = redis.call('INFO', 'memory')
    local used = tonumber(string.match(info, '\r\nused_memory:(%d+)'))
    local maximum = tonumber(string.match(info, '\r\nmaxmemory:(%d+)'))
    return used and maximum and (maximum == 0 or used + required * 2 + 65536 < maximum * 0.8)
end
"""
_ADMIT = (
    _STATE
    + """
local reserved = tonumber(ARGV[2])
if bytes + reserved > tonumber(ARGV[3]) or collectors >= tonumber(ARGV[4])
    or count >= tonumber(ARGV[5]) or not headroom(reserved) then
    save()
    return 0
end
deadline = math.max(deadline, now + tonumber(ARGV[6]))
leases[ARGV[1]] = {now + tonumber(ARGV[6]), reserved, -1}
save()
return 1
"""
)
_PUBLISH = (
    _STATE
    + """
local id, charge = ARGV[1], tonumber(ARGV[2])
local lease = leases[id]
if not lease or lease[3] ~= -1 or charge > lease[2] or not headroom(charge) then
    save()
    return 0
end
local ttl = tonumber(ARGV[3])
for page = 5, #ARGV do
    redis.call('HSET', key, id .. ':' .. (page - 5), ARGV[page])
end
redis.call('HSET', key, id .. ':manifest', ARGV[4])
leases[id] = {now + ttl, charge, #ARGV - 4}
deadline = math.max(deadline, now + ttl)
save()
return 1
"""
)
_RELEASE = (
    _STATE
    + """
local id = ARGV[1]
local lease = leases[id]
if lease and lease[3] == -1 then leases[id] = nil end
save()
return 1
"""
)
_READ = (
    _STATE
    + """
local lease = leases[ARGV[1]]
save()
if not lease or lease[3] == -1 then return {} end
return {redis.call('HGET', key, ARGV[1] .. ':manifest'),
        redis.call('HGET', key, ARGV[1] .. ':' .. ARGV[2])}
"""
)
_local_collectors: set[str] = set()


def snapshot_key() -> str:
    """Return the shared accounting and snapshot eviction unit."""
    return f"{settings.cache_prefix}mcp-list:snapshots"


@asynccontextmanager
async def reserve_collection(redis: Any) -> AsyncIterator[str]:
    """Reserve collection capacity before contacting an upstream server.

    Args:
        redis: Shared Redis client, or None for single-page operation.

    Yields:
        Unique reservation and snapshot identifier.

    Raises:
        JSONRPCError: If collection admission fails.
    """
    reservation = uuid.uuid4().hex
    if len(_local_collectors) >= settings.mcp_proxy_list_max_collectors:
        raise JSONRPCError(-32000, "MCP proxy catalog collection capacity is exhausted")
    _local_collectors.add(reservation)
    try:
        if redis is not None:
            admitted = await redis.eval(
                _ADMIT,
                1,
                snapshot_key(),
                reservation,
                settings.mcp_proxy_list_max_snapshot_bytes,
                settings.mcp_proxy_list_max_total_bytes,
                settings.mcp_proxy_list_max_collectors,
                settings.mcp_proxy_list_max_snapshots,
                math.ceil(settings.mcpgateway_direct_proxy_timeout) + 30,
            )
            if not admitted:
                raise JSONRPCError(-32000, "MCP proxy catalog snapshot capacity is exhausted")
        yield reservation
    finally:
        _local_collectors.discard(reservation)
        if redis is not None:
            await redis.eval(_RELEASE, 1, snapshot_key(), reservation)


async def publish_snapshot(redis: Any, snapshot: str, scope: str, pages: list[bytes]) -> None:
    """Publish pages only within an active reservation.

    Args:
        redis: Shared Redis client.
        snapshot: Active reservation identifier.
        scope: Authorization fingerprint.
        pages: Serialized catalog pages.

    Raises:
        JSONRPCError: If publication exceeds capacity or loses its reservation.
    """
    manifest = orjson.dumps({"scope": scope, "pages": len(pages)})
    charge = sum(len(page) + 512 for page in pages) + len(manifest) + 512
    if len(pages) > 10000 or charge > settings.mcp_proxy_list_max_snapshot_bytes:
        raise JSONRPCError(-32000, "Direct-proxy MCP catalog exceeds the snapshot byte limit")
    published = await redis.eval(_PUBLISH, 1, snapshot_key(), snapshot, charge, settings.mcp_list_cursor_ttl_seconds, manifest, *pages)
    if not published:
        raise JSONRPCError(-32000, "MCP proxy catalog snapshot reservation is unavailable")


async def read_snapshot(redis: Any, snapshot: str, page: int) -> tuple[Any, Any]:
    """Read a snapshot page and manifest before their fixed expiration.

    Args:
        redis: Shared Redis client.
        snapshot: Snapshot identifier.
        page: Requested page index.

    Returns:
        Manifest and page, or two None values after expiration or eviction.
    """
    result = await redis.eval(_READ, 1, snapshot_key(), snapshot, page)
    return (result[0], result[1]) if len(result) == 2 else (None, None)
