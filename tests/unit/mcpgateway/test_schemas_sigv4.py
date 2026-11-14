# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_schemas_sigv4.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Schema, masking and storage-encryption tests for gateway auth_type "sigv4".
"""

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate
from mcpgateway.services.encryption_service import protect_sigv4_config_for_storage
from mcpgateway.utils.sigv4 import decrypt_sigv4_secret, is_encrypted_sigv4_secret

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
CONFIG = {"access_key_id": "AKIAIOSFODNN7EXAMPLE", "secret_access_key": SECRET, "region": "us-east-1", "service": "execute-api"}  # pragma: allowlist secret


def _create(**overrides):
    data = {"name": "aws-gw", "url": "https://api.example.com/mcp", "auth_type": "sigv4", "sigv4_config": dict(CONFIG)}
    data.update(overrides)
    return GatewayCreate(**data)


class TestGatewayCreate:
    def test_accepts_sigv4(self):
        gateway = _create()
        assert gateway.auth_type == "sigv4"
        assert gateway.auth_value is None
        assert gateway.sigv4_config["region"] == "us-east-1"

    def test_requires_config(self):
        with pytest.raises(ValidationError, match="sigv4_config is required"):
            _create(sigv4_config=None)

    @pytest.mark.parametrize("missing", ["access_key_id", "secret_access_key", "region", "service"])
    def test_requires_each_field(self, missing):
        config = {k: v for k, v in CONFIG.items() if k != missing}
        with pytest.raises(ValidationError, match=missing):
            _create(sigv4_config=config)

    def test_rejects_masked_secret_on_create(self):
        with pytest.raises(ValidationError, match="real secret_access_key"):
            _create(sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value})

    def test_rejects_config_without_sigv4_auth(self):
        with pytest.raises(ValidationError, match="only valid when auth_type is 'sigv4'"):
            _create(auth_type="bearer", auth_token="t", sigv4_config=dict(CONFIG))

    def test_session_token_optional(self):
        assert _create(sigv4_config={**CONFIG, "session_token": "tok"}).sigv4_config["session_token"] == "tok"

    def test_unknown_auth_type_still_rejected(self):
        with pytest.raises(ValidationError, match="Invalid 'auth_type'"):
            _create(auth_type="awsv5", sigv4_config=None)

    def test_other_auth_types_unchanged(self):
        gateway = _create(auth_type="bearer", auth_token="abc", sigv4_config=None)
        assert gateway.auth_value is not None
        assert gateway.sigv4_config is None


class TestGatewayUpdate:
    def test_accepts_sigv4_update(self):
        update = GatewayUpdate(auth_type="sigv4", sigv4_config=dict(CONFIG))
        assert update.auth_type == "sigv4"

    def test_masked_secret_allowed_on_update(self):
        update = GatewayUpdate(sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value})
        assert update.sigv4_config["secret_access_key"] == settings.masked_auth_value

    def test_malformed_region_rejected(self):
        with pytest.raises(ValidationError, match="region"):
            GatewayUpdate(sigv4_config={**CONFIG, "region": "US EAST"})


class TestGatewayReadMasking:
    def _read(self, **extra):
        return GatewayRead.model_validate(
            {
                "id": "gw1",
                "name": "aws-gw",
                "url": "https://api.example.com/mcp",
                "auth_type": "sigv4",
                "sigv4_config": {**CONFIG, "session_token": "SESSIONTOKENVALUE", **extra},
            }
        )

    def test_masked_hides_secrets_but_keeps_scope(self):
        masked = self._read().masked()
        assert masked.sigv4_config["secret_access_key"] == settings.masked_auth_value
        assert masked.sigv4_config["session_token"] == settings.masked_auth_value
        assert masked.sigv4_config["access_key_id"] == CONFIG["access_key_id"]
        assert masked.sigv4_config["region"] == "us-east-1"
        assert SECRET not in masked.model_dump_json()
        assert "SESSIONTOKENVALUE" not in masked.model_dump_json()

    def test_no_session_token_stays_empty(self):
        read = GatewayRead.model_validate({"id": "gw1", "name": "n", "url": "https://a.example.com", "auth_type": "sigv4", "sigv4_config": dict(CONFIG)})
        assert "session_token" not in read.masked().sigv4_config

    def test_read_without_sigv4_unaffected(self):
        read = GatewayRead.model_validate({"id": "gw1", "name": "n", "url": "https://a.example.com"})
        assert read.masked().sigv4_config is None


class TestStorageEncryption:
    @pytest.mark.asyncio
    async def test_secrets_encrypted_other_fields_plain(self):
        stored = await protect_sigv4_config_for_storage({**CONFIG, "session_token": "tok"})
        assert stored["secret_access_key"] != SECRET
        assert stored["session_token"] != "tok"
        assert is_encrypted_sigv4_secret("secret_access_key", stored["secret_access_key"])
        assert decrypt_sigv4_secret("secret_access_key", stored["secret_access_key"]) == SECRET
        assert decrypt_sigv4_secret("session_token", stored["session_token"]) == "tok"
        assert stored["access_key_id"] == CONFIG["access_key_id"]
        assert SECRET not in str(stored)

    @pytest.mark.asyncio
    async def test_masked_placeholder_keeps_existing_ciphertext(self):
        existing = await protect_sigv4_config_for_storage(dict(CONFIG))
        updated = await protect_sigv4_config_for_storage({**CONFIG, "secret_access_key": settings.masked_auth_value, "region": "eu-west-1"}, existing)
        assert updated["secret_access_key"] == existing["secret_access_key"]
        assert updated["region"] == "eu-west-1"

    @pytest.mark.asyncio
    async def test_already_encrypted_not_double_encrypted(self):
        first = await protect_sigv4_config_for_storage(dict(CONFIG))
        second = await protect_sigv4_config_for_storage(first)
        assert second["secret_access_key"] == first["secret_access_key"]

    @pytest.mark.asyncio
    async def test_none(self):
        assert await protect_sigv4_config_for_storage(None) is None
