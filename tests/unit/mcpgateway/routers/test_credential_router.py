# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_credential_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Unit tests for Credential Router endpoints."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.routers.credential_router import (
    CredentialStoreRequest,
    _extract_is_admin,
    _extract_user_email,
)


# ---------- Helper function tests ----------


def test_extract_user_email_from_response():
    user = MagicMock(email="Admin@Test.Com")
    assert _extract_user_email(user) == "admin@test.com"


def test_extract_user_email_from_dict():
    user = {"email": "USER@Example.COM"}
    assert _extract_user_email(user) == "user@example.com"


def test_extract_user_email_none():
    assert _extract_user_email({}) is None
    assert _extract_user_email(MagicMock(spec=[])) is None


def test_extract_is_admin_true():
    user = MagicMock(is_admin=True)
    assert _extract_is_admin(user) is True


def test_extract_is_admin_false():
    user = MagicMock(is_admin=False)
    assert _extract_is_admin(user) is False


def test_extract_is_admin_from_dict():
    assert _extract_is_admin({"is_admin": True}) is True
    assert _extract_is_admin({"is_admin": False}) is False


# ---------- Request model tests ----------


def test_credential_store_request_valid():
    req = CredentialStoreRequest(
        credential_type="api_key",
        credential_value="my-secret",
        label="Test",
    )
    assert req.credential_type == "api_key"
    assert req.credential_value == "my-secret"
    assert req.label == "Test"


def test_credential_store_request_no_label():
    req = CredentialStoreRequest(
        credential_type="bearer_token",
        credential_value="tok",
    )
    assert req.label is None


def test_credential_store_request_empty_value():
    with pytest.raises(Exception):
        CredentialStoreRequest(
            credential_type="api_key",
            credential_value="",
        )
