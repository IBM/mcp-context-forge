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
import pathlib

# Third-Party
import pytest

# First-Party
from cpex.framework import ConfigLoader, PluginLoader

# Anchor the config path to this file's location so the test works regardless
# of the directory pytest is invoked from (repo root, tests/, etc.).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_YAML = str(_REPO_ROOT / "plugins" / "config.yaml")


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

    This test is the regression guard against that drift.  It loads the yaml
    and loads each plugin through the framework loader (which invokes the
    plugin's ``__init__`` and therefore any unknown-key warnings), then asserts
    the captured log records contain none of those warnings.

    Loads that raise (e.g. a plugin whose optional dependency is absent) are
    tolerated — that's not a *schema* concern, and the unknown-key warning
    fires during loading regardless.
    """
    # Inject a default REDIS_URL so the rate-limiter's Jinja substitution
    # resolves even when the test runner hasn't set the env var.  The
    # plugin's connection attempt may still fail (no Redis required for
    # this test); we only care about warnings emitted at config-key
    # validation time, which precedes the network attempt.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    cfg = ConfigLoader.load_config(_CONFIG_YAML)
    loader = PluginLoader()

    constructed = 0
    with caplog.at_level(logging.WARNING):
        for plugin_cfg in cfg.plugins:
            try:
                # Load via the framework loader (build + initialise) — the same
                # path the gateway uses at startup.  We keep initialise() rather
                # than only constructing so the guard mirrors real startup and
                # still catches unknown-key warnings even if a future plugin
                # surfaces them at initialise() instead of __init__.
                await loader.load_and_instantiate_plugin(plugin_cfg)
                constructed += 1
            except Exception:
                # A plugin may fail to load (optional dependency absent, etc.);
                # the unknown-key warning fires during loading and is still captured.
                pass

    # Fail rather than pass on zero checks: an empty config or an all-failed
    # load would otherwise verify nothing.
    assert constructed, "No plugins were loaded from plugins/config.yaml — check the config path."

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
