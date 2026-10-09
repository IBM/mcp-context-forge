# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_private_key_jwt_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Deep validation of private_key_jwt key material at the persistence boundary.

Covers the pure helper in ``mcpgateway.common.oauth`` and the service-layer gate
in ``GatewayService._validate_private_key_jwt_config`` that decides which inbound
values are raw PEM worth parsing.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
import pytest

# First-Party
from mcpgateway.common.oauth import _EC_SIGNING_ALG_CURVES, _RSA_SIGNING_ALGS, SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS, validate_private_key_material
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayUpdate
from mcpgateway.services.encryption_service import get_encryption_service, protect_oauth_config_for_storage
from mcpgateway.services.gateway_service import GatewayError, GatewayService

MALFORMED_KEY = "dummy-private-key-material"  # pragma: allowlist secret

# Composed at runtime rather than written literally. The pre-commit
# detect-private-key hook matches this marker as a substring and cannot tell a
# negative assertion from real key material, so a literal would fail CI. Keeping
# it composed lets the hook keep scanning this file for genuine keys instead of
# adding the file to the hook's exclude list.
PEM_HEADER = "-----" + "BEGIN" + " PRIVATE KEY-----"


def _pem(key) -> str:
    """Serialize a private key to unencrypted PKCS8 PEM.

    Args:
        key: A cryptography private key object.

    Returns:
        str: PEM-encoded private key.
    """
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def _rsa_pem() -> str:
    """Return an unencrypted RSA private key PEM.

    Returns:
        str: PEM-encoded RSA private key.
    """
    return _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))


def _ec_pem(curve) -> str:
    """Return an unencrypted EC private key PEM on *curve*.

    Args:
        curve: Elliptic curve instance.

    Returns:
        str: PEM-encoded EC private key.
    """
    return _pem(ec.generate_private_key(curve))


def _oauth_config(**overrides) -> dict:
    """Build a private_key_jwt oauth_config.

    Args:
        **overrides: Fields to override on the base config.

    Returns:
        dict: oauth_config dict.
    """
    config = {
        "client_id": "client-1",
        "token_url": "https://issuer.example.com/token",
        "token_endpoint_auth_method": "private_key_jwt",
        "private_key": _rsa_pem(),
    }
    config.update(overrides)
    return config


