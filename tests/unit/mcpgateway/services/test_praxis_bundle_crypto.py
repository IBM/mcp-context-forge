"""Tests for strict Praxis bundle encryption envelopes."""

from __future__ import annotations

import base64
import hashlib
import json
import traceback

import pytest

from mcpgateway.config import SecurityConfigurationError, Settings
from mcpgateway.services.praxis_bundle_crypto import (
    ENVELOPE_VERSION,
    NONCE_BYTES,
    EncryptedPraxisBundle,
    PraxisBundleAad,
    PraxisBundleCryptoError,
    PraxisBundleCryptoService,
    build_aad,
    encode_envelope,
    parse_envelope,
)

ACTIVE_KEY = bytes(range(32))
OLD_KEY = bytes(range(32, 64))
ACTIVE_KEY_B64 = base64.b64encode(ACTIVE_KEY).decode("ascii")
OLD_KEY_B64 = base64.b64encode(OLD_KEY).decode("ascii")
KEYS_JSON = json.dumps({"active-2026": ACTIVE_KEY_B64, "old-2025": OLD_KEY_B64})
PLAINTEXT_SENTINEL = b"PRAXIS-PLAINTEXT-SENTINEL credential=never-store"
TEST_JWT_SECRET = "q9$L2v!N7x@R4m#T8k%P1s&W6z*D3f_H"  # pragma: allowlist secret
TEST_AUTH_SECRET = "A7!auth-encryption_R4ndom#Value$2026"  # pragma: allowlist secret


class MemoryNonceStore:
    """Atomic in-memory nonce reservation fake."""

    def __init__(self, reject_all: bool = False) -> None:
        self._reserved: set[tuple[str, bytes]] = set()
        self._reject_all = reject_all

    def reserve(self, key_id: str, nonce: bytes) -> bool:
        pair = (key_id, nonce)
        if self._reject_all or pair in self._reserved:
            return False
        self._reserved.add(pair)
        return True


def _aad(target_id: str = "target-alpha", content_hash: str | None = None) -> PraxisBundleAad:
    return PraxisBundleAad(
        target_id=target_id,
        generation_id="11" * 32,
        bundle_schema_version="praxis-bundle/v1",
        content_hash=content_hash or hashlib.sha256(PLAINTEXT_SENTINEL).hexdigest(),
    )


def _service(*, keys_json: str = KEYS_JSON, active_key_id: str = "active-2026", reject_nonces: bool = False) -> PraxisBundleCryptoService:
    return PraxisBundleCryptoService.from_json_keys(keys_json, active_key_id, MemoryNonceStore(reject_all=reject_nonces))


def test_build_aad_has_exact_four_byte_utf8_frames() -> None:
    aad = PraxisBundleAad(target_id="t", generation_id="g", bundle_schema_version="b", content_hash="h")

    framed = build_aad(ENVELOPE_VERSION, "k", aad)

    assert framed.hex() == "0000000131000000016b0000000174000000016700000001620000000168"


def test_envelope_encoding_and_parsing_match_canonical_vector() -> None:
    nonce = bytes(range(NONCE_BYTES))
    ciphertext_and_tag = bytes.fromhex("aa" * 16)
    expected = bytes.fromhex("0100016b000102030405060708090a0b" + "aa" * 16)

    envelope = encode_envelope("k", nonce, ciphertext_and_tag)
    parsed = parse_envelope(envelope)

    assert envelope == expected
    assert (parsed.version, parsed.key_id, parsed.nonce, parsed.ciphertext_and_tag) == (1, "k", nonce, ciphertext_and_tag)


def test_encrypt_uses_random_nonce_and_hashes_exact_stored_bytes() -> None:
    service = _service()

    first = service.encrypt(PLAINTEXT_SENTINEL, _aad())
    second = service.encrypt(PLAINTEXT_SENTINEL, _aad())

    assert isinstance(first, EncryptedPraxisBundle)
    assert first.envelope != second.envelope
    assert parse_envelope(first.envelope).nonce != parse_envelope(second.envelope).nonce
    assert len(parse_envelope(first.envelope).nonce) == NONCE_BYTES
    assert first.ciphertext_hash == hashlib.sha256(first.envelope).hexdigest()
    assert PLAINTEXT_SENTINEL not in first.envelope
    assert first.generation_id == second.generation_id == _aad().generation_id
    assert first.content_hash == second.content_hash == _aad().content_hash
    assert service.decrypt(first.envelope, _aad()) == PLAINTEXT_SENTINEL


