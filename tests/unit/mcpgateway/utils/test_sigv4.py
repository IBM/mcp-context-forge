# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sigv4.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the SigV4 request signer.
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
import re
from unittest.mock import patch

# Third-Party
import httpx
import httpx2
import pytest

# First-Party
from mcpgateway.utils.sigv4 import (
    _canonical_query,
    _canonical_uri,
    build_gateway_sigv4_auth,
    build_sigv4_signer,
    build_stored_sigv4_auth,
    build_stored_sigv4_httpx_auth,
    decrypt_sigv4_secret,
    derive_signing_key,
    encrypt_sigv4_secret,
    SigV4Auth,
    SigV4ConfigError,
    SigV4Credentials,
    SigV4HttpxAuth,
    SigV4Signer,
    sigv4_client_factory,
    UNSIGNED_PAYLOAD,
    validate_sigv4_config,
    with_sigv4_auth,
)

# Credentials published with the AWS Signature Version 4 test suite.
SUITE_ACCESS_KEY = "AKIDEXAMPLE"
SUITE_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
SUITE_TIME = datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

VALID_CONFIG = {
    "access_key_id": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
    "secret_access_key": SUITE_SECRET,
    "region": "us-east-1",
    "service": "execute-api",
}


def _suite_signer(service: str = "service") -> SigV4Signer:
    creds = SigV4Credentials(access_key_id=SUITE_ACCESS_KEY, secret_access_key=SUITE_SECRET, region="us-east-1", service=service)
    return SigV4Signer(creds, clock=lambda: SUITE_TIME)


class TestAwsSuiteVectors:
    """Check the signer against the published AWS SigV4 test suite."""

    def test_signing_key_vector(self):
        key = derive_signing_key(SUITE_SECRET, "20150830", "us-east-1", "iam")
        assert key.hex() == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"  # pragma: allowlist secret

    def test_get_vanilla(self):
        headers = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        auth = _suite_signer().authorization_header("GET", "https://example.amazonaws.com/", headers, EMPTY_SHA256, "20150830T123600Z")
        assert auth == (
            "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
            "SignedHeaders=host;x-amz-date, Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"  # pragma: allowlist secret
        )

    def test_get_vanilla_query_order(self):
        headers = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        auth = _suite_signer().authorization_header("GET", "https://example.amazonaws.com/?Param2=value2&Param1=value1", headers, EMPTY_SHA256, "20150830T123600Z")
        assert auth.endswith("Signature=b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500")  # pragma: allowlist secret

    def test_post_vanilla(self):
        headers = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        auth = _suite_signer().authorization_header("POST", "https://example.amazonaws.com/", headers, EMPTY_SHA256, "20150830T123600Z")
        assert auth.endswith("Signature=5da7c1a2acd57cee7505fc6676e4e544621c30862966e37dddb68e92efbe5d6b")  # pragma: allowlist secret

    def test_get_space_path_is_double_encoded(self):
        headers = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        auth = _suite_signer().authorization_header("GET", "https://example.amazonaws.com/example space/", headers, EMPTY_SHA256, "20150830T123600Z")
        assert auth.endswith("Signature=652487583200325589f1fba4c7e578f72c47cb61beeca81406b39ddec1366741")  # pragma: allowlist secret


