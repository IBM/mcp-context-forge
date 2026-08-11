# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_runtime_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Process-local runtime cache for outbound gRPC connections.

Industrial gRPC workloads call ``invoke_method`` in a tight loop (one MCP tool
call per upstream RPC). Every call used to build a fresh ``GrpcEndpoint``: a new
``Channel`` plus a private ``DescriptorPool`` populated from stored schema
descriptors, then torn down with ``channel.close()``. That per-call allocation is
the dominant cost at low-to-moderate concurrency.

This module caches the reusable pieces -- ``Channel``, ``DescriptorPool`` and the
derived message classes -- keyed by ``(service_id, schema_hash, connection
fingerprint)`` so a schema activation or a service configuration change naturally
invalidates the entry. See :mod:`mcpgateway.translate_grpc` for the caller.

Design constraints:

* Process-level only. No distributed coordination; each gateway worker keeps its
  own entries and a service change on one worker does not purge another until
  that worker's next lookup observes the new hash/fingerprint.
* Bounded. ``_GRPC_RUNTIME_CACHE_MAX_ENTRIES`` caps the number of live entries.
  Evicted channels are closed only once they are no longer referenced by an
  in-flight invocation, so a slow upstream cannot be torn down under a running
  call.
* Refcount-safety. ``acquire``/``release`` pairs the caller (``invoke_method``)
  must balance, even on exception, so ``close`` of an evicted channel never
  races an active call.
* Non-serialized. ``invoke`` itself still performs its sync RPC on the asyncio
  executor; this cache only removes the per-call construction overhead.
"""

# Standard
from collections import OrderedDict
from pathlib import Path
import threading
from typing import Any, Optional

try:
    # Third-Party
    import grpc
    from google.protobuf import descriptor_pool
    from google.protobuf import message_factory

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    grpc = None  # type: ignore
    descriptor_pool = None  # type: ignore
    message_factory = None  # type: ignore

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Runtime resource cap for a single gateway process. A higher ceiling than the
# HTTP/SQL caches because every entry holds a real channel (fd + executor
# thread); the low-to-moderate-concurrency target does not justify hundreds of
# live connections.
_GRPC_RUNTIME_CACHE_MAX_ENTRIES = 64

# A cached channel can sit idle between tool calls. gRPC channel keepalive pings
# keep the transport warm so a burst is not serialized on a reconnect.
_DEFAULT_KEEPALIVE_MS = 30_000


class GrpcRuntimeCache:
    """Process-local LRU cache of reusable gRPC runtime resources.

    An entry bundles the pieces a request needs to reach an upstream service
    without re-creating them: the transport (``Channel``), the schema view
    (``DescriptorPool``) and the derived ``MessageClass`` objects keyed by full
    protobuf type name.

    Key derivation happens in :meth:`key_for`, which folds the schema hash and
    every connection-affecting field of a registered service into the identity.
    A changed hash (schema activation) or a changed field (target/TLS/metadata)
    therefore yields a different key and the stale entry is replaced lazily on
    the next lookup -- no explicit invalidation call sites are needed.
    """

    def __init__(self, max_entries: int = _GRPC_RUNTIME_CACHE_MAX_ENTRIES) -> None:
        """Initialize an empty LRU cache.

        Args:
            max_entries: Hard cap on live entries. Evicting beyond this many is
                an LRU decision; evicted channels are closed only when their
                reference count reaches zero.
        """
        self._max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._lock = threading.Lock()

    def key_for(
        self,
        service_id: str,
        schema_hash: Optional[str],
        target: str,
        tls_enabled: bool,
        tls_cert_path: Optional[str],
        tls_key_path: Optional[str],
        metadata: dict[str, str],
    ) -> str:
        """Derive the cache identity for a registered service configuration.

        The schema hash is the activation version of the schema (the artifact
        id is not part of the identity because the same hash can be reached via
        several artifact versions). All connection-affecting fields are folded
        in so a config edit invalidates the entry.

        Args:
            service_id: Registered gRPC service ID.
            schema_hash: ``GrpcService.active_schema_hash``. A value of ``None``
                is a distinct identity from any hash (used when the service has
                no active schema yet).
            target: Upstream ``host:port``.
            tls_enabled: Whether a secure channel is used.
            tls_cert_path: Optional client certificate path.
            tls_key_path: Optional client private key path.
            metadata: Decrypted per-service gRPC metadata headers.

        Returns:
            Deterministic cache key string.
        """
        tls_paths = ""
        if tls_cert_path or tls_key_path:
            tls_paths = f"{tls_cert_path or ''}|{tls_key_path or ''}"
        meta_sorted = sorted((str(k), str(v)) for k, v in metadata.items())
        return "|".join(
            (
                service_id,
                schema_hash or "<none>",
                target,
                "tls" if tls_enabled else "plain",
                tls_paths,
                repr(meta_sorted),
            )
        )

    def acquire(
        self,
        key: str,
        target: str,
        tls_enabled: bool,
        tls_cert_path: Optional[str],
        tls_key_path: Optional[str],
    ) -> "_CacheEntry":
        """Return a cached entry for ``key`` or create one, bumping its refcount.

        The returned entry owns a ``Channel`` and a private ``DescriptorPool``
        that must be balanced with a later :meth:`release`. The entry is safe to
        hold across an ``await`` because it is never evicted while referenced.

        Args:
            key: Identity from :meth:`key_for`.
            target: Upstream address used to build the channel on a miss.
            tls_enabled: Whether to build a secure channel.
            tls_cert_path: Client cert path for mTLS, or None.
            tls_key_path: Client key path for mTLS, or None.

        Returns:
            A live ``_CacheEntry`` with ``refcount`` already incremented.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                entry.refcount += 1
                return entry

            entry = _CacheEntry(
                channel=_build_channel(target, tls_enabled, tls_cert_path, tls_key_path),
                pool=descriptor_pool.DescriptorPool() if GRPC_AVAILABLE else None,
                method_classes={},
                refcount=1,
            )
            self._entries[key] = entry
            self._entries.move_to_end(key)
            self._evict_locked()
            return entry

    def release(self, key: str, entry: "_CacheEntry") -> None:
        """Drop one reference to ``entry``, closing it once the last holder leaves.

        Args:
            key: The key the entry was acquired under.
            entry: The entry returned by :meth:`acquire`.
        """
        with self._lock:
            entry.refcount -= 1
            if entry.refcount > 0:
                return
            # Only close entries that were actually evicted from the cache. A
            # still-present entry stays warm for the next caller.
            if self._entries.get(key) is entry:
                return
            entry.close()
            logger.info("Closed idle gRPC runtime entry %s", key)

    def invalidate(self, key: str) -> None:
        """Remove ``key`` from the cache, closing it when no caller holds it.

        This is a callable escape hatch for call sites that know a service
        changed; normally key rotation handles invalidation automatically.

        Args:
            key: Identity to drop.
        """
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is not None and entry.refcount == 0:
                entry.close()
                logger.info("Invalidated gRPC runtime entry %s", key)

    def clear(self) -> None:
        """Drop every entry, closing those with no active caller.

        Used by tests and shutdown. Entries still referenced by an in-flight
        call are closed later, when their final release lands.
        """
        with self._lock:
            for key, entry in list(self._entries.items()):
                self._entries.pop(key, None)
                if entry.refcount == 0:
                    entry.close()
            logger.debug("Cleared gRPC runtime cache")

    def entry_count(self) -> int:
        """Return the number of live entries (referenced or not)."""
        with self._lock:
            return len(self._entries)

    def _evict_locked(self) -> None:
        """Evict least-recently-used entries until within ``max_entries``.

        Called with the lock held. Evicted entries with a nonzero refcount are
        only closed by their final release; those with no caller are closed
        immediately.
        """
        while len(self._entries) > self._max_entries:
            evict_key, evict_entry = next(iter(self._entries.items()))
            self._entries.pop(evict_key)
            if evict_entry.refcount == 0:
                evict_entry.close()
                logger.info("Evicted idle gRPC runtime entry %s", evict_key)
            else:
                logger.info("Evicted gRPC runtime entry %s (closed on final release)", evict_key)


