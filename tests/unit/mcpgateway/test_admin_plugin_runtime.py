# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_plugin_runtime.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the plugin runtime admin endpoints in ``mcpgateway.admin``.

Covers the deny paths CLAUDE.md requires for security-sensitive changes:
    * missing ``admin.plugins`` permission → 403
    * ``allow_admin_bypass=False`` branch (regression pin)
    * Pydantic request-body validation (422 for bad payloads)
    * unknown plugin (404)
    * Redis-persisted flag reflects the underlying Redis outcome

The endpoints are called directly so the suite runs without docker-compose
or NGINX. ``PermissionService`` is patched via ``monkeypatch`` — the same
pattern used by ``tests/unit/mcpgateway/routers/test_runtime_admin_router.py``.
"""

# Standard
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
from pydantic import ValidationError
import pytest

# First-Party
import mcpgateway.admin as admin_module
import mcpgateway.plugins as fw
from mcpgateway.schemas import PluginModeUpdateRequest, PluginToggleRequest


@contextmanager
def _capture_admin_logger_records():
    """Intercept ``admin_module.LOGGER`` calls directly and yield record-like sentinels.

    Earlier attempts attached a handler to ``logging.getLogger("mcpgateway.admin")``
    (and before that, used ``caplog``). Both routes go through the standard
    logging chain, which CI configurations sometimes mute via root-handler
    clearing during lifespan, ``logger.disabled`` flips, propagation toggles,
    or LOG_LEVEL gates. Replacing ``LOGGER`` with a spy bypasses all of that —
    the test asserts on what the production code actually called, not on what
    the logging machinery happened to forward.
    """
    captured: list[SimpleNamespace] = []
    spy = MagicMock()

    def _record(level: str):
        def _impl(msg, *args, **_kwargs):
            try:
                formatted = msg % args if args else str(msg)
            except Exception:
                formatted = str(msg)
            captured.append(SimpleNamespace(level=level, message=formatted, getMessage=lambda f=formatted: f))

        return _impl

    spy.debug.side_effect = _record("debug")
    spy.info.side_effect = _record("info")
    spy.warning.side_effect = _record("warning")
    spy.error.side_effect = _record("error")
    spy.critical.side_effect = _record("critical")
    spy.exception.side_effect = _record("error")

    with patch.object(admin_module, "LOGGER", spy):
        yield captured


@pytest.fixture(autouse=True)
def _reset_framework_state():
    """Clear the shared-toggle cache and wire the Redis shim for each test."""
    # First-Party
    from tests.utils.plugin_redis_helper import install_dynamic_redis_provider

    with install_dynamic_redis_provider():
        fw._invalidate_shared_enabled_cache()
        fw._state.clear_local_mode_overrides()
        yield
        fw._invalidate_shared_enabled_cache()
        fw._state.clear_local_mode_overrides()


@pytest.fixture
def admin_user():
    return {"email": "admin@example.com", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "tests", "db": None}


@pytest.fixture
def non_admin_user():
    return {"email": "user@example.com", "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "tests", "db": None}


@pytest.fixture
def allow_admin(monkeypatch: pytest.MonkeyPatch):
    class AllowAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", AllowAll)


@pytest.fixture
def deny_all(monkeypatch: pytest.MonkeyPatch):
    class DenyAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return False

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyAll)


@pytest.fixture
def admin_bypass_denied(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so it denies only when ``allow_admin_bypass`` is False.

    Pins the regression where a future contributor flips ``allow_admin_bypass=True`` —
    admin users would then pass this deny path and the test would start failing.
    """

    class BypassSensitive:
        def __init__(self, _db):
            pass

        async def check_permission(self, **kwargs):
            return bool(kwargs.get("allow_admin_bypass"))

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", BypassSensitive)


@pytest.fixture
def mock_request():
    """Minimal Request stand-in whose ``app.state`` holds no plugin_manager."""
    req = MagicMock()
    req.app = MagicMock()
    req.app.state = SimpleNamespace(plugin_manager=None)
    req.headers = {}
    return req


@pytest.fixture
def mock_redis_client():
    """Return an AsyncMock Redis client that accepts ``set``/``publish`` successfully."""
    client = AsyncMock()
    client.set = AsyncMock()
    client.publish = AsyncMock()
    client.get = AsyncMock(return_value=b"false")
    return client


