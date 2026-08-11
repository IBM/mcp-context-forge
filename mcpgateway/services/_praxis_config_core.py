"""Strict public contracts for versioned Praxis configuration delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum, unique
import hashlib
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, Sequence

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator

MAX_ARCHIVE_BYTES: Final = 16 * 1024 * 1024
MAX_EXTRACTED_BYTES: Final = 64 * 1024 * 1024
MAX_REGULAR_FILES: Final = 64
MAX_PATH_BYTES: Final = 240
MANIFEST_PATH: Final = "render-manifest.json"
MANIFEST_SCHEMA_V1: Final = "praxis-render-manifest/v1"
GENERATION_ENVELOPE_SCHEMA_V1: Final = "praxis-generation-envelope/v1"

Sha256Hex = Annotated[str, StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
SafeIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
ContractVersion = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[!-~]+$")]


@unique
class PraxisContractErrorCode(StrEnum):
    """Stable categories for contract failures outside Pydantic parsing."""

    INVALID_ARCHIVE = "invalid_archive"
    INVALID_CANONICAL_VALUE = "invalid_canonical_value"
    INVALID_DOCUMENT = "invalid_document"
    LIMIT_EXCEEDED = "limit_exceeded"


@dataclass(frozen=True, slots=True)
class PraxisConfigContractError(ValueError):
    """Typed, sanitized failure raised by deterministic contract helpers."""

    code: PraxisContractErrorCode
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class PraxisStrictModel(BaseModel):
    """Immutable strict boundary model shared by every Praxis contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, strict=True)


def length_frame_utf8(fields: Sequence[str]) -> bytes:
    """Encode fields as four-byte big-endian UTF-8 byte lengths and bytes."""
    framed = bytearray()
    for field in fields:
        encoded = field.encode("utf-8")
        if len(encoded) > 0xFFFFFFFF:
            raise PraxisConfigContractError(PraxisContractErrorCode.LIMIT_EXCEEDED, "framed field exceeds uint32 length")
        framed.extend(len(encoded).to_bytes(4, "big"))
        framed.extend(encoded)
    return bytes(framed)


def utc_datetime_text(value: datetime) -> str:
    """Return one canonical RFC 3339 representation for a UTC datetime."""
    if value.utcoffset() != timedelta(0):
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "datetime must be UTC-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PraxisCompatibilityContract(PraxisStrictModel):
    """Complete compatibility tuple committed into every generation identity."""

    bundle_schema: ContractVersion
    renderer_version: ContractVersion
    praxis_revision: ContractVersion
    cpex_contract_version: ContractVersion
    mcp_protocol_version: ContractVersion
    minimum_launcher_version: ContractVersion


class PraxisSourceSnapshot(PraxisStrictModel):
    """Stable identity of one target's transactionally assembled source state."""

    target_id: SafeIdentifier
    source_fingerprint: Sha256Hex


class _PraxisDocumentPath(PraxisStrictModel):
    """Shared validation for canonical relative POSIX document paths."""

    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        encoded = value.encode("utf-8")
        canonical = PurePosixPath(value)
        invalid = len(encoded) > MAX_PATH_BYTES or "\\" in value or "\x00" in value or canonical.is_absolute() or str(canonical) != value or any(part in {"", ".", ".."} for part in canonical.parts)
        if invalid:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_DOCUMENT, "document path is not canonical POSIX")
        return value


class PraxisRenderedDocument(_PraxisDocumentPath):
    """One validated UTF-8 rendered file before manifest and archive assembly."""

    content: bytes = Field(min_length=1, repr=False)

    @field_validator("content")
    @classmethod
    def validate_utf8(cls, value: bytes) -> bytes:
        try:
            value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_DOCUMENT, "document content must be UTF-8") from error
        return value


class PraxisDocumentDescriptor(_PraxisDocumentPath):
    """Ordered in-manifest hash descriptor for one rendered document."""

    sha256: Sha256Hex


def compute_generation_id(snapshot: PraxisSourceSnapshot, compatibility: PraxisCompatibilityContract, payload_hash: Sha256Hex) -> str:
    """Hash the exact length-framed generation compatibility preimage."""
    fields = (
        snapshot.target_id,
        snapshot.source_fingerprint,
        compatibility.bundle_schema,
        compatibility.renderer_version,
        compatibility.praxis_revision,
        compatibility.cpex_contract_version,
        compatibility.mcp_protocol_version,
        compatibility.minimum_launcher_version,
        payload_hash,
    )
    return hashlib.sha256(length_frame_utf8(fields)).hexdigest()


