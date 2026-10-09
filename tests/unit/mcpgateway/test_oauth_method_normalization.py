# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_oauth_method_normalization.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

One normalization policy for ``token_endpoint_auth_method``, enforced.

The schema, the runtime dispatch, and the retry-time assertion refresh must read
this field identically. Three hand-matched copies previously disagreed -- one
stripped whitespace and another did not -- which signed a padded
``private_key_jwt`` config on the first attempt and then skipped refreshing it on
retry. These tests pin the shared function as the only path and parameterize the
full value matrix across every boundary, so a reimplementation anywhere fails
here rather than in production.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import inspect

# Third-Party
import pytest

# First-Party
from mcpgateway.common.oauth import (
    _EC_SIGNING_ALG_CURVES,
    DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD,
    MIN_RSA_KEY_SIZE_BITS,
    normalize_token_endpoint_auth_method,
    SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS,
    SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS,
)

# Legacy spellings of "no method configured". RFC 6749 Section 2.3.1 predates the
# field, so configurations written before it exists rely on the POST default.
_LEGACY_DEFAULT_VALUES = [None, "", "   ", "\t", "\n"]


class TestNormalizeTokenEndpointAuthMethod:
    """The shared policy function itself."""

    @pytest.mark.parametrize("value", _LEGACY_DEFAULT_VALUES)
    def test_legacy_values_resolve_to_the_post_default(self, value):
        assert normalize_token_endpoint_auth_method(value) == DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD

    def test_absent_value_resolves_to_the_post_default(self):
        # dict.get() returns None for a missing key, which is the absent case.
        assert normalize_token_endpoint_auth_method({}.get("token_endpoint_auth_method")) == DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD

    @pytest.mark.parametrize("method", sorted(SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS))
    def test_supported_methods_pass_through(self, method):
        assert normalize_token_endpoint_auth_method(method) == method

    @pytest.mark.parametrize("method", sorted(SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS))
    def test_surrounding_whitespace_is_stripped(self, method):
        assert normalize_token_endpoint_auth_method(f"  {method}  ") == method

    def test_case_is_preserved_so_the_caller_rejects_it(self):
        # Normalizing case would accept "PRIVATE_KEY_JWT" where the schema and the
        # signing path reject it. The function strips but never folds case.
        assert normalize_token_endpoint_auth_method("PRIVATE_KEY_JWT") == "PRIVATE_KEY_JWT"
        assert "PRIVATE_KEY_JWT" not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS

    def test_unsupported_string_passes_through_unchanged(self):
        # Rejection is the caller's job, so the caller can report "unsupported
        # method" rather than a missing-field error.
        assert normalize_token_endpoint_auth_method("bogus") == "bogus"

    @pytest.mark.parametrize("value", [123, ["private_key_jwt"], {"m": "x"}, 1.5, True])
    def test_non_string_values_return_none(self, value):
        # None signals "not a string" so the caller raises a type error instead of
        # an unhashable-value TypeError from set membership (CWE-20).
        assert normalize_token_endpoint_auth_method(value) is None

    def test_function_is_pure(self):
        # It must not write back into oauth_config: an update has to round-trip the
        # operator's submitted value, not a rewritten one.
        config = {"token_endpoint_auth_method": "   "}
        normalize_token_endpoint_auth_method(config.get("token_endpoint_auth_method"))
        assert config == {"token_endpoint_auth_method": "   "}


