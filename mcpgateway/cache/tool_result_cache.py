# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/tool_result_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Opt-in cache for successful, read-only tool invocation results.

The cache is deliberately separate from the tool lookup cache: lookup entries
contain tool configuration, while entries here contain upstream data.  Results
are isolated by caller and request context, stored in a bounded process-local
LRU, and optionally mirrored to Redis for multi-worker deployments.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import logging
import threading
import time
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence

# Third-Party
import orjson

# First-Party
from mcpgateway.common.models import ToolResult

logger = logging.getLogger(__name__)


RESULT_CACHE_ANNOTATION = "x-contextforge-result-cache"
RESULT_CACHE_META_KEY = "io.contextforge/result-cache"


@dataclass(frozen=True)
class ResultCachePolicy:
    """Resolved cache policy for one invocation."""

    enabled: bool
    ttl_seconds: int = 0
    reason: str = "disabled"


@dataclass(frozen=True)
class CachedToolResult:
    """A validated cache hit and its observability metadata."""

    result: ToolResult
    age_seconds: float
    source: str


@dataclass
class _Entry:
    """Serialized result stored in the local LRU."""

    tool_id: str
    gateway_id: Optional[str]
    sql_table_ids: tuple[str, ...]
    payload: bytes
    created_at: float
    expires_at: float


@dataclass
class _Flight:
    """Per-event-loop single-flight lock with a user reference count."""

    lock: asyncio.Lock
    users: int = 0


