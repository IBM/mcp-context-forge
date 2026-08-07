# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Simple-token minting warning.
"""

# First-Party
from mcpgateway.utils.create_jwt_token import _warn_if_simple_token_for_admin


def test_warns_when_simple_token_requested_for_admin(capsys):
    _warn_if_simple_token_for_admin(username="admin@example.com", rich_mode=False, is_known_admin=True)
    err = capsys.readouterr().err
    assert "public-only" in err
    assert "--admin" in err


def test_silent_in_rich_mode(capsys):
    _warn_if_simple_token_for_admin(username="admin@example.com", rich_mode=True, is_known_admin=True)
    assert capsys.readouterr().err == ""


def test_silent_for_non_admin(capsys):
    _warn_if_simple_token_for_admin(username="user@example.com", rich_mode=False, is_known_admin=False)
    assert capsys.readouterr().err == ""