class TestValidatePrivateKeyMaterial:
    """The pure PEM/algorithm helper."""

    def test_valid_rsa_key_accepted(self):
        validate_private_key_material(_rsa_pem(), "RS256")

    def test_alg_defaults_to_rs256_when_omitted(self):
        validate_private_key_material(_rsa_pem(), None)

    @pytest.mark.parametrize("alg", ["RS256", "RS384", "RS512", "PS256"])
    def test_all_rsa_algs_accept_rsa_key(self, alg):
        validate_private_key_material(_rsa_pem(), alg)

    @pytest.mark.parametrize(
        "alg,curve",
        [("ES256", ec.SECP256R1()), ("ES384", ec.SECP384R1()), ("ES512", ec.SECP521R1())],
    )
    def test_ec_algs_accept_matching_curve(self, alg, curve):
        validate_private_key_material(_ec_pem(curve), alg)

    def test_malformed_pem_rejected(self):
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            validate_private_key_material(MALFORMED_KEY, "RS256")

    def test_public_key_pem_rejected(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            validate_private_key_material(public_pem, "RS256")

    def test_passphrase_protected_key_rejected(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        encrypted_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"passphrase"),
        ).decode()
        with pytest.raises(ValueError, match="passphrase-protected"):
            validate_private_key_material(encrypted_pem, "RS256")

    def test_rsa_key_with_ec_alg_rejected(self):
        with pytest.raises(ValueError, match="must be an EC private key"):
            validate_private_key_material(_rsa_pem(), "ES256")

    def test_ec_key_with_rsa_alg_rejected(self):
        with pytest.raises(ValueError, match="must be an RSA private key"):
            validate_private_key_material(_ec_pem(ec.SECP256R1()), "RS256")

    def test_ec_curve_mismatch_rejected(self):
        # ES512 requires P-521, not P-256. PyJWT raises InvalidKeyError at sign
        # time on this pair, so rejecting it at config time is the whole point.
        with pytest.raises(ValueError, match="curve does not match"):
            validate_private_key_material(_ec_pem(ec.SECP256R1()), "ES512")

    def test_unsupported_alg_rejected(self):
        with pytest.raises(ValueError, match="token_endpoint_auth_signing_alg is not allowed"):
            validate_private_key_material(_rsa_pem(), "HS256")

    @pytest.mark.parametrize("alg", ["rs256", "Rs256", " RS256 ", "es256"])
    def test_alg_matched_case_sensitively(self, alg):
        # The schema (schemas.py) and the signing path (oauth_manager.py) both test
        # membership against SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS without
        # normalizing, so this helper must not normalize either. Accepting "rs256"
        # here while the other two reject it is the config/runtime drift this PR
        # exists to remove.
        with pytest.raises(ValueError, match="token_endpoint_auth_signing_alg is not allowed"):
            validate_private_key_material(_rsa_pem(), alg)

    def test_alg_agrees_with_schema_and_runtime_sets(self):
        # One source of truth: every alg this helper accepts must also be a member
        # of the set the schema and the signing path check.
        for alg in SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS:
            key_pem = _ec_pem(_EC_SIGNING_ALG_CURVES[alg]()) if alg in _EC_SIGNING_ALG_CURVES else _rsa_pem()
            validate_private_key_material(key_pem, alg)

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            validate_private_key_material("   ", "RS256")

    def test_error_message_excludes_supplied_value(self):
        # A malformed PEM is attacker-influenced and reaches logs (CWE-117), so
        # the message must not echo it back.
        secret_marker = "SENTINEL-DO-NOT-LOG-abc123"
        with pytest.raises(ValueError) as exc:
            validate_private_key_material(secret_marker, "RS256")
        assert secret_marker not in str(exc.value)

    def test_error_message_excludes_key_material(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = _pem(key)
        with pytest.raises(ValueError) as exc:
            validate_private_key_material(pem, "ES256")
        assert PEM_HEADER not in str(exc.value)
        assert pem not in str(exc.value)


class TestGatewayServicePrivateKeyJwtGate:
    """The service-layer gate: which values get parsed at all."""

    def test_valid_key_accepted(self):
        GatewayService._validate_private_key_jwt_config(_oauth_config())

    def test_malformed_key_rejected(self):
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=MALFORMED_KEY))

    def test_other_auth_methods_skipped(self):
        # A non-private_key_jwt gateway may carry unrelated material; never parse it.
        for method in ("none", "client_secret_basic", "client_secret_post"):
            GatewayService._validate_private_key_jwt_config({"token_endpoint_auth_method": method, "private_key": MALFORMED_KEY})

    def test_absent_method_skipped(self):
        GatewayService._validate_private_key_jwt_config({"client_id": "c1", "private_key": MALFORMED_KEY})

    def test_method_surrounding_whitespace_still_validated(self):
        # OAuthManager strips this field before comparing, so the gate must too:
        # a value the runtime would sign with private_key_jwt must not skip here.
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(token_endpoint_auth_method="  private_key_jwt  ", private_key=MALFORMED_KEY))

    def test_no_skip_gap_against_runtime_method_matching(self):
        # Exhaustive check of the one property that matters for this gate: there is
        # no spelling of token_endpoint_auth_method that the signing path treats as
        # private_key_jwt while this gate skips validation.
        #
        # The predicate below mirrors OAuthManager's normalization at
        # oauth_manager.py:640-641 (strip(), deliberately no lower()). It is a
        # restatement, not a read, so changing that normalization requires
        # changing this line in the same commit; otherwise this test keeps passing
        # while the skip-gap reopens. It still catches the likelier regression,
        # which is someone editing the gate in gateway_service.py.
        for method in ("private_key_jwt", "  private_key_jwt  ", "PRIVATE_KEY_JWT", "Private_Key_Jwt", "client_secret_post", "none", ""):
            runtime_signs_with_pkjwt = method.strip() == "private_key_jwt"
            if not runtime_signs_with_pkjwt:
                continue
            with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
                GatewayService._validate_private_key_jwt_config(_oauth_config(token_endpoint_auth_method=method, private_key=MALFORMED_KEY))

    def test_empty_config_skipped(self):
        GatewayService._validate_private_key_jwt_config(None)
        GatewayService._validate_private_key_jwt_config({})

    def test_missing_key_rejected(self):
        with pytest.raises(ValueError, match="private_key is required"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=""))

    def test_masked_placeholder_resolves_against_the_stored_key(self):
        # An update that keeps the stored key resubmits the mask. The gate now
        # resolves it against the stored ciphertext and validates the key the
        # gateway will actually sign with, rather than returning early.
        stored = {"private_key": get_encryption_service(settings.auth_encryption_secret).encrypt_secret(_rsa_pem())}
        GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=settings.masked_auth_value), existing_oauth_config=stored)

    def test_masked_placeholder_without_a_stored_key_rejected(self):
        # On create there is nothing to preserve, and
        # protect_oauth_config_for_storage turns the placeholder into None, so the
        # gateway would persist with no key and fail at its first token fetch.
        with pytest.raises(ValueError, match="no stored key exists to preserve"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=settings.masked_auth_value))

    def test_ciphertext_is_decrypted_and_validated(self):
        # Stored ciphertext is resolved, not skipped. A validator keyed on the
        # fictional "enc:v1:" prefix would have missed the real "v2:" marker and
        # parsed ciphertext as PEM, rejecting every stored key; one that returns
        # early instead lets malformed material ride through inside the envelope.
        ciphertext = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(_rsa_pem())
        assert not ciphertext.startswith("enc:v1:")
        GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=ciphertext))

    def test_ciphertext_wrapping_malformed_material_rejected(self):
        ciphertext = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(MALFORMED_KEY)
        with pytest.raises(ValueError, match="not a valid PEM-encoded private key"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=ciphertext))

    def test_ciphertext_mismatched_with_requested_alg_rejected(self):
        # The reviewer's acceptance step 4: repeat the masked-update check with
        # the stored ciphertext instead of the mask.
        ciphertext = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(_rsa_pem())
        with pytest.raises(ValueError, match="must be an EC private key"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=ciphertext, token_endpoint_auth_signing_alg="ES256"))

    def test_key_rotation_validates_new_material(self):
        # Rotating to a fresh valid key passes; rotating to junk is rejected.
        GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=_rsa_pem()))
        with pytest.raises(ValueError):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=MALFORMED_KEY))

    def test_alg_mismatch_rejected_through_service(self):
        with pytest.raises(ValueError, match="must be an EC private key"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(token_endpoint_auth_signing_alg="ES256"))

    def test_ec_key_with_matching_alg_accepted_through_service(self):
        GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=_ec_pem(ec.SECP256R1()), token_endpoint_auth_signing_alg="ES256"))