def test_rotation_decrypts_active_and_retained_old_keys() -> None:
    old_service = _service(active_key_id="old-2025")
    old_bundle = old_service.encrypt(PLAINTEXT_SENTINEL, _aad())
    rotated_service = _service(active_key_id="active-2026")
    new_bundle = rotated_service.encrypt(PLAINTEXT_SENTINEL, _aad())

    assert parse_envelope(old_bundle.envelope).key_id == "old-2025"
    assert rotated_service.decrypt(old_bundle.envelope, _aad()) == PLAINTEXT_SENTINEL
    assert rotated_service.decrypt(new_bundle.envelope, _aad()) == PLAINTEXT_SENTINEL


def test_direct_constructor_valid_decoded_keys_encrypt_decrypt_and_rotate() -> None:
    old_service = PraxisBundleCryptoService({"active-2026": ACTIVE_KEY, "old-2025": OLD_KEY}, "old-2025", MemoryNonceStore())
    old_bundle = old_service.encrypt(PLAINTEXT_SENTINEL, _aad())
    rotated_service = PraxisBundleCryptoService({"active-2026": ACTIVE_KEY, "old-2025": OLD_KEY}, "active-2026", MemoryNonceStore())

    assert rotated_service.decrypt(old_bundle.envelope, _aad()) == PLAINTEXT_SENTINEL
    assert rotated_service.decrypt(rotated_service.encrypt(PLAINTEXT_SENTINEL, _aad()).envelope, _aad()) == PLAINTEXT_SENTINEL


@pytest.mark.parametrize(
    "malformed_keys,active_key_id,material_sentinel",
    [
        ({"active": ACTIVE_KEY, "malformed key id": OLD_KEY}, "active", "malformed key id"),
        ({"active": ACTIVE_KEY, ("NONSTRING-ID-SENTINEL",): OLD_KEY}, "active", "NONSTRING-ID-SENTINEL"),
        ({"malformed active": ACTIVE_KEY}, "malformed active", "malformed active"),
        ({"active": "K" * 32}, "active", "K" * 32),
        ({"active": bytearray(ACTIVE_KEY)}, "active", bytearray(ACTIVE_KEY).hex()),
        ({"active": memoryview(ACTIVE_KEY)}, "active", ACTIVE_KEY.hex()),
        ({"active": ACTIVE_KEY, "old": bytearray(OLD_KEY)}, "active", OLD_KEY.hex()),
        ({"active": b""}, "active", "empty-key-material"),
        ({"active": bytes(31)}, "active", "31-byte-key-material"),
        ({"active": bytes(33)}, "active", "33-byte-key-material"),
        ({"active": ACTIVE_KEY, "old": bytes(31)}, "active", "retained-31-byte-key-material"),
    ],
)
def test_direct_constructor_rejects_every_malformed_entry_without_disclosure(
    malformed_keys,
    active_key_id,
    material_sentinel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(PraxisBundleCryptoError) as captured:
        PraxisBundleCryptoService(malformed_keys, active_key_id, MemoryNonceStore())

    error = captured.value
    exposed = " ".join(
        (
            str(error),
            repr(error),
            repr(error.args),
            repr(vars(error)),
            repr(error.__cause__),
            repr(error.__context__),
            "".join(traceback.format_exception(error)),
            caplog.text,
        )
    )
    assert error.code == "invalid_key_ring"
    assert str(error) == "invalid_key_ring: bundle encryption key configuration is invalid"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert material_sentinel not in exposed


def test_nonce_collision_is_fatal() -> None:
    service = _service(reject_nonces=True)

    with pytest.raises(PraxisBundleCryptoError, match="nonce reservation failed"):
        service.encrypt(PLAINTEXT_SENTINEL, _aad())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda envelope: envelope[:-1],
        lambda envelope: envelope[:3] + b" bad" + envelope[7:],
        lambda envelope: bytes((2,)) + envelope[1:],
        lambda envelope: envelope[:3] + b"\xff" + envelope[4:],
        lambda envelope: b"plaintext input",
    ],
)
def test_malformed_truncated_noncanonical_and_plaintext_envelopes_fail_closed(mutation) -> None:
    bundle = _service().encrypt(PLAINTEXT_SENTINEL, _aad())

    with pytest.raises(PraxisBundleCryptoError):
        _service().decrypt(mutation(bundle.envelope), _aad())