class TestCanonicalization:
    """Canonical URI and query rules, cross-checked against botocore output."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/", "/"),
            ("", "/"),
            ("/a/./b//c/", "/a/b/c/"),
            ("//example//", "/example/"),
            ("/v1/a%20b/../c", "/v1/c"),
            ("/a/../../b", "/b"),
            ("/example space/", "/example%20space/"),
        ],
    )
    def test_canonical_uri(self, path, expected):
        assert _canonical_uri(path, double_encode=True) == expected

    def test_s3_path_kept_verbatim(self):
        assert _canonical_uri("/a%20b//c", double_encode=False) == "/a%20b//c"

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("", ""),
            ("Param2=value2&Param1=value1", "Param1=value1&Param2=value2"),
            ("x=a+b&y=%7E&z=", "x=a%20b&y=~&z="),
            ("q=%E2%82%AC&a=b%2Bc", "a=b%2Bc&q=%E2%82%AC"),
            ("a=2&a=1", "a=1&a=2"),
        ],
    )
    def test_canonical_query(self, query, expected):
        assert _canonical_query(query) == expected


class TestSigner:
    """Behavior of SigV4Signer.sign()."""

    def _signer(self, *, session_token=None, unsigned=False, now=SUITE_TIME):
        creds = SigV4Credentials.from_config({**VALID_CONFIG, **({"session_token": session_token} if session_token else {})})
        return SigV4Signer(creds, unsigned_payload=unsigned, clock=lambda: now)

    def test_sign_hashes_exact_body(self):
        body = b'{"a": 1}'
        signed = self._signer().sign("POST", "https://api.example.com/p", {"host": "api.example.com"}, body)
        assert signed["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
        assert signed["x-amz-date"] == "20150830T123600Z"
        assert "x-amz-security-token" not in signed
        assert re.match(
            r"^AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20150830/us-east-1/execute-api/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=[0-9a-f]{64}$",  # pragma: allowlist secret
            signed["Authorization"],
        )

    def test_sign_covers_session_token(self):
        signed = self._signer(session_token="tok").sign("GET", "https://api.example.com/", {"host": "api.example.com"}, b"")
        assert signed["x-amz-security-token"] == "tok"
        assert "x-amz-security-token" in signed["Authorization"]

    def test_unsigned_payload_is_opt_in(self):
        signed = self._signer(unsigned=True).sign("POST", "https://api.example.com/", {"host": "api.example.com"}, b"body")
        assert signed["x-amz-content-sha256"] == UNSIGNED_PAYLOAD

    def test_body_change_changes_signature(self):
        signer = self._signer()
        first = signer.sign("POST", "https://api.example.com/", {"host": "api.example.com"}, b"one")
        second = signer.sign("POST", "https://api.example.com/", {"host": "api.example.com"}, b"two")
        assert first["Authorization"] != second["Authorization"]

    def test_fresh_timestamp_per_call(self):
        times = iter([SUITE_TIME, SUITE_TIME + timedelta(minutes=16)])
        creds = SigV4Credentials.from_config(VALID_CONFIG)
        signer = SigV4Signer(creds, clock=lambda: next(times))
        first = signer.sign("GET", "https://api.example.com/", {"host": "api.example.com"}, b"")
        second = signer.sign("GET", "https://api.example.com/", {"host": "api.example.com"}, b"")
        assert first["x-amz-date"] != second["x-amz-date"]
        assert first["Authorization"] != second["Authorization"]

    def test_signing_key_cached_per_day(self):
        signer = self._signer()
        signer.sign("GET", "https://api.example.com/", {"host": "api.example.com"}, b"")
        cached = signer._cached_key
        signer.sign("GET", "https://api.example.com/x", {"host": "api.example.com"}, b"")
        assert signer._cached_key is cached

    def test_missing_host_rejected(self):
        with pytest.raises(SigV4ConfigError):
            self._signer().sign("GET", "https://api.example.com/", {}, b"")

    def test_s3_path_is_not_double_encoded(self):
        creds = SigV4Credentials.from_config({**VALID_CONFIG, "service": "s3"})
        s3 = SigV4Signer(creds, clock=lambda: SUITE_TIME)
        other = self._signer()
        args = ("GET", "https://b.s3.amazonaws.com/a%20b", {"host": "b.s3.amazonaws.com"}, b"")
        assert s3.sign(*args)["Authorization"] != other.sign(*args)["Authorization"]


class TestAuthFlow:
    """SigV4Auth and SigV4HttpxAuth sign each request that passes through a real client."""

    @staticmethod
    def _signer(counter):
        creds = SigV4Credentials.from_config(VALID_CONFIG)

        def clock():
            counter["n"] += 1
            return SUITE_TIME + timedelta(minutes=16 * counter["n"])

        return SigV4Signer(creds, clock=clock)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lib,auth_cls", [(httpx2, SigV4Auth), (httpx, SigV4HttpxAuth)])
    async def test_every_request_is_signed_afresh(self, lib, auth_cls):
        seen = []

        def handler(request):
            seen.append((request.headers["x-amz-date"], request.headers["authorization"], request.headers["x-amz-content-sha256"], request.content))
            return lib.Response(200, json={})

        counter = {"n": 0}
        auth = auth_cls(self._signer(counter))
        async with lib.AsyncClient(transport=lib.MockTransport(handler), auth=auth, base_url="https://api.example.com") as client:
            await client.post("/v1", json={"k": "v1"})
            await client.post("/v1", json={"k": "v2"})

        assert len(seen) == 2
        assert seen[0][0] != seen[1][0]
        assert seen[0][1] != seen[1][1]
        for _date, _auth, body_hash, body in seen:
            assert body_hash == hashlib.sha256(body).hexdigest()

    @pytest.mark.asyncio
    async def test_stale_signature_headers_are_replaced(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get_list("authorization")
            return httpx2.Response(200)

        auth = SigV4Auth(self._signer({"n": 0}))
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=auth, base_url="https://api.example.com") as client:
            await client.get("/", headers={"Authorization": "Bearer inbound-token"})
        assert len(seen["auth"]) == 1
        assert seen["auth"][0].startswith("AWS4-HMAC-SHA256 ")


class TestConfigValidation:
    """validate_sigv4_config and SigV4Credentials."""

    def test_valid(self):
        assert validate_sigv4_config(VALID_CONFIG)["region"] == "us-east-1"

    @pytest.mark.parametrize("missing", ["access_key_id", "secret_access_key", "region", "service"])
    def test_required_fields(self, missing):
        config = {k: v for k, v in VALID_CONFIG.items() if k != missing}
        with pytest.raises(SigV4ConfigError, match=missing):
            validate_sigv4_config(config)

    @pytest.mark.parametrize("field,value", [("region", "US_EAST"), ("service", "exec/ute"), ("access_key_id", "short")])
    def test_malformed_fields(self, field, value):
        with pytest.raises(SigV4ConfigError):
            validate_sigv4_config({**VALID_CONFIG, field: value})

    def test_unknown_key_rejected(self):
        with pytest.raises(SigV4ConfigError, match="unsupported"):
            validate_sigv4_config({**VALID_CONFIG, "extra": "x"})

    def test_not_a_mapping(self):
        with pytest.raises(SigV4ConfigError):
            validate_sigv4_config("nope")

    def test_session_token_must_be_string(self):
        with pytest.raises(SigV4ConfigError):
            validate_sigv4_config({**VALID_CONFIG, "session_token": 5})

    def test_blank_session_token_dropped(self):
        assert "session_token" not in validate_sigv4_config({**VALID_CONFIG, "session_token": "  "})

    def test_repr_hides_secrets(self):
        creds = SigV4Credentials.from_config({**VALID_CONFIG, "session_token": "SESSIONTOKENVALUE"})
        text = repr(creds)
        assert SUITE_SECRET not in text
        assert "SESSIONTOKENVALUE" not in text

    def test_fingerprint_is_stable_and_non_secret(self):
        creds = SigV4Credentials.from_config(VALID_CONFIG)
        assert creds.key_fingerprint == creds.key_fingerprint
        assert len(creds.key_fingerprint) == 12
        assert creds.access_key_id not in creds.key_fingerprint

    def test_build_signer(self):
        assert isinstance(build_sigv4_signer(VALID_CONFIG), SigV4Signer)


class TestStoredConfig:
    """Stored configs hold encrypted secrets and decrypt only for runtime use."""

    @pytest.fixture
    def stored(self):
        return {**VALID_CONFIG, "secret_access_key": encrypt_sigv4_secret("secret_access_key", SUITE_SECRET), "session_token": encrypt_sigv4_secret("session_token", "tok")}

    def test_build_from_stored(self, stored):
        auth = build_stored_sigv4_auth(stored)
        assert isinstance(auth, SigV4Auth)
        assert auth.signer.credentials.secret_access_key == SUITE_SECRET
        assert auth.signer.credentials.session_token == "tok"

    def test_build_from_stored_never_runs_the_memory_hard_kdf(self, stored):
        """Runtime decryption runs on the event loop, so it must not derive an Argon2id key."""
        with patch("mcpgateway.services.encryption_service.EncryptionService.derive_key_argon2id", side_effect=AssertionError("Argon2id on the request path")):
            assert isinstance(build_stored_sigv4_auth(stored), SigV4Auth)
            assert isinstance(build_stored_sigv4_httpx_auth(stored), SigV4HttpxAuth)

    def test_ciphertext_is_bound_to_its_field(self):
        """A value stored for one field must not decrypt as another field."""
        blob = encrypt_sigv4_secret("session_token", "tok")
        assert decrypt_sigv4_secret("session_token", blob) == "tok"
        assert decrypt_sigv4_secret("secret_access_key", blob) is None
        with pytest.raises(SigV4ConfigError):
            encrypt_sigv4_secret("region", "us-east-1")

    def test_swapped_secret_fields_are_rejected(self, stored):
        swapped = {**stored, "secret_access_key": stored["session_token"]}
        with pytest.raises(SigV4ConfigError):
            build_stored_sigv4_auth(swapped)

    def test_build_httpx_from_stored(self, stored):
        assert isinstance(build_stored_sigv4_httpx_auth(stored), SigV4HttpxAuth)

    def test_none_when_unset(self):
        assert build_stored_sigv4_auth(None) is None
        assert build_stored_sigv4_auth({}) is None
        assert build_stored_sigv4_httpx_auth(None) is None


class TestFactoryWrapper:
    """with_sigv4_auth supplies the auth argument every upstream client factory already accepts."""

    def test_passthrough_without_auth(self):
        def factory(headers=None, timeout=None, auth=None):
            return "client"

        assert with_sigv4_auth(factory, None) is factory

    def test_injects_auth_and_ignores_caller_auth(self):
        received = {}

        def factory(headers=None, timeout=None, auth=None):
            received.update(headers=headers, timeout=timeout, auth=auth)
            return "client"

        sentinel = object()
        wrapped = with_sigv4_auth(factory, sentinel)
        assert wrapped(headers={"a": "b"}, timeout=5, auth=None) == "client"
        assert received == {"headers": {"a": "b"}, "timeout": 5, "auth": sentinel}
        wrapped(headers=None, timeout=None, auth="caller-auth")  # pragma: allowlist secret
        assert received["auth"] is sentinel


class TestGatewayHelpers:
    """build_gateway_sigv4_auth and sigv4_client_factory feed the non-registry session paths."""

    def test_non_sigv4_gateway_has_no_signer(self):
        assert build_gateway_sigv4_auth("bearer", None) is None
        assert build_gateway_sigv4_auth(None, {"anything": 1}) is None

    def test_sigv4_gateway_without_config_fails_closed(self):
        with pytest.raises(SigV4ConfigError):
            build_gateway_sigv4_auth("sigv4", None)
        with pytest.raises(SigV4ConfigError):
            build_gateway_sigv4_auth("sigv4", {})

    def test_sigv4_gateway_builds_signer(self):
        stored = {**VALID_CONFIG, "secret_access_key": encrypt_sigv4_secret("secret_access_key", SUITE_SECRET)}
        assert isinstance(build_gateway_sigv4_auth("sigv4", stored), SigV4Auth)

    def test_client_factory_none_without_signer(self):
        assert sigv4_client_factory(None) is None

    @pytest.mark.asyncio
    async def test_client_factory_builds_signing_client(self):
        signer = build_stored_sigv4_auth(None) or SigV4Auth(build_sigv4_signer(VALID_CONFIG))
        factory = sigv4_client_factory(signer)
        client = factory({"X-Test": "1"}, None, None)
        try:
            assert isinstance(client, httpx2.AsyncClient)
            assert client.auth is signer
            assert client.headers["X-Test"] == "1"
        finally:
            await client.aclose()