class TestUpdatePathRejectsMalformedKey:
    """``update_gateway`` must reject malformed key material, never absorb it.

    ``update_gateway`` carries an ``except (GatewayConnectionError, GatewayCredentialError)``
    branch that, when no connection-affecting field changed, downgrades a failure to a
    warning and persists the update. Validation therefore runs before the reinitialization
    block, and these tests pin that ordering: a malformed key must abort the update.
    """

    @staticmethod
    def _existing_gateway():
        """Build a persisted gateway stub with a working oauth_config.

        Returns:
            MagicMock: Gateway row stub.
        """
        gateway = MagicMock()
        gateway.id = "gw-pkjwt"
        gateway.name = "Existing Gateway"
        gateway.url = "https://existing.example.com"
        gateway.enabled = True
        gateway.gateway_mode = "cache"
        gateway.transport = "SSE"
        gateway.auth_type = "oauth"
        gateway.auth_value = None
        gateway.auth_query_params = None
        gateway.oauth_config = {
            "grant_type": "client_credentials",
            "client_id": "client-1",
            "token_url": "https://issuer.example.com/token",
        }
        gateway.ca_certificate = None
        gateway.ca_certificate_sig = None
        gateway.signing_algorithm = None
        gateway.client_cert = None
        gateway.client_key = None
        gateway.tools = []
        gateway.resources = []
        gateway.prompts = []
        gateway.email_team = None
        gateway.version = 1
        # GatewayRead validates these on the success path; MagicMock defaults fail it.
        gateway.team = None
        gateway.team_id = None
        gateway.created_by = "admin@example.com"
        gateway.modified_by = "admin@example.com"
        return gateway

    @staticmethod
    def _patch_caches(monkeypatch, gateway):
        """Stub the lookups and caches ``update_gateway`` touches.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            gateway: Gateway row stub returned by ``get_for_update``.
        """
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: MagicMock(invalidate_gateways=AsyncMock()))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))

    @pytest.mark.asyncio
    async def test_malformed_key_on_update_is_rejected_not_swallowed(self, monkeypatch):
        service = GatewayService()
        gateway = self._existing_gateway()
        self._patch_caches(monkeypatch, gateway)

        db = MagicMock()
        db.rollback = MagicMock()
        service._initialize_gateway = AsyncMock(return_value=({}, [], [], [], []))
        service._notify_gateway_updated = AsyncMock()

        update = GatewayUpdate(
            oauth_config={
                "grant_type": "client_credentials",
                "client_id": "client-1",
                "token_url": "https://issuer.example.com/token",
                "token_endpoint_auth_method": "private_key_jwt",
                "private_key": MALFORMED_KEY,
            }
        )

        # GatewayError, not a silent success: update_gateway's outer handler wraps
        # ValueError the same way it already wraps _validate_token_exchange_config's
        # rejections, so this matches the sibling validator rather than diverging.
        #
        # The message is deliberately not asserted. #7079 routes catch-all
        # handlers through unexpected_error_detail(), which keeps project
        # exception messages and replaces everything else with a correlation
        # reference. A bare ValueError from the shared validator is therefore
        # sanitized by design, so asserting on its text would pin behaviour that
        # change intentionally removed. What matters here is that the update is
        # refused and nothing is committed.
        with pytest.raises(GatewayError):
            await service.update_gateway(db, "gw-pkjwt", update)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_key_on_update_is_accepted(self, monkeypatch):
        service = GatewayService()
        gateway = self._existing_gateway()
        self._patch_caches(monkeypatch, gateway)

        db = MagicMock()
        db.rollback = MagicMock()
        service._initialize_gateway = AsyncMock(return_value=({}, [], [], [], []))
        service._notify_gateway_updated = AsyncMock()

        update = GatewayUpdate(
            oauth_config={
                "grant_type": "client_credentials",
                "client_id": "client-1",
                "token_url": "https://issuer.example.com/token",
                "token_endpoint_auth_method": "private_key_jwt",
                "private_key": _rsa_pem(),
            }
        )

        await service.update_gateway(db, "gw-pkjwt", update)
        db.rollback.assert_not_called()