class PraxisRenderManifestV1(PraxisCompatibilityContract):
    """Deterministic in-bundle manifest with no external or secret metadata."""

    manifest_schema: Literal["praxis-render-manifest/v1"] = MANIFEST_SCHEMA_V1
    target_id: SafeIdentifier
    generation_id: Sha256Hex
    source_fingerprint: Sha256Hex
    payload_hash: Sha256Hex
    documents: tuple[PraxisDocumentDescriptor, ...] = Field(min_length=1, max_length=MAX_REGULAR_FILES - 1)

    @model_validator(mode="after")
    def validate_identity_and_documents(self) -> PraxisRenderManifestV1:
        paths = tuple(document.path for document in self.documents)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or MANIFEST_PATH in paths:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_DOCUMENT, "manifest documents must be unique, sorted, and non-self-referential")
        snapshot = PraxisSourceSnapshot(target_id=self.target_id, source_fingerprint=self.source_fingerprint)
        if self.generation_id != compute_generation_id(snapshot, self, self.payload_hash):
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "generation identity does not match manifest fields")
        return self


class PraxisBundleBuildRequest(PraxisStrictModel):
    """Typed input required to assemble one complete deterministic bundle."""

    snapshot: PraxisSourceSnapshot
    compatibility: PraxisCompatibilityContract
    documents: tuple[PraxisRenderedDocument, ...] = Field(min_length=1, max_length=MAX_REGULAR_FILES - 1)

    @model_validator(mode="after")
    def validate_documents(self) -> PraxisBundleBuildRequest:
        paths = tuple(document.path for document in self.documents)
        if len(paths) != len(set(paths)) or MANIFEST_PATH in paths:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_DOCUMENT, "bundle documents must be unique and exclude the manifest")
        return self


class PraxisGenerationEncryptionMetadata(PraxisStrictModel):
    """External encryption and clock metadata never embedded in the archive."""

    ciphertext_hash: Sha256Hex
    envelope_version: Literal[1]
    key_id: SafeIdentifier
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        utc_datetime_text(value)
        return value.astimezone(timezone.utc)

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return utc_datetime_text(value)


class PraxisGenerationEnvelope(PraxisCompatibilityContract):
    """External generation metadata without plaintext or ciphertext bodies."""

    generation_envelope_schema: Literal["praxis-generation-envelope/v1"] = GENERATION_ENVELOPE_SCHEMA_V1
    target_id: SafeIdentifier
    generation_id: Sha256Hex
    source_fingerprint: Sha256Hex
    payload_hash: Sha256Hex
    content_hash: Sha256Hex
    ciphertext_hash: Sha256Hex
    envelope_version: Literal[1]
    key_id: SafeIdentifier
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        utc_datetime_text(value)
        return value.astimezone(timezone.utc)

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return utc_datetime_text(value)

    @model_validator(mode="after")
    def validate_generation_id(self) -> PraxisGenerationEnvelope:
        snapshot = PraxisSourceSnapshot(target_id=self.target_id, source_fingerprint=self.source_fingerprint)
        if self.generation_id != compute_generation_id(snapshot, self, self.payload_hash):
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "generation identity does not match envelope fields")
        return self


@dataclass(frozen=True, slots=True)
class PraxisBundleArtifact:
    """In-memory deterministic plaintext artifact before persistence encryption."""

    manifest: PraxisRenderManifestV1
    manifest_bytes: bytes
    archive_bytes: bytes
    payload_hash: Sha256Hex
    generation_id: Sha256Hex
    content_hash: Sha256Hex

    def generation_envelope(self, metadata: PraxisGenerationEncryptionMetadata) -> PraxisGenerationEnvelope:
        """Bind external encryption metadata to this deterministic artifact."""
        manifest = self.manifest
        return PraxisGenerationEnvelope(
            target_id=manifest.target_id,
            generation_id=self.generation_id,
            source_fingerprint=manifest.source_fingerprint,
            payload_hash=self.payload_hash,
            content_hash=self.content_hash,
            ciphertext_hash=metadata.ciphertext_hash,
            envelope_version=metadata.envelope_version,
            key_id=metadata.key_id,
            created_at=metadata.created_at,
            bundle_schema=manifest.bundle_schema,
            renderer_version=manifest.renderer_version,
            praxis_revision=manifest.praxis_revision,
            cpex_contract_version=manifest.cpex_contract_version,
            mcp_protocol_version=manifest.mcp_protocol_version,
            minimum_launcher_version=manifest.minimum_launcher_version,
        )
