# -*- coding: utf-8 -*-
"""Extra tests for main helpers."""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway import main


def test_get_user_email_variants():
    assert main.get_user_email({"email": "a@example.com"}) == "a@example.com"
    assert main.get_user_email({"sub": "b@example.com"}) == "b@example.com"
    assert main.get_user_email({"username": "x"}) == "unknown"
    assert main.get_user_email("c@example.com") == "c@example.com"
    assert main.get_user_email(None) == "unknown"


def test_get_token_teams_and_rpc_context():
    req = MagicMock()
    req.state = MagicMock()
    req.state._jwt_verified_payload = ("token", {"teams": ["t1"], "is_admin": True})

    email, teams, is_admin = main._get_rpc_filter_context(req, {"email": "user@example.com"})

    assert email == "user@example.com"
    assert teams == ["t1"]
    assert is_admin is True


def test_jsonpath_modifier_valid_and_invalid():
    assert main.jsonpath_modifier({"a": 1}, "$.a") == [1]

    with pytest.raises(HTTPException):
        main.jsonpath_modifier({"a": 1}, "$[")


def test_transform_data_with_mappings():
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    mappings = {"x": "$.a"}
    result = main.transform_data_with_mappings(data, mappings)

    assert result == [{"x": 1}, {"x": 3}]


def test_validate_security_configuration(monkeypatch: pytest.MonkeyPatch):
    warnings = ["warn1"]
    monkeypatch.setattr(main.settings, "get_security_status", lambda: {"warnings": warnings, "secure_secrets": False, "auth_enabled": False})
    monkeypatch.setattr(main.settings, "require_strong_secrets", False)
    monkeypatch.setattr(main.settings, "jwt_secret_key", "my-test-key")
    monkeypatch.setattr(main.settings, "basic_auth_password", SimpleNamespace(get_secret_value=lambda: "changeme"))
    monkeypatch.setattr(main.settings, "mcpgateway_ui_enabled", True)
    monkeypatch.setattr(main.settings, "environment", "production")
    monkeypatch.setattr(main.settings, "jwt_issuer", "mcpgateway")
    monkeypatch.setattr(main.settings, "jwt_audience", "mcpgateway-api")

    main.validate_security_configuration()


def test_log_critical_issues_enforced(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.settings, "require_strong_secrets", True)

    with pytest.raises(SystemExit):
        main.log_critical_issues(["issue"])