class TestPrivateKeyLifecycle:
    """The signing key from submission through storage, rotation and use.

    ``private_key`` is listed in ``OAUTH_SENSITIVE_KEYS``, but no test covered it
    through ``protect_oauth_config_for_storage``. These tests pin the properties a
    reviewer needs to trust: the raw PEM never persists, an update that keeps the
    key does not rotate it, and a key that survives the storage round trip can
    still sign.
    """

    @staticmethod
    def _service():
        """Return the encryption service bound to the configured secret.

        Returns:
            EncryptionService: Service used for the storage round trip.
        """
        return get_encryption_service(settings.auth_encryption_secret)

    @pytest.mark.asyncio
    async def test_raw_pem_never_persists(self):
        original = _rsa_pem()
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": original})

        assert self._service().is_encrypted(stored["private_key"])
        assert PEM_HEADER not in stored["private_key"]
        assert original not in stored["private_key"]

    @pytest.mark.asyncio
    async def test_storage_round_trip_is_lossless(self):
        # A key that changes under encryption would fail at sign time rather than
        # at configuration time, so the round trip must be exact.
        original = _rsa_pem()
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": original})

        assert self._service().decrypt_secret(stored["private_key"]) == original

    @pytest.mark.asyncio
    async def test_masked_update_preserves_the_stored_key(self):
        # Editing an unrelated field resubmits the mask. Treating that as new key
        # material would silently rotate the key and break the gateway.
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": _rsa_pem()})
        updated = await protect_oauth_config_for_storage(
            {"token_endpoint_auth_method": "private_key_jwt", "private_key": settings.masked_auth_value},
            existing_oauth_config=stored,
        )

        assert updated["private_key"] == stored["private_key"]

    @pytest.mark.asyncio
    async def test_resubmitted_ciphertext_is_not_double_encrypted(self):
        # A client that reads the config back and submits it unchanged must not
        # cause a second encryption pass, which would make the key undecryptable.
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": _rsa_pem()})
        updated = await protect_oauth_config_for_storage(
            {"token_endpoint_auth_method": "private_key_jwt", "private_key": stored["private_key"]},
            existing_oauth_config=stored,
        )

        assert updated["private_key"] == stored["private_key"]
        assert self._service().decrypt_secret(updated["private_key"]) == self._service().decrypt_secret(stored["private_key"])

    @pytest.mark.asyncio
    async def test_rotation_replaces_the_stored_key(self):
        old_pem = _rsa_pem()
        new_pem = _rsa_pem()
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": old_pem})
        rotated = await protect_oauth_config_for_storage(
            {"token_endpoint_auth_method": "private_key_jwt", "private_key": new_pem},
            existing_oauth_config=stored,
        )

        assert rotated["private_key"] != stored["private_key"]
        assert self._service().decrypt_secret(rotated["private_key"]) == new_pem

    @pytest.mark.asyncio
    async def test_key_still_signs_after_the_storage_round_trip(self):
        # The end-to-end property the feature rests on: a key that was validated,
        # encrypted, stored and decrypted can still produce a verifiable
        # assertion. Each step above is checked in isolation; this is the
        # composition.
        # Third-Party
        import jwt as pyjwt

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        original = _pem(key)
        public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

        GatewayService._validate_private_key_jwt_config({"token_endpoint_auth_method": "private_key_jwt", "private_key": original})
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": original})
        recovered = self._service().decrypt_secret(stored["private_key"])

        assertion = pyjwt.encode({"iss": "c1", "sub": "c1", "aud": "https://issuer.example.com/token"}, recovered, algorithm="RS256")
        claims = pyjwt.decode(assertion, public_pem, algorithms=["RS256"], audience="https://issuer.example.com/token")
        assert claims["iss"] == "c1"

    @pytest.mark.asyncio
    async def test_gate_accepts_the_stored_form_on_a_later_update(self):
        # The gate and the storage layer must agree: whatever storage produces has
        # to be a value the gate skips, or an unrelated field edit would be
        # rejected on every subsequent update.
        stored = await protect_oauth_config_for_storage({"token_endpoint_auth_method": "private_key_jwt", "private_key": _rsa_pem()})

        GatewayService._validate_private_key_jwt_config({"token_endpoint_auth_method": "private_key_jwt", "private_key": stored["private_key"]})


