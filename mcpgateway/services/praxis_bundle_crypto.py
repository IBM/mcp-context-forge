# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/praxis_bundle_crypto.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Strict authenticated encryption for canonical Praxis bundle archives.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import os
import re
from typing import Final, Mapping, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ConfigDict, TypeAdapter, ValidationError

from mcpgateway.services.praxis_config_models import length_frame_utf8

ENVELOPE_VERSION: Final = 1
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32
GCM_TAG_BYTES: Final = 16
_KEY_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_KEY_MAP_ADAPTER: Final = TypeAdapter(dict[str, str], config=ConfigDict(strict=True, hide_input_in_errors=True))


class PraxisBundleCryptoError(ValueError):
    """Sanitized failure at the encrypted bundle boundary."""

    def __init__(self, code: str, detail: str) -> None:
        """Create an error containing only a stable code and sanitized detail."""
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class NonceReservationStore(Protocol):
    """Persistence boundary that atomically reserves a key/nonce pair."""

    def reserve(self, key_id: str, nonce: bytes) -> bool:
        """Return true only when the pair was newly reserved."""


@dataclass(frozen=True, slots=True)
class PraxisBundleAad:
    """Generation identity fields authenticated but not stored in ciphertext."""

    target_id: str
    generation_id: str
    bundle_schema_version: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ParsedPraxisEnvelope:
    """Strictly parsed canonical stored envelope."""

    version: int
    key_id: str
    nonce: bytes
    ciphertext_and_tag: bytes


@dataclass(frozen=True, slots=True)
class EncryptedPraxisBundle:
    """Ciphertext persistence value and external generation metadata."""

    envelope: bytes
    ciphertext_hash: str
    envelope_version: int
    key_id: str
    generation_id: str
    content_hash: str


def _valid_key_id(key_id: str) -> bool:
    """Return true only for an operator-safe key identifier."""
    return _KEY_ID_PATTERN.fullmatch(key_id) is not None


def build_aad(version: int, key_id: str, identity: PraxisBundleAad) -> bytes:
    """Build the exact six-field length-framed AES-GCM AAD."""
    if version != ENVELOPE_VERSION or not _valid_key_id(key_id):
        raise PraxisBundleCryptoError("invalid_aad", "bundle authentication metadata is invalid")
    return length_frame_utf8(
        (
            str(version),
            key_id,
            identity.target_id,
            identity.generation_id,
            identity.bundle_schema_version,
            identity.content_hash,
        )
    )


def encode_envelope(key_id: str, nonce: bytes, ciphertext_and_tag: bytes) -> bytes:
    """Encode one canonical v1 stored envelope."""
    if not _valid_key_id(key_id) or len(nonce) != NONCE_BYTES or len(ciphertext_and_tag) < GCM_TAG_BYTES:
        raise PraxisBundleCryptoError("invalid_envelope", "bundle envelope fields are invalid")
    key_id_bytes = key_id.encode("utf-8")
    return bytes((ENVELOPE_VERSION,)) + len(key_id_bytes).to_bytes(2, "big") + key_id_bytes + nonce + ciphertext_and_tag


def parse_envelope(envelope: bytes) -> ParsedPraxisEnvelope:
    """Parse an exact canonical v1 envelope or fail closed."""
    minimum_size = 1 + 2 + 1 + NONCE_BYTES + GCM_TAG_BYTES
    if len(envelope) < minimum_size or envelope[0] != ENVELOPE_VERSION:
        raise PraxisBundleCryptoError("invalid_envelope", "bundle envelope is malformed")
    key_id_size = int.from_bytes(envelope[1:3], "big")
    key_id_end = 3 + key_id_size
    ciphertext_start = key_id_end + NONCE_BYTES
    if key_id_size == 0 or ciphertext_start + GCM_TAG_BYTES > len(envelope):
        raise PraxisBundleCryptoError("invalid_envelope", "bundle envelope is malformed")
    try:
        key_id = envelope[3:key_id_end].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        key_id = ""
    if not _valid_key_id(key_id):
        raise PraxisBundleCryptoError("invalid_envelope", "bundle envelope is malformed") from None
    nonce = envelope[key_id_end:ciphertext_start]
    ciphertext_and_tag = envelope[ciphertext_start:]
    canonical = encode_envelope(key_id, nonce, ciphertext_and_tag)
    if not hmac.compare_digest(canonical, envelope):
        raise PraxisBundleCryptoError("invalid_envelope", "bundle envelope is noncanonical")
    return ParsedPraxisEnvelope(ENVELOPE_VERSION, key_id, nonce, ciphertext_and_tag)


