# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_grpc_runtime_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the process-local gRPC runtime cache (channel + descriptor pool reuse)
and its integration into GrpcService.invoke_method.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.services.grpc_runtime_cache import GrpcRuntimeCache, _CacheEntry, runtime_cache
from mcpgateway.services.grpc_service import GrpcService, GrpcServiceError


class TestGrpcRuntimeCacheKey:
    """Key derivation: schema hash and connection config fold into identity."""

    def test_key_stable_for_same_config(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {"k": "v"})
        key2 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {"k": "v"})
        assert key1 == key2

    def test_key_changes_on_schema_hash(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {})
        key2 = cache.key_for("svc-1", "hash-b", "10.0.0.1:50051", False, None, None, {})
        assert key1 != key2

    def test_key_changes_on_service_id(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {})
        key2 = cache.key_for("svc-2", "hash-a", "10.0.0.1:50051", False, None, None, {})
        assert key1 != key2

    def test_key_changes_on_target(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {})
        key2 = cache.key_for("svc-1", "hash-a", "10.0.0.2:50051", False, None, None, {})
        assert key1 != key2

    def test_key_changes_on_tls_enabled(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {})
        key2 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", True, None, None, {})
        assert key1 != key2

    def test_key_changes_on_metadata(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {"a": "1"})
        key2 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {"a": "2"})
        assert key1 != key2

    def test_none_schema_hash_is_distinct_identity(self):
        cache = GrpcRuntimeCache(max_entries=8)
        key1 = cache.key_for("svc-1", None, "10.0.0.1:50051", False, None, None, {})
        key2 = cache.key_for("svc-1", "hash-a", "10.0.0.1:50051", False, None, None, {})
        assert key1 != key2


class TestGrpcRuntimeCacheAcquireRelease:
    """Refcounted lifecycle: channels close only once idle and evicted."""

    def test_acquire_creates_channel_on_miss(self):
        cache = GrpcRuntimeCache(max_entries=8)
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel") as mock_build:
            mock_build.return_value = MagicMock()
            entry = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
        assert entry.refcount == 1
        mock_build.assert_called_once_with("10.0.0.1:50051", False, None, None)

    def test_acquire_reuses_entry_on_hit(self):
        cache = GrpcRuntimeCache(max_entries=8)
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel", return_value=MagicMock()) as mock_build:
            first = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
            second = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
        assert first is second
        assert second.refcount == 2
        mock_build.assert_called_once()

    def test_release_keeps_channel_when_still_present(self):
        cache = GrpcRuntimeCache(max_entries=8)
        channel = MagicMock()
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel", return_value=channel):
            entry = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
            cache.release("k1", entry)
        # Entry still cached and warm: channel must NOT be closed.
        assert cache.entry_count() == 1
        channel.close.assert_not_called()

    def test_release_closes_channel_after_eviction(self):
        cache = GrpcRuntimeCache(max_entries=1)
        channel1 = MagicMock()
        channel2 = MagicMock()
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel", side_effect=[channel1, channel2]):
            entry1 = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
            entry2 = cache.acquire("k2", "10.0.0.2:50051", False, None, None)
        # k1 was evicted (LRU) while still referenced by entry1's holder.
        channel1.close.assert_not_called()
        cache.release("k1", entry1)
        channel1.close.assert_called_once()
        # k2 remains present.
        channel2.close.assert_not_called()

    def test_invalidate_removes_and_closes_idle_entry(self):
        cache = GrpcRuntimeCache(max_entries=8)
        channel = MagicMock()
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel", return_value=channel):
            entry = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
            cache.release("k1", entry)
            cache.invalidate("k1")
        assert cache.entry_count() == 0
        channel.close.assert_called_once()

    def test_clear_closes_all_idle_entries(self):
        cache = GrpcRuntimeCache(max_entries=8)
        channel = MagicMock()
        with patch("mcpgateway.services.grpc_runtime_cache._build_channel", return_value=channel):
            entry = cache.acquire("k1", "10.0.0.1:50051", False, None, None)
            cache.release("k1", entry)
            cache.clear()
        assert cache.entry_count() == 0
        channel.close.assert_called_once()