class TestRsaKeySizeFloor:
    """RFC 7518 Sections 3.3 and 3.5 require RSA keys of at least 2048 bits.

    PyJWT emits a warning for a smaller key and signs a verifiable assertion
    anyway, so the floor has to be enforced rather than inferred from the warning
    or from a provider rejecting the result.
    """

    @staticmethod
    def _rsa_pem_of_size(bits: int) -> str:
        """Return an unencrypted RSA private key PEM of *bits* length.

        Args:
            bits: Modulus size.

        Returns:
            str: PEM-encoded RSA private key.
        """
        return _pem(rsa.generate_private_key(public_exponent=65537, key_size=bits))

    @pytest.mark.parametrize("alg", sorted(_RSA_SIGNING_ALGS))
    def test_undersized_key_rejected_for_every_rsa_alg(self, alg):
        with pytest.raises(ValueError, match="requires at least 2048 bits"):
            validate_private_key_material(self._rsa_pem_of_size(1024), alg)

    @pytest.mark.parametrize("alg", sorted(_RSA_SIGNING_ALGS))
    def test_minimum_size_accepted_for_every_rsa_alg(self, alg):
        validate_private_key_material(self._rsa_pem_of_size(2048), alg)

    def test_error_names_the_actual_size_without_leaking_key_material(self):
        pem = self._rsa_pem_of_size(1024)
        with pytest.raises(ValueError) as exc:
            validate_private_key_material(pem, "RS256")
        message = str(exc.value)
        assert "1024-bit" in message
        assert PEM_HEADER not in message
        assert pem not in message

    def test_undersized_key_rejected_through_the_service_gate(self):
        with pytest.raises(ValueError, match="requires at least 2048 bits"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=self._rsa_pem_of_size(1024)))

    def test_undersized_key_rejected_when_wrapped_in_ciphertext(self):
        ciphertext = get_encryption_service(settings.auth_encryption_secret).encrypt_secret(self._rsa_pem_of_size(1024))
        with pytest.raises(ValueError, match="requires at least 2048 bits"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=ciphertext))

    def test_undersized_stored_key_rejected_through_a_masked_update(self):
        # The path a pre-existing gateway takes: the operator edits an unrelated
        # field, the mask resolves to the stored undersized key, and the update
        # must be refused rather than silently preserved.
        stored = {"private_key": get_encryption_service(settings.auth_encryption_secret).encrypt_secret(self._rsa_pem_of_size(1024))}
        with pytest.raises(ValueError, match="requires at least 2048 bits"):
            GatewayService._validate_private_key_jwt_config(_oauth_config(private_key=settings.masked_auth_value), existing_oauth_config=stored)

    @pytest.mark.parametrize("alg", sorted(_RSA_SIGNING_ALGS))
    @pytest.mark.asyncio
    async def test_undersized_key_rejected_at_signing_time(self, alg):
        # The only check that reaches configurations persisted before upfront
        # validation existed, or imported outside the gateway API. Boundary
        # validation cannot see those rows; this is what the reviewer meant by
        # "including imported or existing configurations".
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        credentials = {
            "client_id": "client-1",
            "token_url": "https://issuer.example.com/token",
            "token_endpoint_auth_method": "private_key_jwt",
            "private_key": self._rsa_pem_of_size(1024),
            "token_endpoint_auth_signing_alg": alg,
        }
        with pytest.raises(OAuthError, match="Invalid private_key for private_key_jwt"):
            await OAuthManager()._build_client_assertion(credentials)

    @pytest.mark.asyncio
    async def test_signing_failure_surfaces_as_oautherror_not_valueerror(self):
        # The shared validators raise ValueError for the configuration boundary.
        # Nothing between _build_client_assertion and the flow handlers catches
        # it, so a leak would surface as a generic failure with validator text in
        # a user-facing message.
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        credentials = {
            "client_id": "client-1",
            "token_url": "https://issuer.example.com/token",
            "token_endpoint_auth_method": "private_key_jwt",
            "private_key": MALFORMED_KEY,
        }
        with pytest.raises(OAuthError):
            await OAuthManager()._build_client_assertion(credentials)
        # And specifically not the raw ValueError.
        try:
            await OAuthManager()._build_client_assertion(credentials)
        except ValueError as exc:  # OAuthError must not subclass ValueError here
            assert isinstance(exc, OAuthError), "ValueError leaked out of the signing path"
        except OAuthError:
            pass

    @pytest.mark.asyncio
    async def test_valid_key_still_signs_a_verifiable_assertion(self):
        # Third-Party
        import jwt as pyjwt

        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        credentials = {
            "client_id": "client-1",
            "token_url": "https://issuer.example.com/token",
            "token_endpoint_auth_method": "private_key_jwt",
            "private_key": _pem(key),
            "token_endpoint_auth_signing_alg": "RS256",
        }
        assertion = await OAuthManager()._build_client_assertion(credentials)
        claims = pyjwt.decode(assertion, public_pem, algorithms=["RS256"], audience="https://issuer.example.com/token")
        assert claims["iss"] == "client-1"
        assert claims["sub"] == "client-1"


