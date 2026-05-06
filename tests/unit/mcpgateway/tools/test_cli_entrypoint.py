# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/test_cli_entrypoint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for mcpgateway.tools.cli entrypoint.
"""

# First-Party
import mcpgateway.tools.cli as cforge_cli


def test_main_calls_typer_app(monkeypatch) -> None:
    called: dict[str, object] = {}

    def _fake_app(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(cforge_cli, "app", _fake_app)

    cforge_cli.main()

    assert called["args"] == ()
    assert called["kwargs"] == {"obj": {}}
