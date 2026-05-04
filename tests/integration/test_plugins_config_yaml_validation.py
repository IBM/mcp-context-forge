# -*- coding: utf-8 -*-
"""Validation tests for the gateway's shipped ``plugins/config.yaml``.

Two contracts pinned here, both about the *yaml as shipped* matching the
plugins it configures:

  1. The rate-limiter's ``redis_url`` resolves from the ``REDIS_URL`` env
     via the plugin loader's Jinja substitution and points at a live Redis.
     Companion to IBM/mcp-context-forge#4581.

  2. Loading ``plugins/config.yaml`` and constructing each plugin produces
     zero ``unknown config key`` warnings — every key in every plugin's
     ``config:`` block must be in that plugin's accepted schema.  Catches
     stale / typo / aspirational keys before they reach operators' logs.

Skips cleanly on runners without Redis available; the schema-alignment
test runs without Redis and stays green everywhere.
"""

# Standard
import logging
import socket

# Third-Party
import pytest
import redis

# First-Party
from mcpgateway.plugins.framework.loader.config import ConfigLoader


def _redis_reachable(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _redis_reachable(),
    reason="Redis not reachable on 127.0.0.1:6379",
)
def test_rate_limiter_redis_url_resolves_and_connects(monkeypatch):
    """The rate-limiter's redis_url, sourced from the REDIS_URL env via the
    plugin loader's Jinja substitution, must resolve to a non-empty string
    AND the resolved URL must reach a live Redis (PING -> PONG).
    """
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    cfg = ConfigLoader.load_config("plugins/config.yaml")
    rl = next(p for p in cfg.plugins if p.name == "RateLimiterPlugin")
    resolved = rl.config.get("redis_url")

    assert resolved, (
        "redis_url must resolve to a non-empty string after Jinja substitution"
    )
    assert "{{" not in resolved, (
        f"Jinja placeholder leaked through unrendered: {resolved!r}"
    )

    client = redis.from_url(resolved, socket_connect_timeout=2, socket_timeout=2)
    try:
        assert client.ping() is True
    finally:
        client.close()


@pytest.mark.asyncio
async def test_shipped_plugins_config_has_no_unknown_keys(caplog, monkeypatch):
    """Loading ``plugins/config.yaml`` and constructing each plugin must
    produce zero ``unknown config key`` warnings.

    Plugins that emit those warnings (currently the rate-limiter's Rust
    engine; future plugins may follow the same pattern) accept a fixed
    schema and warn at WARN-level when an unrecognised key appears in
    their ``config:`` block.  The shipped yaml should never contain such
    keys: stale ones (left behind after a rename), typos
    (``redis_ur`` instead of ``redis_url``), or aspirational ones (added
    in the hope a feature exists when it doesn't) all silently pollute
    operators' logs and pull focus during incident response.

    This test is the regression guard against that drift.  It loads the
    yaml, instantiates each plugin via the plugin-framework loader (which
    invokes the plugin's ``__init__`` and therefore any unknown-key
    warnings), and asserts the captured log records contain none of those
    warnings.

    Constructions that raise (e.g. a plugin requiring a Redis it can't
    reach) are tolerated — that's a *connectivity* concern, not a *schema*
    concern, and the warning still fires before the connection attempt.

    TODO: move to ``tests/unit/`` once the plugin-framework extraction
    lands — no external deps, just placed here while the framework's
    unit-test surface is paused.
    """
    # Inject a default REDIS_URL so the rate-limiter's Jinja substitution
    # resolves even when the test runner hasn't set the env var.  The
    # plugin's connection attempt may still fail (no Redis required for
    # this test); we only care about warnings emitted at config-key
    # validation time, which precedes the network attempt.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # First-Party — local import so test-collection doesn't pay for it
    # in environments where mcpgateway isn't fully installed.
    from mcpgateway.plugins.framework.loader.plugin import PluginLoader  # noqa: PLC0415

    cfg = ConfigLoader.load_config("plugins/config.yaml")
    loader = PluginLoader()

    with caplog.at_level(logging.WARNING):
        for plugin_cfg in cfg.plugins:
            try:
                await loader.load_and_instantiate_plugin(plugin_cfg)
            except Exception:
                # Plugin construction may fail for connectivity / other
                # runtime reasons; the unknown-key warning fires earlier
                # at schema-validation time and is still captured.
                pass

    unknown_warnings = [
        r.getMessage()
        for r in caplog.records
        if "unknown config key" in r.getMessage().lower()
    ]
    assert not unknown_warnings, (
        f"plugins/config.yaml contains config keys the corresponding plugins "
        f"do not recognise.  Drop them from the yaml or fix typos.  "
        f"Captured warnings: {unknown_warnings}"
    )