@pytest.fixture
def mock_plugin_service(monkeypatch: pytest.MonkeyPatch):
    """Return a mock plugin service with two known plugins and wire the configured-names helper."""
    service = MagicMock()
    service.set_plugin_manager = MagicMock()
    service.get_all_plugins = MagicMock(return_value=[{"name": "RateLimiterPlugin"}, {"name": "OtherPlugin"}])
    monkeypatch.setattr(admin_module, "get_plugin_service", lambda: service)
    # ``update_plugin_mode`` validates against the configured plugin set rather
    # than the live manager so freshly-disabled nodes can still pre-stage per-
    # plugin overrides. Stub the helper here so tests exercise the real path.
    monkeypatch.setattr("mcpgateway.plugins.list_configured_plugin_names", lambda: ["RateLimiterPlugin", "OtherPlugin"])
    return service


# ---------------------------------------------------------------------------
# PUT /admin/plugins — toggle_plugins_global
# ---------------------------------------------------------------------------


class TestToggleGlobalPluginsRBAC:
    """Deny-path coverage for ``PUT /admin/plugins``."""

    @pytest.mark.asyncio
    async def test_denies_when_permission_service_rejects(self, deny_all, admin_user, mock_request, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginToggleRequest(enabled=True)
        with pytest.raises(HTTPException) as exc:
            await admin_module.toggle_plugins_global(payload=payload, request=mock_request, user=admin_user)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_denies_admin_when_bypass_disabled(self, admin_bypass_denied, admin_user, mock_request, monkeypatch):
        """``allow_admin_bypass=False`` must not let an admin through — pins the decorator argument."""
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginToggleRequest(enabled=True)
        with pytest.raises(HTTPException) as exc:
            await admin_module.toggle_plugins_global(payload=payload, request=mock_request, user=admin_user)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_denies_non_admin_user(self, deny_all, non_admin_user, mock_request, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginToggleRequest(enabled=False)
        with pytest.raises(HTTPException) as exc:
            await admin_module.toggle_plugins_global(payload=payload, request=mock_request, user=non_admin_user)
        assert exc.value.status_code == 403


class TestToggleGlobalPluginsValidation:
    """Pydantic request-body validation runs before the route handler executes."""

    def test_missing_enabled_rejected(self):
        with pytest.raises(ValidationError):
            PluginToggleRequest()  # type: ignore[call-arg]

    def test_non_bool_enabled_rejected(self):
        # Pydantic coerces "yes"/"no" strings to bool by default; use an
        # uncoercible value so the test pins against a future schema change.
        with pytest.raises(ValidationError):
            PluginToggleRequest(enabled=["bad"])  # type: ignore[arg-type]


class TestToggleGlobalPluginsHappyPath:
    """Verifies the endpoint surfaces the real Redis outcome to the caller."""

    @pytest.mark.asyncio
    async def test_returns_redis_persisted_true_when_redis_ok(self, allow_admin, admin_user, mock_request, mock_redis_client, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis_client))
        payload = PluginToggleRequest(enabled=True)
        response = await admin_module.toggle_plugins_global(payload=payload, request=mock_request, user=admin_user)
        assert response.redis_persisted is True
        mock_redis_client.set.assert_awaited_once()
        mock_redis_client.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_redis_persisted_false_when_redis_unavailable(self, allow_admin, admin_user, mock_request, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginToggleRequest(enabled=True)
        response = await admin_module.toggle_plugins_global(payload=payload, request=mock_request, user=admin_user)
        assert response.redis_persisted is False


class TestToggleGlobalPluginsAdminCacheSync:
    """Regression pins: toggling the subsystem must refresh the admin-side caches.

    On a node that started with plugins disabled, ``app.state.plugin_manager``
    stays unset and ``PluginService`` is never wired. Without this sync the
    runtime starts serving plugins but ``/admin/plugins`` and
    ``/admin/plugins/{name}`` read empty/stale state until restart.
    """

    @pytest.mark.asyncio
    async def test_enabling_wires_admin_cache(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        fake_manager = MagicMock(name="fake_plugin_manager")
        # RBAC decorator also calls ``get_plugin_manager`` and would try to
        # invoke the permission-check hook on whatever comes back. Flip
        # ``has_hooks_for`` off so the decorator skips it and we only exercise
        # the admin-cache sync path here.
        fake_manager.has_hooks_for = MagicMock(return_value=False)

        async def fake_get_plugin_manager(*_, **__):
            return fake_manager

        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", fake_get_plugin_manager)

        await admin_module.toggle_plugins_global(payload=PluginToggleRequest(enabled=True), request=mock_request, user=admin_user)

        assert mock_request.app.state.plugin_manager is fake_manager
        mock_plugin_service.set_plugin_manager.assert_called_once_with(fake_manager)

    @pytest.mark.asyncio
    async def test_sync_failure_does_not_mask_successful_toggle(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        """The shared toggle has already committed; a failed admin-cache sync must not turn into a 500.

        Regression pin: before the try/except, an exception inside the sync
        block (e.g. ``set_plugin_manager`` raising on a degraded node) propagated
        up and the handler 500'd even though the global toggle was already
        persisted. We also pin the swallow-and-warn log path so a future
        refactor that drops the log can't silently strand operators.
        """
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        # Force the sync step to fail mid-way. The shared toggle has already
        # been written by ``enable_plugins_shared`` at this point.
        mock_plugin_service.set_plugin_manager.side_effect = RuntimeError("cache unavailable")

        # Attach directly to the admin module's LOGGER — pytest's ``caplog``
        # lives on root and is lost if any earlier test's lifespan ran
        # ``root_logger.handlers.clear()``. A logger-local handler survives.
        with _capture_admin_logger_records() as records:
            response = await admin_module.toggle_plugins_global(payload=PluginToggleRequest(enabled=False), request=mock_request, user=admin_user)

        assert response.redis_persisted is False
        # The sync path was entered (mock raised), and the swallow path logged
        # the admin-cache-sync failure warning.
        mock_plugin_service.set_plugin_manager.assert_called_once_with(None)
        assert any("admin-cache sync failed" in record.getMessage() for record in records)

    @pytest.mark.asyncio
    async def test_disabling_clears_admin_cache(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        """The inverse path: disabling must detach the manager so stale metadata doesn't keep serving."""
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        # Pre-populate with something so we can assert it gets cleared.
        mock_request.app.state.plugin_manager = MagicMock(name="stale_manager")

        await admin_module.toggle_plugins_global(payload=PluginToggleRequest(enabled=False), request=mock_request, user=admin_user)

        assert mock_request.app.state.plugin_manager is None
        mock_plugin_service.set_plugin_manager.assert_called_once_with(None)


class TestAdminCacheSelfHeal:
    """Regression pin for ``_sync_plugin_service_from_runtime`` — admin reads must self-heal.

    If ``toggle_plugins_global`` ever swallowed a sync failure (degraded factory,
    transient error) and left ``app.state.plugin_manager`` unset, the admin GETs
    would render stale/empty forever without this fallback. Pinning it here
    prevents a future refactor from silently deleting the helper.
    """

    @pytest.mark.asyncio
    async def test_sync_helper_populates_from_framework_when_app_state_missing(self, monkeypatch):
        """The helper must hydrate ``app.state`` and ``plugin_service`` from ``get_plugin_manager`` when ``app.state`` is empty."""
        req = MagicMock()
        req.app = MagicMock()
        req.app.state = SimpleNamespace()  # deliberately no ``plugin_manager`` attr

        plugin_service = MagicMock()
        plugin_service.set_plugin_manager = MagicMock()

        fake_manager = MagicMock(name="live_manager")

        async def fake_get_plugin_manager(*_, **__):
            return fake_manager

        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", fake_get_plugin_manager)

        await admin_module._sync_plugin_service_from_runtime(req, plugin_service)

        assert req.app.state.plugin_manager is fake_manager
        plugin_service.set_plugin_manager.assert_called_once_with(fake_manager)

    @pytest.mark.asyncio
    async def test_sync_helper_clears_cache_on_remote_global_disable(self, monkeypatch):
        """Remote-disable regression pin: if another node flipped the shared toggle off, this node must drop its stale cache.

        Before the fix, the helper only hydrated ``app.state`` when it was
        empty, so a prior enable left a live-looking manager there and admin
        reads kept serving plugin metadata the cluster had turned off.
        """
        req = MagicMock()
        req.app = MagicMock()
        # Simulate a prior enable: cache populated with a now-stale manager.
        req.app.state = SimpleNamespace(plugin_manager=MagicMock(name="stale_manager"))

        plugin_service = MagicMock()

        async def fake_get_plugin_manager(*_, **__):
            # Framework returns None because the shared toggle is now ``false``.
            return None

        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", fake_get_plugin_manager)

        await admin_module._sync_plugin_service_from_runtime(req, plugin_service)

        assert req.app.state.plugin_manager is None
        plugin_service.set_plugin_manager.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_sync_helper_swallows_errors_and_never_raises(self, monkeypatch):
        """A failure inside the helper must not turn a read into a 500 — and must log."""
        req = MagicMock()
        req.app = MagicMock()
        req.app.state = SimpleNamespace()

        plugin_service = MagicMock()
        called = {"exploding": False}

        async def exploding(*_, **__):
            called["exploding"] = True
            raise RuntimeError("factory unavailable")

        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", exploding)

        # Must return without raising — the try/except around the helper body
        # is what stops a framework failure from turning into a 500. We also
        # pin the warning log (via a logger-local handler, see note above)
        # so the operator signal isn't quietly dropped.
        with _capture_admin_logger_records() as records:
            await admin_module._sync_plugin_service_from_runtime(req, plugin_service)

        assert called["exploding"] is True
        assert not hasattr(req.app.state, "plugin_manager") or req.app.state.plugin_manager is None
        plugin_service.set_plugin_manager.assert_not_called()
        assert any("self-heal failed" in record.getMessage() for record in records)


# ---------------------------------------------------------------------------
# PUT /admin/plugins/{name} — update_plugin_mode
# ---------------------------------------------------------------------------


class TestUpdatePluginModeRBAC:
    """Deny-path coverage for ``PUT /admin/plugins/{name}``."""

    @pytest.mark.asyncio
    async def test_denies_without_permission(self, deny_all, admin_user, mock_request, mock_plugin_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginModeUpdateRequest(mode="enforce")
        with pytest.raises(HTTPException) as exc:
            await admin_module.update_plugin_mode(
                name="RateLimiterPlugin",
                payload=payload,
                user=admin_user,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_denies_admin_when_bypass_disabled(self, admin_bypass_denied, admin_user, mock_request, mock_plugin_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginModeUpdateRequest(mode="enforce")
        with pytest.raises(HTTPException) as exc:
            await admin_module.update_plugin_mode(
                name="RateLimiterPlugin",
                payload=payload,
                user=admin_user,
            )
        assert exc.value.status_code == 403


class TestUpdatePluginModeValidation:
    """Pydantic rejects unsupported mode values before the handler runs."""

    @pytest.mark.parametrize("bad_mode", ["off", "PERMISSIVE", "", None, 123])
    def test_invalid_mode_rejected(self, bad_mode):
        with pytest.raises(ValidationError):
            PluginModeUpdateRequest(mode=bad_mode)  # type: ignore[arg-type]

    @pytest.mark.parametrize("good_mode", ["enforce", "enforce_ignore_error", "permissive", "disabled"])
    def test_valid_modes_accepted(self, good_mode):
        body = PluginModeUpdateRequest(mode=good_mode)
        assert body.mode == good_mode


class TestUpdatePluginModeConfiguredValidation:
    """Regression pin: validation reads the configured plugin set, not the live manager.

    On a node that booted with plugins globally disabled, ``PluginService`` has
    no wired manager and ``get_all_plugins()`` returns ``[]``. Before this fix
    that made the endpoint 404 for every valid plugin name, blocking operators
    from pre-staging a mode override before turning the subsystem on.
    """

    @pytest.mark.asyncio
    async def test_accepts_configured_plugin_when_manager_unwired(self, allow_admin, admin_user, mock_request, mock_redis_client, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis_client))

        # Simulate a freshly disabled node: no live manager, so the plugin
        # service returns an empty list — but the factory still loaded the
        # YAML config at startup, so the configured names helper is populated.
        stub_service = MagicMock()
        stub_service.get_all_plugins = MagicMock(return_value=[])
        monkeypatch.setattr(admin_module, "get_plugin_service", lambda: stub_service)
        monkeypatch.setattr("mcpgateway.plugins.list_configured_plugin_names", lambda: ["PreStagePlugin"])

        response = await admin_module.update_plugin_mode(
            name="PreStagePlugin",
            payload=PluginModeUpdateRequest(mode="permissive"),
            user=admin_user,
        )
        assert response.plugin == "PreStagePlugin"
        assert response.mode == "permissive"


class TestUpdatePluginModeHandler:
    """End-to-end behaviour of the handler when RBAC allows."""

    @pytest.mark.asyncio
    async def test_404_on_unknown_plugin(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginModeUpdateRequest(mode="enforce")
        with pytest.raises(HTTPException) as exc:
            await admin_module.update_plugin_mode(
                name="NotARealPlugin",
                payload=payload,
                user=admin_user,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reports_redis_persisted_true(self, allow_admin, admin_user, mock_request, mock_plugin_service, mock_redis_client, monkeypatch):
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis_client))
        payload = PluginModeUpdateRequest(mode="permissive")
        response = await admin_module.update_plugin_mode(
            name="RateLimiterPlugin",
            payload=payload,
            user=admin_user,
        )
        assert response.plugin == "RateLimiterPlugin"
        assert response.mode == "permissive"
        assert response.redis_persisted is True
        # Redis SET carries the 24h TTL — regression pin so a refactor can't drop ``ex=``.
        call = mock_redis_client.set.call_args
        assert call.kwargs.get("ex") == 86400 or (len(call.args) >= 3 and call.args[2] == 86400)
        mock_redis_client.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_failure_logged_not_raised(self, allow_admin, admin_user, mock_request, mock_plugin_service, mock_redis_client, monkeypatch):
        """``invalidate_all_plugin_managers`` raising must become a WARNING, not a 500.

        The override is already stored by ``publish_plugin_mode_change`` at this
        point — a cache-sweep failure would strand operators without this pin.
        """
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis_client))

        async def _fail_invalidate():
            raise RuntimeError("cache sweep blew up")

        monkeypatch.setattr("mcpgateway.plugins.invalidate_all_plugin_managers", _fail_invalidate)

        with _capture_admin_logger_records() as records:
            response = await admin_module.update_plugin_mode(
                name="RateLimiterPlugin",
                payload=PluginModeUpdateRequest(mode="permissive"),
                user=admin_user,
            )

        assert response.plugin == "RateLimiterPlugin"
        assert response.mode == "permissive"
        assert any("cache invalidation failed" in record.getMessage() for record in records)

    @pytest.mark.asyncio
    async def test_single_node_no_redis_applies_override_locally(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        """On Redis-less deployments the override lands in the in-process map; response signals redis_persisted=False."""
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
        payload = PluginModeUpdateRequest(mode="disabled")
        response = await admin_module.update_plugin_mode(
            name="RateLimiterPlugin",
            payload=payload,
            user=admin_user,
        )
        assert response.redis_persisted is False
        assert response.mode == "disabled"
        # The local override map now holds the change — this is what makes the
        # "local fallback" real: _apply_redis_mode_overrides will pick it up on
        # the next manager rebuild.
        assert fw.get_local_mode_overrides()["RateLimiterPlugin"] == "disabled"

    @pytest.mark.asyncio
    async def test_redis_set_failure_still_applies_locally(self, allow_admin, admin_user, mock_request, mock_plugin_service, monkeypatch):
        """A Redis SET transport failure still lands the override locally; publish must not run."""
        failing_client = AsyncMock()
        failing_client.set = AsyncMock(side_effect=Exception("ECONNREFUSED"))
        failing_client.publish = AsyncMock()
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=failing_client))

        payload = PluginModeUpdateRequest(mode="enforce")
        response = await admin_module.update_plugin_mode(
            name="RateLimiterPlugin",
            payload=payload,
            user=admin_user,
        )
        assert response.redis_persisted is False
        assert response.mode == "enforce"
        assert fw.get_local_mode_overrides()["RateLimiterPlugin"] == "enforce"
        # Publish must not run when the SET itself failed — prevents broadcasting
        # an override that isn't in Redis yet.
        failing_client.publish.assert_not_awaited()