def _annotation_mapping(annotations: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """Return the namespaced result-cache annotation when it is a mapping."""
    raw = annotations.get(RESULT_CACHE_ANNOTATION)
    return raw if isinstance(raw, Mapping) else None


def resolve_result_cache_policy(
    *,
    globally_enabled: bool,
    annotations: Mapping[str, Any],
    integration_type: Optional[str],
    request_type: Optional[str],
    source_operation: Optional[str],
    meta_data: Optional[Mapping[str, Any]],
    has_tool_plugins: bool,
    default_ttl_seconds: int,
    max_ttl_seconds: int,
) -> ResultCachePolicy:
    """Resolve a fail-closed cache policy for a tool invocation.

    Caching requires both the global feature flag and an explicit per-tool
    annotation.  The MCP ``readOnlyHint`` is treated as a safety assertion,
    not inferred from a tool name.  REST writes, governed SQL writes, streaming
    gRPC methods, and calls with tool hooks are never cached.
    """
    if not globally_enabled:
        return ResultCachePolicy(False, reason="globally-disabled")

    config = _annotation_mapping(annotations)
    if config is None or config.get("enabled") is not True:
        return ResultCachePolicy(False, reason="not-opted-in")
    if annotations.get("readOnlyHint") is not True:
        return ResultCachePolicy(False, reason="not-read-only")
    if annotations.get("destructiveHint") is True:
        return ResultCachePolicy(False, reason="destructive")
    if has_tool_plugins:
        # A hit must never bypass authorization, transformation, redaction, or
        # audit logic implemented by a pre/post tool hook.
        return ResultCachePolicy(False, reason="tool-plugins-active")

    normalized_integration = (integration_type or "").upper()
    if normalized_integration == "REST" and (request_type or "").upper() != "GET":
        return ResultCachePolicy(False, reason="rest-write")
    if normalized_integration == "SQL" and (source_operation or "").lower() != "query":
        return ResultCachePolicy(False, reason="sql-write")
    if normalized_integration not in {"REST", "MCP", "GRPC", "SQL"}:
        return ResultCachePolicy(False, reason="unsupported-integration")

    if annotations.get("x-grpc-server-streaming") is True or annotations.get("x-grpc-client-streaming") is True:
        return ResultCachePolicy(False, reason="streaming")
    if meta_data and callable(meta_data.get("grpc_stream_callback")):
        return ResultCachePolicy(False, reason="streaming")

    raw_ttl = config.get("ttlSeconds", default_ttl_seconds)
    if isinstance(raw_ttl, bool) or not isinstance(raw_ttl, int) or raw_ttl <= 0:
        return ResultCachePolicy(False, reason="invalid-ttl")
    return ResultCachePolicy(True, ttl_seconds=min(raw_ttl, max_ttl_seconds), reason="eligible")


def _canonical_digest(value: Mapping[str, Any]) -> Optional[str]:
    """Hash JSON-compatible key material without retaining its sensitive values."""
    try:
        encoded = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    except (TypeError, ValueError, orjson.JSONEncodeError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def build_result_cache_key(
    *,
    tool_id: str,
    tool_version: Any,
    arguments: Mapping[str, Any],
    app_user_email: Optional[str],
    user_email: Optional[str],
    token_teams: Optional[Sequence[str]],
    server_id: Optional[str],
    request_headers: Optional[Mapping[str, str]],
    meta_data: Optional[Mapping[str, Any]],
    runtime_config: Mapping[str, Any],
) -> Optional[str]:
    """Build a stable, tenant-safe key for a tool result.

    The returned value is only a SHA-256 digest; raw arguments, headers,
    credentials, identities, and metadata are never embedded in Redis keys.
    Volatile tracing fields are omitted because they do not change semantics.
    """
    if not tool_id:
        return None

    stable_meta: Dict[str, Any] = {}
    for key, value in (meta_data or {}).items():
        if key not in {"traceparent", "tracestate", "grpc_stream_callback"}:
            stable_meta[str(key)] = value

    stable_headers = {
        str(key).lower(): value for key, value in (request_headers or {}).items() if str(key).lower() not in {"traceparent", "tracestate", "x-correlation-id", "mcp-session-id", "x-mcp-session-id"}
    }
    material = {
        "schema": 1,
        "tool": {"id": tool_id, "version": tool_version},
        "arguments": arguments,
        # Team membership is set-like authorization context. Canonicalizing the
        # sequence avoids unnecessary misses when equivalent JWTs list teams in
        # a different order, while preserving the security-significant
        # distinction between ``None`` (admin bypass) and ``[]`` (public-only).
        "principal": {
            "app_user_email": app_user_email,
            "user_email": user_email,
            "teams": sorted(set(token_teams)) if token_teams is not None else None,
        },
        "server_id": server_id,
        "request_headers": stable_headers,
        "meta": stable_meta,
        "runtime": runtime_config,
    }
    digest = _canonical_digest(material)
    return f"v1:{tool_id}:{digest}" if digest else None


def with_result_cache_metadata(result: ToolResult, *, hit: bool, source: str, age_seconds: float = 0.0, ttl_seconds: Optional[int] = None) -> ToolResult:
    """Return a copy of ``result`` annotated with cache observability metadata."""
    # Avoid a serialization round trip here. Cache instrumentation is
    # best-effort and must not turn an otherwise valid upstream invocation into
    # an error merely because an extension placed a non-JSON object in _meta.
    cloned = result.model_copy(deep=True)
    result_meta = dict(cloned.meta or {})
    cache_meta: Dict[str, Any] = {
        "hit": hit,
        "source": source,
        "ageMs": max(0, round(age_seconds * 1000, 3)),
    }
    if ttl_seconds is not None:
        cache_meta["ttlSeconds"] = ttl_seconds
    result_meta[RESULT_CACHE_META_KEY] = cache_meta
    cloned.meta = result_meta
    return cloned


class ToolResultCache:
    """Bounded L1 result cache with optional Redis L2 and local single-flight."""

    def __init__(self) -> None:
        """Initialize cache configuration and process-local state."""
        try:
            # First-Party
            from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

            self._enabled = getattr(settings, "tool_result_cache_enabled", False)
            self._default_ttl_seconds = getattr(settings, "tool_result_cache_default_ttl_seconds", 60)
            self._max_ttl_seconds = getattr(settings, "tool_result_cache_max_ttl_seconds", 3600)
            self._l1_max_entries = getattr(settings, "tool_result_cache_l1_max_entries", 1000)
            self._l1_max_bytes = getattr(settings, "tool_result_cache_l1_max_bytes", 67_108_864)
            self._max_entry_bytes = getattr(settings, "tool_result_cache_max_entry_bytes", 1_048_576)
            self._l2_enabled = getattr(settings, "tool_result_cache_l2_enabled", True) and settings.cache_type == "redis"
            self._cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        except ImportError:
            self._enabled = False
            self._default_ttl_seconds = 60
            self._max_ttl_seconds = 3600
            self._l1_max_entries = 1000
            self._l1_max_bytes = 67_108_864
            self._max_entry_bytes = 1_048_576
            self._l2_enabled = False
            self._cache_prefix = "mcpgw:"

        self._cache: "OrderedDict[str, _Entry]" = OrderedDict()
        self._l1_bytes = 0
        self._lock = threading.Lock()
        self._flights: Dict[tuple[int, str], _Flight] = {}
        self._flight_lock = threading.Lock()
        self._sql_generations: Dict[str, int] = {}
        self._redis_checked = False
        self._redis_available = False
        self._stats: Dict[str, int] = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "stores": 0,
            "evictions": 0,
            "oversize_skips": 0,
            "encode_errors": 0,
            "decode_errors": 0,
            "invalidations": 0,
        }

    @property
    def enabled(self) -> bool:
        """Return whether result caching is globally enabled."""
        return self._enabled

    @property
    def default_ttl_seconds(self) -> int:
        """Return the default per-entry TTL."""
        return self._default_ttl_seconds

    @property
    def max_ttl_seconds(self) -> int:
        """Return the configured per-entry TTL ceiling."""
        return self._max_ttl_seconds

    def _redis_key(self, key: str) -> str:
        return f"{self._cache_prefix}tool_result:{key}"

    def _tool_index_key(self, tool_id: str) -> str:
        return f"{self._cache_prefix}tool_result:index:tool:{tool_id}"

    def _gateway_index_key(self, gateway_id: str) -> str:
        return f"{self._cache_prefix}tool_result:index:gateway:{gateway_id}"

    def _sql_table_index_key(self, sql_table_id: str) -> str:
        return f"{self._cache_prefix}tool_result:index:sql_table:{sql_table_id}"

    def _sql_generation_key(self, sql_table_id: str) -> str:
        return f"{self._cache_prefix}tool_result:generation:sql_table:{sql_table_id}"

    async def sql_generation_key_suffix(self, sql_table_ids: Sequence[str]) -> Optional[str]:
        """Return an opaque dependency-generation suffix for an SQL cache key.

        Redis generations make a slow fill that started before a write commit
        unreachable in every worker. Without Redis, the process-local
        generations provide the same guarantee inside one gateway worker.
        ``None`` means distributed generation state could not be read; callers
        must bypass result caching for that invocation rather than construct a
        potentially stale generation-zero key.
        """
        normalized = tuple(sorted({str(table_id) for table_id in sql_table_ids if table_id}))
        if not normalized:
            return ""
        generations: Dict[str, int] = {}
        if self._l2_enabled:
            redis = await self._get_redis_client()
            if not redis:
                return None
            try:
                values = await redis.mget(*(self._sql_generation_key(table_id) for table_id in normalized))
                generations = {
                    table_id: int(value or 0)
                    for table_id, value in zip(normalized, values)
                }
            except Exception as exc:  # pragma: no cover - backend-specific failures
                logger.debug("ToolResultCache Redis generation read failed: %s", exc)
                self._redis_available = False
                return None
        else:
            generations = self.snapshot_sql_generations(normalized)
        digest = _canonical_digest({"sql_generations": generations})
        return f":sqlgen:{digest}" if digest else ""

    async def _get_redis_client(self) -> Any:
        if not self._l2_enabled:
            return None
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
            if client:
                self._redis_checked = True
                self._redis_available = True
            return client
        except Exception:  # pragma: no cover - backend-specific failures
            self._redis_checked = True
            self._redis_available = False
            return None

    @staticmethod
    def _serialize_entry(entry: _Entry) -> bytes:
        return orjson.dumps(
            {
                "tool_id": entry.tool_id,
                "gateway_id": entry.gateway_id,
                "sql_table_ids": list(entry.sql_table_ids),
                "payload": orjson.loads(entry.payload),
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
            }
        )

    @staticmethod
    def _deserialize_entry(value: Any) -> _Entry:
        envelope = orjson.loads(value)
        return _Entry(
            tool_id=str(envelope["tool_id"]),
            gateway_id=envelope.get("gateway_id"),
            sql_table_ids=tuple(
                str(table_id)
                for table_id in (
                    envelope.get("sql_table_ids")
                    or ([envelope["sql_table_id"]] if envelope.get("sql_table_id") else [])
                )
            ),
            payload=orjson.dumps(envelope["payload"]),
            created_at=float(envelope["created_at"]),
            expires_at=float(envelope["expires_at"]),
        )

    def _set_l1(self, key: str, entry: _Entry, *, expected_sql_generations: Optional[Mapping[str, int]] = None) -> bool:
        with self._lock:
            if expected_sql_generations and any(self._sql_generations.get(table_id, 0) != generation for table_id, generation in expected_sql_generations.items()):
                return False
            entry_bytes = len(entry.payload)
            if entry_bytes > self._l1_max_bytes:
                return False
            if key in self._cache:
                previous = self._cache.pop(key)
                self._l1_bytes -= len(previous.payload)
            while self._cache and (len(self._cache) >= self._l1_max_entries or self._l1_bytes + entry_bytes > self._l1_max_bytes):
                _evicted_key, evicted = self._cache.popitem(last=False)
                self._l1_bytes -= len(evicted.payload)
                self._stats["evictions"] += 1
            self._cache[key] = entry
            self._l1_bytes += entry_bytes
            return True

    def _get_l1(self, key: str) -> Optional[_Entry]:
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                self._cache.move_to_end(key)
                self._stats["l1_hits"] += 1
                return entry
            if entry:
                removed = self._cache.pop(key)
                self._l1_bytes -= len(removed.payload)
            self._stats["l1_misses"] += 1
        return None

    def _validated_hit(self, entry: _Entry, source: str) -> Optional[CachedToolResult]:
        try:
            result = ToolResult.model_validate(orjson.loads(entry.payload))
        except Exception:
            with self._lock:
                self._stats["decode_errors"] += 1
            return None
        return CachedToolResult(result=result, age_seconds=max(0.0, time.time() - entry.created_at), source=source)

    async def get(self, key: str) -> Optional[CachedToolResult]:
        """Read and validate an entry from L1, then optional Redis L2."""
        if not self._enabled:
            return None
        entry = self._get_l1(key)
        if entry:
            hit = self._validated_hit(entry, "memory")
            if hit:
                return hit
            await self.invalidate(key)

        redis = await self._get_redis_client()
        if not redis:
            return None
        try:
            raw = await redis.get(self._redis_key(key))
            if not raw:
                self._stats["l2_misses"] += 1
                return None
            entry = self._deserialize_entry(raw)
            if entry.expires_at <= time.time():
                await redis.delete(self._redis_key(key))
                self._stats["l2_misses"] += 1
                return None
            self._stats["l2_hits"] += 1
            self._set_l1(key, entry)
            hit = self._validated_hit(entry, "redis")
            if hit:
                return hit
            await self.invalidate(key)
        except Exception as exc:  # pragma: no cover - backend-specific failures
            logger.debug("ToolResultCache Redis get failed: %s", exc)
            self._redis_available = False
        return None

    async def set(
        self,
        key: str,
        result: ToolResult,
        *,
        ttl_seconds: int,
        tool_id: str,
        gateway_id: Optional[str] = None,
        sql_table_id: Optional[str] = None,
        sql_table_ids: Optional[Sequence[str]] = None,
        expected_sql_generations: Optional[Mapping[str, int]] = None,
    ) -> bool:
        """Store a successful result, returning whether it fit cache limits."""
        if not self._enabled or result.is_error:
            return False
        try:
            payload = orjson.dumps(result.model_dump(by_alias=True, mode="json"))
        except Exception as exc:
            # ToolResult permits extension metadata. If an extension supplies a
            # value Pydantic/orjson cannot encode, bypass caching rather than
            # failing the successful tool call.
            logger.debug("ToolResultCache result serialization failed: %s", exc)
            with self._lock:
                self._stats["encode_errors"] += 1
            return False
        if len(payload) > self._max_entry_bytes:
            with self._lock:
                self._stats["oversize_skips"] += 1
            return False

        effective_ttl = min(max(1, ttl_seconds), self._max_ttl_seconds)
        now = time.time()
        dependency_ids = {str(table_id) for table_id in (sql_table_ids or ()) if table_id}
        if sql_table_id:
            dependency_ids.add(str(sql_table_id))
        entry = _Entry(
            tool_id=tool_id,
            gateway_id=gateway_id,
            sql_table_ids=tuple(sorted(dependency_ids)),
            payload=payload,
            created_at=now,
            expires_at=now + effective_ttl,
        )
        if not self._set_l1(key, entry, expected_sql_generations=expected_sql_generations):
            return False
        with self._lock:
            self._stats["stores"] += 1

        redis = await self._get_redis_client()
        if not redis:
            return True
        try:
            redis_key = self._redis_key(key)
            await redis.setex(redis_key, effective_ttl, self._serialize_entry(entry))
            index_keys = [self._tool_index_key(tool_id)]
            if gateway_id:
                index_keys.append(self._gateway_index_key(gateway_id))
            index_keys.extend(self._sql_table_index_key(table_id) for table_id in entry.sql_table_ids)
            for index_key in index_keys:
                # ZSET scores are entry expirations. Pruning on every write
                # bounds stale reverse members even when high-cardinality keys
                # continually refresh the index TTL.
                await redis.zremrangebyscore(index_key, 0, now)
                await redis.zadd(index_key, {key: entry.expires_at})
                await redis.expire(index_key, self._max_ttl_seconds)
        except Exception as exc:  # pragma: no cover - backend-specific failures
            logger.debug("ToolResultCache Redis set failed: %s", exc)
            self._redis_available = False
        return True

    async def invalidate(self, key: str) -> None:
        """Invalidate one exact key in both tiers."""
        with self._lock:
            removed = self._cache.pop(key, None)
            if removed:
                self._l1_bytes -= len(removed.payload)
                self._stats["invalidations"] += 1
        redis = await self._get_redis_client()
        if redis:
            try:
                await redis.delete(self._redis_key(key))
            except Exception as exc:  # pragma: no cover - backend-specific failures
                logger.debug("ToolResultCache Redis key invalidation failed: %s", exc)

    def _invalidate_local_matching(self, *, tool_id: Optional[str] = None, gateway_id: Optional[str] = None, sql_table_id: Optional[str] = None) -> int:
        with self._lock:
            keys = [
                key
                for key, entry in self._cache.items()
                if (tool_id is not None and entry.tool_id == tool_id)
                or (gateway_id is not None and entry.gateway_id == gateway_id)
                or (sql_table_id is not None and sql_table_id in entry.sql_table_ids)
            ]
            for key in keys:
                removed = self._cache.pop(key)
                self._l1_bytes -= len(removed.payload)
            self._stats["invalidations"] += len(keys)
        return len(keys)

    async def _invalidate_index(self, index_key: str, message: str) -> None:
        redis = await self._get_redis_client()
        if not redis:
            return
        try:
            members = await redis.zrangebyscore(index_key, time.time(), "+inf")
            normalized = [member.decode() if isinstance(member, bytes) else str(member) for member in members]
            if normalized:
                await redis.delete(*(self._redis_key(key) for key in normalized))
            await redis.delete(index_key)
            await redis.publish("mcpgw:cache:invalidate", message)
        except Exception as exc:  # pragma: no cover - backend-specific failures
            logger.debug("ToolResultCache Redis index invalidation failed: %s", exc)

    async def invalidate_tool(self, tool_id: str) -> None:
        """Invalidate every cached result for one tool."""
        self._invalidate_local_matching(tool_id=tool_id)
        await self._invalidate_index(self._tool_index_key(tool_id), f"tool_result:tool:{tool_id}")

    async def invalidate_gateway(self, gateway_id: str) -> None:
        """Invalidate every cached result associated with one gateway."""
        self._invalidate_local_matching(gateway_id=gateway_id)
        await self._invalidate_index(self._gateway_index_key(gateway_id), f"tool_result:gateway:{gateway_id}")

    async def invalidate_sql_table(self, sql_table_id: str) -> None:
        """Invalidate cached query results for a governed SQL table."""
        await self.invalidate_sql_tables((sql_table_id,))

    async def invalidate_sql_tables(self, sql_table_ids: Sequence[str]) -> None:
        """Invalidate SQL dependencies and await every distributed attempt.

        The local generations are advanced before any Redis I/O so stale fills
        are rejected immediately in this worker. The coroutine does not return
        until every Redis generation increment and reverse-index cleanup has
        completed (or failed through the cache's best-effort fallback).
        """
        normalized = self.invalidate_sql_tables_local(sql_table_ids)
        await self.invalidate_sql_tables_distributed(normalized)

    def invalidate_sql_tables_local(self, sql_table_ids: Sequence[str]) -> tuple[str, ...]:
        """Immediately advance generations and clear local SQL results."""
        normalized = tuple(sorted({str(table_id) for table_id in sql_table_ids if table_id}))
        for table_id in normalized:
            self._increment_sql_generation(table_id)
            self._invalidate_local_matching(sql_table_id=table_id)
        return normalized

    async def invalidate_sql_tables_distributed(self, sql_table_ids: Sequence[str]) -> None:
        """Await Redis generation/index invalidation after local preparation."""
        normalized = tuple(sorted({str(table_id) for table_id in sql_table_ids if table_id}))
        if normalized:
            await asyncio.gather(*(self._invalidate_sql_table_distributed(table_id) for table_id in normalized))

    async def _invalidate_sql_table_distributed(self, sql_table_id: str) -> None:
        """Advance Redis generation and remove old distributed entries."""
        redis = await self._get_redis_client()
        if redis:
            try:
                # Increment before deleting old keys. A fill already in flight
                # may still write its old-generation key, but no subsequent
                # reader can address it.
                await redis.incr(self._sql_generation_key(sql_table_id))
            except Exception as exc:  # pragma: no cover - backend-specific failures
                logger.debug("ToolResultCache Redis generation increment failed: %s", exc)
                self._redis_available = False
        await self._invalidate_index(self._sql_table_index_key(sql_table_id), f"tool_result:sql_table:{sql_table_id}")

    def invalidate_sql_tables_sync(self, sql_table_ids: Sequence[str]) -> None:
        """Synchronously invalidate SQL dependencies in both cache tiers.

        Catalog services also have synchronous callers, including management
        scripts and tests. A dedicated synchronous Redis client avoids trying
        to drive the shared async client from a different or nested event loop.
        """
        normalized = self.invalidate_sql_tables_local(sql_table_ids)
        if not normalized:
            return

        redis = self._new_sync_redis_client()
        if not redis:
            return
        try:
            for table_id in normalized:
                try:
                    redis.incr(self._sql_generation_key(table_id))
                except Exception as exc:  # pragma: no cover - backend-specific failures
                    logger.debug("ToolResultCache sync Redis generation increment failed: %s", exc)
                    self._redis_available = False
                self._invalidate_index_sync(redis, self._sql_table_index_key(table_id), f"tool_result:sql_table:{table_id}")
        finally:
            try:
                redis.close()
            except Exception as exc:  # pragma: no cover - backend-specific failures
                logger.debug("ToolResultCache sync Redis close failed: %s", exc)

    def _new_sync_redis_client(self) -> Any:
        """Create a short-lived synchronous Redis client for sync barriers."""
        if not self._l2_enabled:
            return None
        try:
            # First-Party
            from mcpgateway.utils.redis_client import create_redis_client_sync  # pylint: disable=import-outside-toplevel

            return create_redis_client_sync()
        except Exception as exc:  # pragma: no cover - backend-specific failures
            logger.debug("ToolResultCache sync Redis client creation failed: %s", exc)
            self._redis_available = False
            return None

    def _invalidate_index_sync(self, redis: Any, index_key: str, message: str) -> None:
        """Synchronously remove indexed Redis results and publish invalidation."""
        try:
            members = redis.zrangebyscore(index_key, time.time(), "+inf")
            normalized = [member.decode() if isinstance(member, bytes) else str(member) for member in members]
            if normalized:
                redis.delete(*(self._redis_key(key) for key in normalized))
            redis.delete(index_key)
            redis.publish("mcpgw:cache:invalidate", message)
        except Exception as exc:  # pragma: no cover - backend-specific failures
            logger.debug("ToolResultCache sync Redis index invalidation failed: %s", exc)

    def invalidate_tools_sync(self, tool_ids: Sequence[str]) -> None:
        """Synchronously invalidate result entries for multiple tools."""
        normalized = tuple(sorted({str(tool_id) for tool_id in tool_ids if tool_id}))
        for tool_id in normalized:
            self._invalidate_local_matching(tool_id=tool_id)
        if not normalized:
            return
        redis = self._new_sync_redis_client()
        if not redis:
            return
        try:
            for tool_id in normalized:
                self._invalidate_index_sync(redis, self._tool_index_key(tool_id), f"tool_result:tool:{tool_id}")
        finally:
            try:
                redis.close()
            except Exception as exc:  # pragma: no cover - backend-specific failures
                logger.debug("ToolResultCache sync Redis close failed: %s", exc)

    def invalidate_tool_local(self, tool_id: str) -> int:
        """Clear local entries for a tool without publishing another message."""
        return self._invalidate_local_matching(tool_id=tool_id)

    def invalidate_gateway_local(self, gateway_id: str) -> int:
        """Clear local entries for a gateway without publishing another message."""
        return self._invalidate_local_matching(gateway_id=gateway_id)

    def invalidate_sql_table_local(self, sql_table_id: str) -> int:
        """Clear local entries for a SQL table without publishing another message."""
        self._increment_sql_generation(sql_table_id)
        return self._invalidate_local_matching(sql_table_id=sql_table_id)

    def snapshot_sql_generations(self, sql_table_ids: Sequence[str]) -> Dict[str, int]:
        """Capture local table generations before a SQL query cache fill."""
        with self._lock:
            return {str(table_id): self._sql_generations.get(str(table_id), 0) for table_id in sql_table_ids}

    def _increment_sql_generation(self, sql_table_id: str) -> None:
        """Advance one table generation so in-flight stale fills are rejected."""
        with self._lock:
            self._sql_generations[sql_table_id] = self._sql_generations.get(sql_table_id, 0) + 1

    def invalidate_all_local(self) -> None:
        """Clear this worker's L1 entries."""
        with self._lock:
            self._stats["invalidations"] += len(self._cache)
            self._cache.clear()
            self._l1_bytes = 0

    @asynccontextmanager
    async def single_flight(self, key: str) -> AsyncIterator[None]:
        """Serialize concurrent misses for ``key`` within the current worker."""
        loop_key = (id(asyncio.get_running_loop()), key)
        with self._flight_lock:
            flight = self._flights.get(loop_key)
            if flight is None:
                flight = _Flight(lock=asyncio.Lock())
                self._flights[loop_key] = flight
            flight.users += 1
        acquired = False
        try:
            await flight.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                flight.lock.release()
            with self._flight_lock:
                flight.users -= 1
                if flight.users == 0 and self._flights.get(loop_key) is flight:
                    self._flights.pop(loop_key, None)

    def stats(self) -> Dict[str, Any]:
        """Return bounded-cardinality cache metrics and configuration."""
        with self._lock:
            counters = dict(self._stats)
            l1_size = len(self._cache)
            l1_bytes = self._l1_bytes
        total_hits = counters["l1_hits"] + counters["l2_hits"]
        total_misses = counters["l1_misses"] + counters["l2_misses"]
        return {
            "enabled": self._enabled,
            **counters,
            "hit_rate": total_hits / (total_hits + total_misses) if total_hits + total_misses else 0.0,
            "l1_size": l1_size,
            "l1_bytes": l1_bytes,
            "l1_max_entries": self._l1_max_entries,
            "l1_max_bytes": self._l1_max_bytes,
            "max_entry_bytes": self._max_entry_bytes,
            "default_ttl_seconds": self._default_ttl_seconds,
            "max_ttl_seconds": self._max_ttl_seconds,
            "l2_enabled": self._l2_enabled,
            "redis_available": self._redis_available,
        }

    def reset_stats(self) -> None:
        """Reset counters without clearing entries."""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0


tool_result_cache = ToolResultCache()