class TestEcCurveExhaustiveness:
    """Why no explicit EC strength floor exists.

    ``_EC_SIGNING_ALG_CURVES`` pins each ES algorithm to exactly one curve, so an
    undersized curve already fails the curve check for every supported algorithm
    and a ``key_size`` comparison would be unreachable. These tests turn that
    reasoning into an enforced invariant.
    """

    @pytest.mark.parametrize("alg", sorted(_EC_SIGNING_ALG_CURVES))
    def test_secp192r1_rejected_for_every_es_alg(self, alg):
        undersized = _pem(ec.generate_private_key(ec.SECP192R1()))
        with pytest.raises(ValueError, match="curve does not match"):
            validate_private_key_material(undersized, alg)

    @pytest.mark.parametrize("alg,curve", sorted((a, c) for a, c in _EC_SIGNING_ALG_CURVES.items()))
    def test_each_es_alg_accepts_only_its_own_curve(self, alg, curve):
        validate_private_key_material(_pem(ec.generate_private_key(curve())), alg)
        for other_alg, other_curve in _EC_SIGNING_ALG_CURVES.items():
            if other_alg == alg:
                continue
            with pytest.raises(ValueError, match="curve does not match"):
                validate_private_key_material(_pem(ec.generate_private_key(other_curve())), alg)


