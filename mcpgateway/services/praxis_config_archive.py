"""Canonical JSON, payload hashing, and POSIX ustar assembly for Praxis."""

from __future__ import annotations

from contextlib import closing
from io import BytesIO
import json
import hashlib
import tarfile
from typing import Sequence, TypeAlias, assert_never

from pydantic import BaseModel, ValidationError

from mcpgateway.services._praxis_config_core import (
    MANIFEST_PATH,
    MAX_ARCHIVE_BYTES,
    MAX_EXTRACTED_BYTES,
    MAX_REGULAR_FILES,
    PraxisBundleArtifact,
    PraxisBundleBuildRequest,
    PraxisConfigContractError,
    PraxisContractErrorCode,
    PraxisDocumentDescriptor,
    PraxisRenderManifestV1,
    PraxisRenderedDocument,
    compute_generation_id,
    length_frame_utf8,
)

RawJsonValue: TypeAlias = str | int | float | bool | None | list["RawJsonValue"] | dict[str, "RawJsonValue"]


def _reject_float(value: RawJsonValue) -> None:
    match value:
        case float():
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "floats are forbidden in canonical JSON")
        case dict():
            for nested in value.values():
                _reject_float(nested)
        case list():
            for nested in value:
                _reject_float(nested)
        case str() | int() | bool() | None:
            return
        case unreachable:
            assert_never(unreachable)


def canonical_json_bytes(model: BaseModel) -> bytes:
    """Serialize a strict model as sorted compact UTF-8 JSON without floats."""
    value: RawJsonValue = model.model_dump(mode="json")
    _reject_float(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sorted_documents(documents: Sequence[PraxisRenderedDocument]) -> tuple[PraxisRenderedDocument, ...]:
    return tuple(sorted(documents, key=lambda document: document.path))


def _payload_hash(documents: Sequence[PraxisRenderedDocument]) -> str:
    fields: list[str] = []
    for document in _sorted_documents(documents):
        fields.extend((document.path, document.content.decode("utf-8")))
    return hashlib.sha256(length_frame_utf8(fields)).hexdigest()


def _document_descriptors(documents: Sequence[PraxisRenderedDocument]) -> tuple[PraxisDocumentDescriptor, ...]:
    return tuple(PraxisDocumentDescriptor(path=document.path, sha256=hashlib.sha256(document.content).hexdigest()) for document in _sorted_documents(documents))


def _ustar_bytes(documents: Sequence[PraxisRenderedDocument]) -> bytes:
    ordered = _sorted_documents(documents)
    if len(ordered) > MAX_REGULAR_FILES:
        raise PraxisConfigContractError(PraxisContractErrorCode.LIMIT_EXCEEDED, "archive contains too many regular files")
    extracted_size = sum(len(document.content) for document in ordered)
    if extracted_size > MAX_EXTRACTED_BYTES:
        raise PraxisConfigContractError(PraxisContractErrorCode.LIMIT_EXCEEDED, "archive extracted content exceeds limit")
    output = bytearray()
    for document in ordered:
        info = tarfile.TarInfo(document.path)
        info.size = len(document.content)
        info.mode = 0o600
        info.uid = 0
        info.gid = 0
        info.mtime = 0
        info.uname = ""
        info.gname = ""
        info.type = tarfile.REGTYPE
        try:
            output.extend(info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8", errors="strict"))
        except (UnicodeError, ValueError) as error:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_DOCUMENT, "document path cannot be represented as POSIX ustar") from error
        output.extend(document.content)
        output.extend(bytes((-len(document.content)) % tarfile.BLOCKSIZE))
    output.extend(bytes(2 * tarfile.BLOCKSIZE))
    archive = bytes(output)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise PraxisConfigContractError(PraxisContractErrorCode.LIMIT_EXCEEDED, "canonical archive exceeds download limit")
    return archive


def build_praxis_bundle(request: PraxisBundleBuildRequest) -> PraxisBundleArtifact:
    """Build payload identity, deterministic manifest, and canonical archive."""
    payload_hash = _payload_hash(request.documents)
    generation_id = compute_generation_id(request.snapshot, request.compatibility, payload_hash)
    compatibility = request.compatibility
    manifest = PraxisRenderManifestV1(
        target_id=request.snapshot.target_id,
        generation_id=generation_id,
        source_fingerprint=request.snapshot.source_fingerprint,
        payload_hash=payload_hash,
        documents=_document_descriptors(request.documents),
        bundle_schema=compatibility.bundle_schema,
        renderer_version=compatibility.renderer_version,
        praxis_revision=compatibility.praxis_revision,
        cpex_contract_version=compatibility.cpex_contract_version,
        mcp_protocol_version=compatibility.mcp_protocol_version,
        minimum_launcher_version=compatibility.minimum_launcher_version,
    )
    manifest_bytes = canonical_json_bytes(manifest)
    archive_documents = (*request.documents, PraxisRenderedDocument(path=MANIFEST_PATH, content=manifest_bytes))
    archive_bytes = _ustar_bytes(archive_documents)
    return PraxisBundleArtifact(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        archive_bytes=archive_bytes,
        payload_hash=payload_hash,
        generation_id=generation_id,
        content_hash=hashlib.sha256(archive_bytes).hexdigest(),
    )


def validate_canonical_archive(archive: bytes) -> tuple[PraxisRenderedDocument, ...]:
    """Parse and byte-verify the exact canonical regular-file ustar profile."""
    if len(archive) > MAX_ARCHIVE_BYTES or len(archive) < 3 * tarfile.BLOCKSIZE or len(archive) % tarfile.BLOCKSIZE != 0:
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive size or block framing is invalid")
    if archive[-1024:] != bytes(1024) or archive[-1536:-1024] == bytes(512):
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive must end with exactly two zero blocks")
    documents: list[PraxisRenderedDocument] = []
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_REGULAR_FILES:
                raise PraxisConfigContractError(PraxisContractErrorCode.LIMIT_EXCEEDED, "archive contains too many regular files")
            for member in members:
                canonical_metadata = (
                    member.type == tarfile.REGTYPE
                    and member.uid == 0
                    and member.gid == 0
                    and member.uname == ""
                    and member.gname == ""
                    and member.mode == 0o600
                    and member.mtime == 0
                    and member.linkname == ""
                    and not member.pax_headers
                )
                if not canonical_metadata:
                    raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive member metadata is not canonical ustar")
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "regular archive member has no content")
                with closing(extracted):
                    documents.append(PraxisRenderedDocument(path=member.name, content=extracted.read()))
    except (tarfile.TarError, ValidationError) as error:
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive cannot be parsed as ustar") from error
    ordered = tuple(documents)
    if tuple(document.path for document in ordered) != tuple(sorted(document.path for document in ordered)) or len({document.path for document in ordered}) != len(ordered):
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive paths must be unique and sorted")
    if _ustar_bytes(ordered) != archive:
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_ARCHIVE, "archive bytes are not canonical")
    return ordered
