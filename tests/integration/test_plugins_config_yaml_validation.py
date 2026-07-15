# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_plugins_config_yaml_validation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Validation test for the gateway's shipped ``plugins/config.yaml``.

Pins one contract about the *yaml as shipped* matching the plugins it
configures: loading ``plugins/config.yaml`` and constructing each plugin
produces zero ``unknown config key`` warnings — every key in every plugin's
``config:`` block must be in that plugin's accepted schema.  Catches
stale / typo / aspirational keys before they reach operators' logs.

The schema-alignment check runs without Redis and stays green everywhere.
"""

# Standard
import logging

# Third-Party
import pytest

# First-Party
from cpex.framework import ConfigLoader


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
    """
    # Inject a default REDIS_URL so the rate-limiter's Jinja substitution
    # resolves even when the test runner hasn't set the env var.  The
    # plugin's connection attempt may still fail (no Redis required for
    # this test); we only care about warnings emitted at config-key
    # validation time, which precedes the network attempt.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # First-Party — local import so test-collection doesn't pay for it
    # in environments where mcpgateway isn't fully installed.
    from cpex.framework import PluginLoader  # noqa: PLC0415

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