class _CacheEntry:
    """One cached gRPC runtime bundle (channel + descriptor pool + message classes)."""

    __slots__ = ("channel", "pool", "method_classes", "refcount")

    def __init__(self, channel: Any, pool: Any, method_classes: dict[str, Any], refcount: int) -> None:
        """Initialize a cache entry.

        Args:
            channel: gRPC channel to the upstream service.
            pool: Private descriptor pool populated with the service schema.
            method_classes: Cache of full message type name to ``MessageClass``.
            refcount: Number of live holders of this entry.
        """
        self.channel = channel
        self.pool = pool
        self.method_classes = method_classes
        self.refcount = refcount

    def close(self) -> None:
        """Close the underlying channel and drop the descriptor pool."""
        if self.channel is not None:
            try:
                self.channel.close()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to close cached gRPC channel: %s", exc)
            self.channel = None
        self.pool = None
        self.method_classes = {}


def _build_channel(
    target: str,
    tls_enabled: bool,
    tls_cert_path: Optional[str],
    tls_key_path: Optional[str],
) -> Optional[Any]:
    """Create a grpc channel with keepalive enabled.

    Args:
        target: Upstream ``host:port``.
        tls_enabled: Whether to use a secure channel.
        tls_cert_path: Client cert path for mTLS, or None.
        tls_key_path: Client key path for mTLS, or None.

    Returns:
        A configured gRPC channel, or None when the gRPC runtime is unavailable.
    """
    if not GRPC_AVAILABLE:
        return None

    options = [
        ("grpc.keepalive_time_ms", _DEFAULT_KEEPALIVE_MS),
        ("grpc.keepalive_timeout_ms", 20_000),
        ("grpc.keepalive_permit_without_calls", 1),
        ("grpc.http2.max_pings_without_data", 0),
        ("grpc.max_receive_message_length", int(getattr(settings, "mcpgateway_grpc_max_message_size", 4 * 1024 * 1024))),
    ]
    if tls_enabled:
        if tls_cert_path and tls_key_path:
            try:
                cert = Path(tls_cert_path).read_bytes()
                key = Path(tls_key_path).read_bytes()
                credentials = grpc.ssl_channel_credentials(root_certificates=cert, private_key=key)
            except OSError as exc:
                raise ValueError(f"Unable to read TLS certificate or key file: {exc}") from exc
        else:
            credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(target, credentials, options=options)
    return grpc.insecure_channel(target, options=options)


# Module-level singleton. ``invoke_method`` acquires/releases on this instance;
# tests may replace it with a fresh ``GrpcRuntimeCache``.
runtime_cache = GrpcRuntimeCache(
    max_entries=getattr(settings, "grpc_runtime_cache_max_entries", _GRPC_RUNTIME_CACHE_MAX_ENTRIES)
)