def decode_key_ring_json(encoded_keys: str) -> dict[str, bytes]:
    """Decode a strict JSON base64 AES-256 key ring without exposing inputs."""
    parsed: dict[str, str] | None = None
    try:
        parsed = _KEY_MAP_ADAPTER.validate_json(encoded_keys)
    except ValidationError:
        parsed = None
    if not parsed:
        raise PraxisBundleCryptoError("invalid_key_ring", "bundle encryption key configuration is invalid") from None
    decoded: dict[str, bytes] = {}
    invalid = False
    for key_id, encoded_key in parsed.items():
        if not _valid_key_id(key_id):
            invalid = True
            continue
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            invalid = True
            continue
        if len(key) != KEY_BYTES:
            invalid = True
            continue
        decoded[key_id] = key
    if invalid or len(decoded) != len(parsed):
        raise PraxisBundleCryptoError("invalid_key_ring", "bundle encryption key configuration is invalid") from None
    return decoded


class PraxisBundleCryptoService:
    """Encrypt and decrypt canonical archives using a rotating AES-256-GCM key ring."""

    def __init__(self, keys: Mapping[str, bytes], active_key_id: str, nonce_store: NonceReservationStore) -> None:
        """Bind a validated decoded key ring to an atomic nonce reservation store."""
        valid_active_key = isinstance(active_key_id, str) and _valid_key_id(active_key_id) and active_key_id in keys
        valid_entries = all(isinstance(key_id, str) and _valid_key_id(key_id) and isinstance(key, bytes) and len(key) == KEY_BYTES for key_id, key in keys.items())
        if not keys or not valid_active_key or not valid_entries:
            raise PraxisBundleCryptoError("invalid_key_ring", "bundle encryption key configuration is invalid")
        self._keys = dict(keys)
        self._active_key_id = active_key_id
        self._nonce_store = nonce_store

    @classmethod
    def from_json_keys(cls, encoded_keys: str, active_key_id: str, nonce_store: NonceReservationStore) -> PraxisBundleCryptoService:
        """Construct the service from the operator JSON key-ring setting."""
        return cls(decode_key_ring_json(encoded_keys), active_key_id, nonce_store)

    def encrypt(self, archive: bytes, identity: PraxisBundleAad) -> EncryptedPraxisBundle:
        """Encrypt authenticated plaintext into one randomized v1 envelope."""
        if not hmac.compare_digest(hashlib.sha256(archive).hexdigest(), identity.content_hash):
            raise PraxisBundleCryptoError("content_hash_mismatch", "canonical archive identity is invalid")
        nonce = os.urandom(NONCE_BYTES)
        if not self._nonce_store.reserve(self._active_key_id, nonce):
            raise PraxisBundleCryptoError("nonce_collision", "nonce reservation failed")
        aad = build_aad(ENVELOPE_VERSION, self._active_key_id, identity)
        ciphertext_and_tag = AESGCM(self._keys[self._active_key_id]).encrypt(nonce, archive, aad)
        envelope = encode_envelope(self._active_key_id, nonce, ciphertext_and_tag)
        return EncryptedPraxisBundle(
            envelope=envelope,
            ciphertext_hash=hashlib.sha256(envelope).hexdigest(),
            envelope_version=ENVELOPE_VERSION,
            key_id=self._active_key_id,
            generation_id=identity.generation_id,
            content_hash=identity.content_hash,
        )

    def decrypt(self, envelope: bytes, identity: PraxisBundleAad) -> bytes:
        """Authenticate and decrypt an exact stored envelope with active or retained keys."""
        plaintext = self._decrypt_envelope(envelope, identity)
        if not hmac.compare_digest(hashlib.sha256(plaintext).hexdigest(), identity.content_hash):
            raise PraxisBundleCryptoError("content_hash_mismatch", "decrypted bundle identity is invalid")
        return plaintext

    def _decrypt_envelope(self, envelope: bytes, identity: PraxisBundleAad) -> bytes:
        """Authenticate an envelope before enforcing its plaintext identity."""
        parsed = parse_envelope(envelope)
        key = self._keys.get(parsed.key_id)
        if key is None:
            raise PraxisBundleCryptoError("unknown_key", "bundle encryption key is unavailable")
        aad = build_aad(parsed.version, parsed.key_id, identity)
        plaintext: bytes | None = None
        try:
            plaintext = AESGCM(key).decrypt(parsed.nonce, parsed.ciphertext_and_tag, aad)
        except InvalidTag:
            plaintext = None
        if plaintext is None:
            raise PraxisBundleCryptoError("authentication_failed", "bundle authentication failed") from None
        return plaintext
