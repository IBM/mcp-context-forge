# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/make_enforce_config.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Derive a single-plugin enforce config from the committed plugin config.

The live-gateway plugin E2E suites boot the gateway with exactly one cpex
plugin active in ``enforce`` mode. Rather than committing a second, hand-edited
copy of each plugin block (which drifts whenever ``plugins/config.yaml``
changes), this script reads the real config and produces a throwaway config in
which:

* the target plugin's ``mode`` is set to ``enforce``,
* every other plugin's ``mode`` is forced to ``disabled`` (isolation), and
* ``plugin_settings.fail_on_plugin_error`` is set to ``true`` so a broken cpex
  wheel fails gateway boot loudly instead of being silently skipped.

Everything else (the plugin's ``kind``, ``hooks``, detector ``config``,
``priority``, ``conditions``, ``plugin_dirs``, other ``plugin_settings``) is
copied verbatim, so the E2E always exercises production's actual plugin shape.
``plugins/config.yaml`` therefore remains the single source of truth.

For the tool-plugin-bindings enforcement path the same script is run with
``--all-disabled``: every plugin (including the target) is forced to
``disabled`` so the gateway boots with the plugin loaded but inert, and a
runtime DB binding is what flips it to ``enforce`` for a specific team+tool.

Usage::

    # Static-config enforcement path
    python tests/live_gateway/plugins/make_enforce_config.py \
        --source plugins/config.yaml \
        --plugin SecretsDetection \
        --output /tmp/plugin_e2e_config.yaml

    # Tool-plugin-bindings enforcement path (plugin disabled in static config)
    python tests/live_gateway/plugins/make_enforce_config.py \
        --source plugins/config.yaml \
        --plugin SecretsDetection \
        --all-disabled \
        --output /tmp/plugin_e2e_config.yaml
"""

from __future__ import annotations

# Standard
import argparse
import json
import sys
from typing import Any

# Third-Party
import yaml


def build_enforce_config(
    config: dict,
    plugin_name: str,
    *,
    all_disabled: bool = False,
    config_overrides: dict[str, Any] | None = None,
) -> dict:
    """Return a copy of ``config`` scoped to a single plugin under test.

    Args:
        config: Parsed plugin configuration (the document loaded from
            ``plugins/config.yaml``).
        plugin_name: ``name`` of the plugin under test. It must exist in the
            config; this validates the build against the single source of truth.
        all_disabled: When ``True`` every plugin (including ``plugin_name``) is
            forced to ``disabled`` — the tool-plugin-bindings enforcement path,
            where a runtime DB binding does the enforcing. When ``False``
            (default) the target runs in ``enforce`` mode and all others in
            ``disabled`` — the static-config enforcement path.
        config_overrides: Optional ``config`` keys merged over the target
            plugin's committed ``config`` block. Used to keep the static path's
            effective config identical to the bindings path's ``config_overrides``
            (e.g. the SQL sanitizer scans only ``fields``, so the echo tool's
            ``message`` arg must be added to ``fields`` on both paths).

    Returns:
        The mutated config document with ``fail_on_plugin_error`` set to
        ``true`` so a broken cpex wheel fails gateway boot loudly.

    Raises:
        KeyError: If ``plugin_name`` is not present in the config.
    """
    plugins = config.get("plugins") or []
    names = [p.get("name") for p in plugins]
    if plugin_name not in names:
        raise KeyError(f"plugin {plugin_name!r} not found in config; available: {names}")

    for plugin in plugins:
        if all_disabled:
            plugin["mode"] = "disabled"
        else:
            plugin["mode"] = "enforce" if plugin.get("name") == plugin_name else "disabled"
        if config_overrides and plugin.get("name") == plugin_name:
            plugin_config = plugin.setdefault("config", {})
            plugin_config.update(config_overrides)

    settings = config.setdefault("plugin_settings", {})
    settings["fail_on_plugin_error"] = True
    return config


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (``0`` on success).
    """
    parser = argparse.ArgumentParser(description="Derive a single-plugin enforce config from the committed plugin config.")
    parser.add_argument("--source", default="plugins/config.yaml", help="Path to the committed plugin config (single source of truth).")
    parser.add_argument("--plugin", required=True, help="The plugin 'name' under test (e.g. SecretsDetection).")
    parser.add_argument(
        "--all-disabled",
        action="store_true",
        help="Force every plugin (including --plugin) to 'disabled' for the tool-plugin-bindings enforcement path.",
    )
    parser.add_argument(
        "--config-override",
        action="append",
        default=[],
        metavar="KEY=JSON",
        help="Override a key in the target plugin's 'config' block; value is parsed as JSON "
        "(e.g. --config-override 'fields=[\"sql\",\"query\",\"statement\",\"message\"]'). Repeatable.",
    )
    parser.add_argument("--output", required=True, help="Path to write the derived config.")
    args = parser.parse_args(argv)

    config_overrides: dict[str, Any] = {}
    for item in args.config_override:
        if "=" not in item:
            parser.error(f"--config-override must be KEY=JSON, got {item!r}")
        key, _, raw = item.partition("=")
        try:
            config_overrides[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            parser.error(f"--config-override {key!r} value is not valid JSON: {exc}")

    with open(args.source, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    config = build_enforce_config(config, args.plugin, all_disabled=args.all_disabled, config_overrides=config_overrides)

    with open(args.output, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, default_flow_style=False)

    mode_desc = "all-disabled (bindings path)" if args.all_disabled else "enforce"
    print(f"Wrote {mode_desc} config for {args.plugin!r} to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