class TestInvokeMethodRuntimeCache:
    """invoke_method uses the runtime cache for store-descriptor services."""

    def _enabled_service(self, *, with_schema=True, schema_hash="hash-a"):
        """Build a registered service MagicMock with an active schema."""
        svc = MagicMock(spec=DbGrpcService)
        svc.id = "svc-1"
        svc.name = "svc"
        svc.slug = "svc"
        svc.enabled = True
        svc.target = "10.0.0.1:50051"
        svc.tls_cert_path = None
        svc.tls_key_path = None
        svc.tls_enabled = False
        svc.grpc_metadata = {}
        svc.discovered_services = {
            "mysvc.Service": {"name": "mysvc.Service", "package": "mysvc", "methods": [{"name": "DoThing", "input_type": ".mysvc.Req", "output_type": ".mysvc.Resp", "client_streaming": False, "server_streaming": False}]},
        }
        svc.active_schema_hash = schema_hash if with_schema else None
        return svc

    @pytest.mark.asyncio
    async def test_cache_hit_reuses_single_channel(self, monkeypatch):
        """Two invocations with unchanged schema share one cached channel."""
        svc = self._enabled_service()
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = svc
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_grpc_target", lambda _t: None)
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_tls_path", lambda p, label="TLS path": p)
        monkeypatch.setattr("mcpgateway.services.grpc_service.GrpcSchemaService.descriptors_for_service", lambda db, s: [b"proto-bytes"])
        cache = GrpcRuntimeCache(max_entries=8)

        created = []
        invoked = []

        class RecordingEndpoint:
            def __init__(self, **kw):
                created.append(kw)
                self._channel = kw.get("channel")
                self._services = {}

            def load_file_descriptors(self, *_a, **_kw):
                pass

            async def start(self, timeout=None, trusted_local=False):
                pass

            async def invoke(self, *_a, **_kw):
                invoked.append(self._channel)
                return {"result": "ok"}

            async def close(self):
                pass

        with patch("mcpgateway.translate_grpc.GrpcEndpoint", RecordingEndpoint):
            with patch("mcpgateway.services.grpc_service.runtime_cache", cache):
                for _ in range(2):
                    result = await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})
        assert result == {"result": "ok"}
        # Both calls went through the SAME cached channel.
        assert invoked[0] is invoked[1]
        assert invoked[0] is cache._entries[list(cache._entries)[0]].channel

    @pytest.mark.asyncio
    async def test_schema_change_invalidates_cache(self, monkeypatch):
        """A new schema hash yields a new channel; old entry closes when idle."""
        svc_a = self._enabled_service(schema_hash="hash-a")
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = svc_a
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_grpc_target", lambda _t: None)
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_tls_path", lambda p, label="TLS path": p)
        monkeypatch.setattr("mcpgateway.services.grpc_service.GrpcSchemaService.descriptors_for_service", lambda db, s: [b"proto-bytes"])
        cache = GrpcRuntimeCache(max_entries=8)
        channels = []

        class RecordingEndpoint:
            def __init__(self, **kw):
                self._channel = kw.get("channel")
                self._services = {}

            def load_file_descriptors(self, *_a, **_kw):
                pass

            async def start(self, timeout=None, trusted_local=False):
                pass

            async def invoke(self, *_a, **_kw):
                channels.append(self._channel)
                return {"result": "ok"}

            async def close(self):
                pass

        with patch("mcpgateway.translate_grpc.GrpcEndpoint", RecordingEndpoint), patch("mcpgateway.services.grpc_service.runtime_cache", cache):
            await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})
            # Simulate an administrator activating a new schema (new hash).
            svc_a.active_schema_hash = "hash-b"
            await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})

        assert len(channels) == 2
        assert channels[0] is not channels[1]
        assert cache.entry_count() == 2

    @pytest.mark.asyncio
    async def test_config_change_invalidates_cache(self, monkeypatch):
        """Changing the service target yields a fresh channel (config change)."""
        svc = self._enabled_service()
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = svc
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_grpc_target", lambda _t: None)
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_tls_path", lambda p, label="TLS path": p)
        monkeypatch.setattr("mcpgateway.services.grpc_service.GrpcSchemaService.descriptors_for_service", lambda db, s: [b"proto-bytes"])
        cache = GrpcRuntimeCache(max_entries=8)
        channels = []

        class RecordingEndpoint:
            def __init__(self, **kw):
                self._channel = kw.get("channel")
                self._services = {}

            def load_file_descriptors(self, *_a, **_kw):
                pass

            async def start(self, timeout=None, trusted_local=False):
                pass

            async def invoke(self, *_a, **_kw):
                channels.append(self._channel)
                return {"result": "ok"}

            async def close(self):
                pass

        with patch("mcpgateway.translate_grpc.GrpcEndpoint", RecordingEndpoint), patch("mcpgateway.services.grpc_service.runtime_cache", cache):
            await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})
            svc.target = "10.0.0.2:50051"
            await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})

        assert len(channels) == 2
        assert channels[0] is not channels[1]

    @pytest.mark.asyncio
    async def test_release_called_on_error(self, monkeypatch):
        """A failed invocation still balances the cache acquire in finally."""
        svc = self._enabled_service()
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = svc
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_grpc_target", lambda _t: None)
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_tls_path", lambda p, label="TLS path": p)
        monkeypatch.setattr("mcpgateway.services.grpc_service.GrpcSchemaService.descriptors_for_service", lambda db, s: [b"proto-bytes"])
        cache = GrpcRuntimeCache(max_entries=8)

        class FailingEndpoint:
            def __init__(self, **kw):
                self._channel = kw.get("channel")
                self._services = {}

            def load_file_descriptors(self, *_a, **_kw):
                pass

            async def start(self, timeout=None, trusted_local=False):
                raise GrpcServiceError("boom")

            async def invoke(self, *_a, **_kw):
                return None

            async def close(self):
                pass

        with patch("mcpgateway.translate_grpc.GrpcEndpoint", FailingEndpoint), patch("mcpgateway.services.grpc_service.runtime_cache", cache):
            with pytest.raises(GrpcServiceError):
                await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})

        # After the failed call, the entry was released and is warm (refcount 0).
        assert cache.entry_count() == 1
        (entry,) = cache._entries.values()
        assert entry.refcount == 0

    @pytest.mark.asyncio
    async def test_cache_disabled_falls_back_to_per_call_endpoint(self, monkeypatch):
        """With grpc_runtime_cache_enabled=False the cache is not consulted."""
        svc = self._enabled_service()
        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = svc
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_grpc_target", lambda _t: None)
        monkeypatch.setattr("mcpgateway.services.grpc_service._validate_tls_path", lambda p, label="TLS path": p)
        monkeypatch.setattr("mcpgateway.services.grpc_service.GrpcSchemaService.descriptors_for_service", lambda db, s: [b"proto-bytes"])
        # First-Party
        from mcpgateway.services.grpc_service import settings as grpc_settings

        monkeypatch.setattr(grpc_settings, "grpc_runtime_cache_enabled", False)
        cache = GrpcRuntimeCache(max_entries=8)
        close_calls = []
        created = []

        class TrackedEndpoint:
            def __init__(self, **kw):
                created.append(kw)
                self._services = {}

            def load_file_descriptors(self, *_a, **_kw):
                pass

            async def start(self, timeout=None, trusted_local=False):
                pass

            async def invoke(self, *_a, **_kw):
                return {"result": "ok"}

            async def close(self):
                close_calls.append(True)

        with patch("mcpgateway.translate_grpc.GrpcEndpoint", TrackedEndpoint), patch("mcpgateway.services.grpc_service.runtime_cache", cache):
            await GrpcService().invoke_method(mock_db, "svc-1", "mysvc.Service.DoThing", {})

        assert cache.entry_count() == 0
        assert len(created) == 1
        assert len(close_calls) == 1
        # Per-call endpoint owns its channel.
        assert created[0].get("owns_channel") is not False