def test_tampering_and_wrong_aad_fail_authentication() -> None:
    service = _service()
    bundle = service.encrypt(PLAINTEXT_SENTINEL, _aad())
    tampered = bundle.envelope[:-1] + bytes((bundle.envelope[-1] ^ 1,))

    with pytest.raises(PraxisBundleCryptoError, match="authentication failed"):
        service.decrypt(tampered, _aad())
    with pytest.raises(PraxisBundleCryptoError, match="authentication failed"):
        service.decrypt(bundle.envelope, _aad(target_id="target-beta"))


def test_unknown_key_and_malformed_key_material_are_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    bundle = _service(active_key_id="old-2025").encrypt(PLAINTEXT_SENTINEL, _aad())
    malformed_key = "KEY-MATERIAL-SENTINEL"

    with pytest.raises(PraxisBundleCryptoError) as unknown_error:
        _service(keys_json=json.dumps({"active-2026": ACTIVE_KEY_B64})).decrypt(bundle.envelope, _aad())
    with pytest.raises(PraxisBundleCryptoError) as malformed_error:
        _service(keys_json=json.dumps({"active-2026": malformed_key}))

    exposed = f"{unknown_error.value!r} {malformed_error.value!r} {caplog.text}"
    assert malformed_key not in exposed
    assert ACTIVE_KEY_B64 not in exposed
    assert PLAINTEXT_SENTINEL.decode() not in exposed


def test_settings_allow_missing_keys_only_for_off_or_shadow_only() -> None:
    off = Settings(jwt_secret_key=TEST_JWT_SECRET, auth_encryption_secret=TEST_AUTH_SECRET, _env_file=None)
    shadow = Settings(
        jwt_secret_key=TEST_JWT_SECRET,
        auth_encryption_secret=TEST_AUTH_SECRET,
        praxis_config_shadow_enabled=True,
        _env_file=None,
    )

    assert off.praxis_bundle_encryption_keys.get_secret_value() == ""
    assert shadow.praxis_bundle_active_key_id == ""


@pytest.mark.parametrize("gate", ["praxis_artifact_delivery_enabled", "praxis_activation_enabled"])
def test_settings_require_valid_key_ring_before_delivery_or_activation(gate: str) -> None:
    values = {gate: True}

    with pytest.raises(SecurityConfigurationError, match="Praxis bundle encryption configuration is unavailable"):
        Settings(jwt_secret_key=TEST_JWT_SECRET, auth_encryption_secret=TEST_AUTH_SECRET, _env_file=None, **values)

    configured = Settings(
        jwt_secret_key=TEST_JWT_SECRET,
        auth_encryption_secret=TEST_AUTH_SECRET,
        praxis_bundle_encryption_keys=KEYS_JSON,
        praxis_bundle_active_key_id="active-2026",
        _env_file=None,
        **values,
    )
    assert getattr(configured, gate) is True


def test_settings_reject_malformed_keys_without_exposing_material() -> None:
    key_sentinel = "CONFIG-KEY-SENTINEL"

    with pytest.raises(SecurityConfigurationError) as error:
        Settings(
            jwt_secret_key=TEST_JWT_SECRET,
            auth_encryption_secret=TEST_AUTH_SECRET,
            praxis_artifact_delivery_enabled=True,
            praxis_bundle_encryption_keys=json.dumps({"active-2026": key_sentinel}),
            praxis_bundle_active_key_id="active-2026",
            _env_file=None,
        )

    assert key_sentinel not in str(error.value)


def test_traffic_gate_is_rejected_in_this_release() -> None:
    with pytest.raises(SecurityConfigurationError, match="Praxis traffic is not available"):
        Settings(jwt_secret_key=TEST_JWT_SECRET, auth_encryption_secret=TEST_AUTH_SECRET, praxis_traffic_enabled=True, _env_file=None)