class TestWritePathsReachTheValidator:
    """Every path that persists an ``oauth_config`` must validate it.

    Validation that covers one entry point is finding 1 again at a different
    door, so these tests pin the audit rather than leaving it in a review
    comment.
    """

    def test_gateway_create_and_update_both_call_the_gate(self):
        # Standard
        import inspect

        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        prepare = inspect.getsource(GatewayService.prepare_oauth_config_for_storage)
        assert "_validate_private_key_jwt_config" in prepare, "the create path stopped validating"

        update = inspect.getsource(GatewayService.update_gateway)
        assert "_validate_private_key_jwt_config" in update, "the update path stopped validating"
        assert "existing_oauth_config=original_oauth_config" in update, "the update path stopped resolving placeholders against the stored config"

    def test_catalog_registration_routes_through_the_validating_helper(self):
        # catalog_service builds a gateway of its own. It must reach the
        # GatewayService method, which validates, and not the bare encryption
        # helper, which does not.
        # Standard
        import inspect

        # First-Party
        from mcpgateway.services import catalog_service

        source = inspect.getsource(catalog_service)
        assert "self._gateway_service.prepare_oauth_config_for_storage(" in source

    def test_catalog_credential_allowlist_cannot_carry_key_material(self):
        # The one catalog branch that calls the bare encryption helper is the
        # discovery-timeout fallback. It is safe only because
        # _build_oauth_config_from_credentials copies a fixed field list that
        # excludes private_key and token_endpoint_auth_method. That exclusion is
        # incidental, so pin it: adding either field to the allowlist would route
        # key material around the validator.
        # First-Party
        from mcpgateway.services.catalog_service import CatalogService

        built = CatalogService._build_oauth_config_from_credentials(
            {
                "issuer": "https://issuer.example.com",
                "client_id": "client-1",
                "token_url": "https://issuer.example.com/token",
                "private_key": _rsa_pem(),
                "token_endpoint_auth_method": "private_key_jwt",
                "token_endpoint_auth_signing_alg": "RS256",
            }
        )

        assert "private_key" not in built, "catalog credentials can now carry key material; it must reach _validate_private_key_jwt_config"
        assert "token_endpoint_auth_method" not in built, "catalog credentials can now select an auth method; private_key_jwt would bypass validation"
        assert built["grant_type"] == "authorization_code"
