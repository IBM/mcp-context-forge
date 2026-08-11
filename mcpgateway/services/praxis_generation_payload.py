"""Authenticated archive and control-plane source state for one generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
from typing import Final

from pydantic import ValidationError

from mcpgateway.db import PraxisBundleGeneration
from mcpgateway.services._praxis_config_core import PraxisConfigContractError
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleAad, PraxisBundleCryptoError, PraxisBundleCryptoService, parse_envelope
from mcpgateway.services.praxis_config_archive import validate_canonical_archive
from mcpgateway.services._praxis_config_core import PraxisStrictModel
from mcpgateway.services.praxis_config_models import PraxisBundleArtifact, PraxisConfigSourceSnapshot, PraxisServerSource

SOURCE_SCHEMA: Final = "praxis-source/v1"


class PraxisGenerationPayloadError(Exception):
    """Authenticated generation storage is corrupt or inconsistent."""


@dataclass(frozen=True, slots=True)
class PraxisGenerationBuild:
    """Inputs required to construct one encrypted generation row."""

    target_id: str
    source_epoch: int
    policy_epoch: int
    fence: int
    created_at: datetime
    snapshot: PraxisConfigSourceSnapshot
    artifact: PraxisBundleArtifact


@dataclass(frozen=True, slots=True)
class PraxisDecryptedGeneration:
    """Fully authenticated archive and control-plane-only source snapshot."""

    archive: bytes
    snapshot: PraxisConfigSourceSnapshot


class _StoredSource(PraxisStrictModel):
    target_id: str
    servers: tuple[PraxisServerSource, ...]


def encode_source_snapshot(snapshot: PraxisConfigSourceSnapshot) -> bytes:
    """Encode the exact canonical source state hashed by source collection."""
    return json.dumps(
        {"target_id": snapshot.target_id, "servers": [server.model_dump(mode="json") for server in snapshot.servers]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def build_generation(build: PraxisGenerationBuild, crypto: PraxisBundleCryptoService) -> PraxisBundleGeneration:
    """Encrypt the canonical archive and source state in independent envelopes."""
    artifact = build.artifact
    encrypted = crypto.encrypt(
        artifact.archive_bytes,
        PraxisBundleAad(build.target_id, artifact.generation_id, artifact.manifest.bundle_schema, artifact.content_hash),
    )
    source_encrypted = crypto.encrypt(
        encode_source_snapshot(build.snapshot),
        PraxisBundleAad(build.target_id, artifact.generation_id, SOURCE_SCHEMA, build.snapshot.source_fingerprint),
    )
    parsed = parse_envelope(encrypted.envelope)
    source_parsed = parse_envelope(source_encrypted.envelope)
    if parsed.key_id == source_parsed.key_id and hmac.compare_digest(parsed.nonce, source_parsed.nonce):
        raise PraxisGenerationPayloadError
    compatibility = artifact.manifest
    return PraxisBundleGeneration(
        target_id=build.target_id,
        generation_id=artifact.generation_id,
        source_fingerprint=compatibility.source_fingerprint,
        source_epoch=build.source_epoch,
        policy_epoch=build.policy_epoch,
        fence=build.fence,
        payload_hash=artifact.payload_hash,
        content_hash=artifact.content_hash,
        ciphertext_hash=encrypted.ciphertext_hash,
        ciphertext=encrypted.envelope,
        envelope_version=encrypted.envelope_version,
        key_id=encrypted.key_id,
        nonce=parsed.nonce,
        source_ciphertext_hash=source_encrypted.ciphertext_hash,
        source_ciphertext=source_encrypted.envelope,
        source_envelope_version=source_encrypted.envelope_version,
        source_key_id=source_encrypted.key_id,
        source_nonce=source_parsed.nonce,
        source_schema=SOURCE_SCHEMA,
        bundle_schema=compatibility.bundle_schema,
        renderer_version=compatibility.renderer_version,
        praxis_revision=compatibility.praxis_revision,
        cpex_contract_version=compatibility.cpex_contract_version,
        mcp_protocol_version=compatibility.mcp_protocol_version,
        minimum_launcher_version=compatibility.minimum_launcher_version,
        created_at=build.created_at,
    )


def decrypt_generation(generation: PraxisBundleGeneration, crypto: PraxisBundleCryptoService) -> PraxisDecryptedGeneration:
    """Authenticate storage, archive, canonical hash, and typed source state."""
    if not hmac.compare_digest(hashlib.sha256(generation.ciphertext).hexdigest(), generation.ciphertext_hash) or not hmac.compare_digest(
        hashlib.sha256(generation.source_ciphertext).hexdigest(), generation.source_ciphertext_hash
    ):
        raise PraxisGenerationPayloadError
    try:
        archive = crypto.decrypt(generation.ciphertext, PraxisBundleAad(generation.target_id, generation.generation_id, generation.bundle_schema, generation.content_hash))
        source_bytes = crypto.decrypt(
            generation.source_ciphertext,
            PraxisBundleAad(generation.target_id, generation.generation_id, generation.source_schema, generation.source_fingerprint),
        )
        validate_canonical_archive(archive)
        stored_source = _StoredSource.model_validate_json(source_bytes, strict=True)
        snapshot = PraxisConfigSourceSnapshot(target_id=stored_source.target_id, source_fingerprint=generation.source_fingerprint, servers=stored_source.servers)
    except (PraxisBundleCryptoError, PraxisConfigContractError, ValidationError):
        raise PraxisGenerationPayloadError from None
    if snapshot.target_id != generation.target_id or not hmac.compare_digest(snapshot.source_fingerprint, generation.source_fingerprint):
        raise PraxisGenerationPayloadError
    return PraxisDecryptedGeneration(archive, snapshot)


__all__ = ("SOURCE_SCHEMA", "PraxisDecryptedGeneration", "PraxisGenerationBuild", "PraxisGenerationPayloadError", "build_generation", "decrypt_generation", "encode_source_snapshot")