class TestNormalizationIsTheSolePath:
    """No consumer may reimplement the rule inline.

    Guards against the defect class rather than one instance. If someone adds a
    fourth consumer, or re-inlines the rule in an existing one, this fails.
    """

    @staticmethod
    def _source(obj) -> str:
        """Return the source of a function or method.

        Args:
            obj: Callable to read.

        Returns:
            str: Source text.
        """
        return inspect.getsource(obj)

    def test_schema_validator_uses_the_shared_function(self):
        # First-Party
        from mcpgateway.schemas import _validate_oauth_token_endpoint_auth

        source = self._source(_validate_oauth_token_endpoint_auth)
        assert "normalize_token_endpoint_auth_method" in source
        assert f'or "{DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD}"' not in source

    @pytest.mark.parametrize("method_name", ["_apply_token_endpoint_auth", "_refresh_client_assertion"])
    def test_runtime_consumers_use_the_shared_function(self, method_name):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        source = self._source(getattr(OAuthManager, method_name))
        assert "normalize_token_endpoint_auth_method" in source
        # The inline dance these used to carry.
        assert ".strip()" not in source.split("normalize_token_endpoint_auth_method")[0].split("auth_method")[-1]

    def test_gateway_gate_uses_the_shared_function(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        source = self._source(GatewayService._validate_private_key_jwt_config)
        assert "normalize_token_endpoint_auth_method" in source

    def test_no_consumer_hardcodes_the_default(self):
        # A hardcoded "client_secret_post" fallback outside the shared function is
        # how the boundaries drifted apart in the first place.
        # First-Party
        from mcpgateway.services import oauth_manager as runtime_module

        for method_name in ("_apply_token_endpoint_auth", "_refresh_client_assertion"):
            source = self._source(getattr(runtime_module.OAuthManager, method_name))
            assert f'= "{DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD}"' not in source, f"{method_name} reimplements the default inline"


class TestMethodMatrixAcrossEveryBoundary:
    """The same value must behave the same way at every boundary.

    Parameterized over absent, null, empty, whitespace-only, supported, and
    unsupported values, checked against the request schema (create and update)
    and the runtime dispatch.
    """

    @staticmethod
    def _oauth_config(method, sentinel="OMIT"):
        """Build a client_credentials oauth_config, optionally without the method key.

        Args:
            method: Value for ``token_endpoint_auth_method``.
            sentinel: Marker meaning "omit the key entirely".

        Returns:
            dict: oauth_config dict.
        """
        config = {
            "grant_type": "client_credentials",
            "client_id": "client-1",
            "client_secret": "secret-1",  # pragma: allowlist secret - fixture literal
            "token_url": "https://issuer.example.com/token",
        }
        if method is not sentinel:
            config["token_endpoint_auth_method"] = method
        return config

    @pytest.mark.parametrize("value", _LEGACY_DEFAULT_VALUES)
    def test_legacy_values_accepted_on_create(self, value):
        # First-Party
        from mcpgateway.schemas import GatewayCreate

        gateway = GatewayCreate(name="gw", url="https://example.com", oauth_config=self._oauth_config(value))
        assert gateway.oauth_config["token_endpoint_auth_method"] == value

    @pytest.mark.parametrize("value", _LEGACY_DEFAULT_VALUES)
    def test_legacy_values_accepted_on_update(self, value):
        # The reviewer's observed failure: GatewayUpdate rejected "" and "   " with
        # a 422 while the runtime defaulted them, so resubmitting a working config
        # broke it.
        # First-Party
        from mcpgateway.schemas import GatewayUpdate

        gateway = GatewayUpdate(oauth_config=self._oauth_config(value))
        assert gateway.oauth_config["token_endpoint_auth_method"] == value

    @pytest.mark.parametrize("value", _LEGACY_DEFAULT_VALUES)
    def test_legacy_values_use_post_auth_at_runtime(self, value):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        token_data: dict = {}
        headers: dict = {}
        credentials = {"client_id": "client-1", "client_secret": "secret-1", "token_endpoint_auth_method": value}  # pragma: allowlist secret - fixture literal
        asyncio.run(OAuthManager()._apply_token_endpoint_auth(token_data, headers, credentials))

        assert token_data == {"client_id": "client-1", "client_secret": "secret-1"}  # pragma: allowlist secret - fixture literal
        assert "Authorization" not in headers

    def test_absent_key_accepted_and_uses_post_auth(self):
        # First-Party
        from mcpgateway.schemas import GatewayCreate, GatewayUpdate
        from mcpgateway.services.oauth_manager import OAuthManager

        GatewayCreate(name="gw", url="https://example.com", oauth_config=self._oauth_config("OMIT"))
        GatewayUpdate(oauth_config=self._oauth_config("OMIT"))

        token_data: dict = {}
        asyncio.run(OAuthManager()._apply_token_endpoint_auth(token_data, {}, {"client_id": "client-1", "client_secret": "secret-1"}))  # pragma: allowlist secret - fixture literal
        assert token_data["client_id"] == "client-1"

    @pytest.mark.parametrize("method", sorted(SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS - {"private_key_jwt"}))
    def test_supported_methods_accepted_everywhere(self, method):
        # private_key_jwt is excluded because it additionally requires key
        # material; it has its own dedicated coverage.
        # First-Party
        from mcpgateway.schemas import GatewayCreate, GatewayUpdate

        GatewayCreate(name="gw", url="https://example.com", oauth_config=self._oauth_config(method))
        GatewayUpdate(oauth_config=self._oauth_config(method))

    @pytest.mark.parametrize("method", ["bogus", "client_secret_digest", "PRIVATE_KEY_JWT", "Client_Secret_Post"])
    def test_unsupported_methods_rejected_everywhere(self, method):
        # Third-Party
        from pydantic import ValidationError

        # First-Party
        from mcpgateway.schemas import GatewayCreate, GatewayUpdate
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        with pytest.raises(ValidationError):
            GatewayCreate(name="gw", url="https://example.com", oauth_config=self._oauth_config(method))
        with pytest.raises(ValidationError):
            GatewayUpdate(oauth_config=self._oauth_config(method))
        with pytest.raises(OAuthError, match="Unsupported token_endpoint_auth_method"):
            asyncio.run(OAuthManager()._apply_token_endpoint_auth({}, {}, {"client_id": "c", "token_endpoint_auth_method": method}))

    @pytest.mark.parametrize("method", [123, ["private_key_jwt"], {"m": "x"}])
    def test_non_string_methods_rejected_with_a_type_error_everywhere(self, method):
        # CWE-20: these must not reach set membership, which raises an unhashable
        # TypeError and surfaces as a 500.
        # Third-Party
        from pydantic import ValidationError

        # First-Party
        from mcpgateway.schemas import GatewayCreate, GatewayUpdate
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        with pytest.raises(ValidationError, match="must be a string"):
            GatewayCreate(name="gw", url="https://example.com", oauth_config=self._oauth_config(method))
        with pytest.raises(ValidationError, match="must be a string"):
            GatewayUpdate(oauth_config=self._oauth_config(method))
        with pytest.raises(OAuthError, match="must be a string"):
            asyncio.run(OAuthManager()._apply_token_endpoint_auth({}, {}, {"client_id": "c", "token_endpoint_auth_method": method}))


class TestSigningAlgorithmInvariants:
    """Properties the algorithm checks rely on, pinned so they cannot silently lapse."""

    def test_every_supported_alg_is_classified(self):
        # First-Party
        from mcpgateway.common.oauth import _RSA_SIGNING_ALGS

        unclassified = SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS - _RSA_SIGNING_ALGS - set(_EC_SIGNING_ALG_CURVES)
        assert not unclassified, f"these algorithms match neither the RSA set nor the EC curve map: {sorted(unclassified)}"

    def test_ec_curve_map_covers_every_ec_alg(self):
        # validate_loaded_private_key indexes _EC_SIGNING_ALG_CURVES directly for
        # any non-RSA algorithm, so a missing entry would raise KeyError rather
        # than reject the key. This is what makes the absent EC size floor safe.
        # First-Party
        from mcpgateway.common.oauth import _RSA_SIGNING_ALGS

        ec_algs = SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS - _RSA_SIGNING_ALGS
        assert ec_algs == set(_EC_SIGNING_ALG_CURVES), "an ES algorithm was added without a curve entry; validate_loaded_private_key would raise KeyError"

    def test_rsa_floor_matches_the_jws_requirement(self):
        # RFC 7518 Sections 3.3 and 3.5.
        assert MIN_RSA_KEY_SIZE_BITS == 2048
