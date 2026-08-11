"""Contract tests for deterministic Praxis configuration delivery models."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import tarfile
import traceback

from hypothesis import given
from hypothesis import strategies as st
import pytest
from pydantic import BaseModel, ValidationError

from mcpgateway.services import praxis_config_models
from mcpgateway.services.praxis_config_models import (
    MAX_ARCHIVE_BYTES,
    DirectiveAction,
    PraxisActivationCohort,
    PraxisBundleBuildRequest,
    PraxisBundleArtifact,
    PraxisCompatibilityContract,
    PraxisConfigContractError,
    PraxisContractErrorCode,
    PraxisDirectiveIdentity,
    PraxisDirectiveResponse,
    PraxisDirectiveResponseInput,
    PraxisFailedReport,
    PraxisGenerationEnvelope,
    PraxisGenerationEncryptionMetadata,
    PraxisRenderManifestV1,
    PraxisRenderedDocument,
    PraxisSourceSnapshot,
    ReportState,
    ReplicaFailureCategory,
    build_directive,
    build_praxis_bundle,
    canonical_json_bytes,
    compute_generation_id,
    compute_response_etag,
    length_frame_utf8,
    parse_replica_report,
    validate_canonical_archive,
)

SOURCE_FINGERPRINT = "11" * 32


def _compatibility() -> PraxisCompatibilityContract:
    return PraxisCompatibilityContract(
        bundle_schema="praxis-bundle/v1",
        renderer_version="1.2.3",
        praxis_revision="ed46eb5",
        cpex_contract_version="cpex/v1",
        mcp_protocol_version="2025-11-25",
        minimum_launcher_version="0.1.0",
    )


def _snapshot() -> PraxisSourceSnapshot:
    return PraxisSourceSnapshot(target_id="target-alpha", source_fingerprint=SOURCE_FINGERPRINT)


def _documents() -> tuple[PraxisRenderedDocument, ...]:
    return (
        PraxisRenderedDocument(path="praxis.yaml", content=b"version: 1\nname: Praxis\n"),
        PraxisRenderedDocument(path="cpex/team-a--server-1.yaml", content="policy: allow\nlabel: café\n".encode()),
    )


def _artifact(documents: tuple[PraxisRenderedDocument, ...] | None = None) -> PraxisBundleArtifact:
    request = PraxisBundleBuildRequest(snapshot=_snapshot(), compatibility=_compatibility(), documents=documents or _documents())
    return build_praxis_bundle(request)


def _directive_identity(rollout_id: str = "rollout-001") -> PraxisDirectiveIdentity:
    return PraxisDirectiveIdentity(
        target_id="target-alpha",
        rollout_id=rollout_id,
        policy_epoch=7,
        action=DirectiveAction.ACTIVATE,
        generation_id=_artifact().generation_id,
        eligibility_deadline=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )


def test_length_frame_utf8_uses_big_endian_byte_lengths() -> None:
    # Given: one ASCII and one multibyte UTF-8 field.
    fields = ("A", "é")
    # When: the contract frames the fields.
    framed = length_frame_utf8(fields)
    # Then: lengths count encoded bytes and use four-byte big-endian integers.
    assert framed.hex() == "000000014100000002c3a9"


@given(st.lists(st.text(max_size=20), max_size=8))
def test_length_frame_utf8_round_trips_field_boundaries(fields: list[str]) -> None:
    # Given: arbitrary Unicode fields.
    framed = length_frame_utf8(fields)
    # When: an independent cursor walks the framed bytes.
    cursor = 0
    decoded: list[str] = []
    while cursor < len(framed):
        size = int.from_bytes(framed[cursor : cursor + 4], "big")
        cursor += 4
        decoded.append(framed[cursor : cursor + size].decode())
        cursor += size
    # Then: field boundaries and Unicode values are preserved exactly.
    assert decoded == fields


@pytest.mark.parametrize(
    "field",
    ["bundle_schema", "renderer_version", "praxis_revision", "cpex_contract_version", "mcp_protocol_version", "minimum_launcher_version"],
)
def test_generation_changes_when_any_compatibility_field_changes(field: str) -> None:
    # Given: one payload and a complete compatibility tuple.
    artifact = _artifact()
    changed = _compatibility().model_copy(update={field: f"changed-{field}"})
    # When: one compatibility component changes.
    changed_generation = compute_generation_id(_snapshot(), changed, artifact.payload_hash)
    # Then: the immutable content generation changes.
    assert changed_generation != artifact.generation_id


def test_bundle_is_deterministic_across_document_order() -> None:
    # Given: identical rendered documents in opposite orders.
    documents = _documents()
    # When: both bundles are assembled.
    first = _artifact(documents)
    second = _artifact(tuple(reversed(documents)))
    # Then: payload, manifest, archive, and identities are byte-identical.
    assert (first.payload_hash, first.manifest_bytes, first.archive_bytes, first.generation_id, first.content_hash) == (
        second.payload_hash,
        second.manifest_bytes,
        second.archive_bytes,
        second.generation_id,
        second.content_hash,
    )


def test_manifest_excludes_external_and_secret_fields() -> None:
    # Given: a valid deterministic manifest with one forbidden external field added.
    manifest = _artifact().manifest.model_dump(mode="json")
    # When/Then: self-hashing, clock, key, body, and credential fields are rejected.
    for field in ("content_hash", "ciphertext_hash", "key_id", "created_at", "plaintext", "authorization"):
        with pytest.raises(ValidationError):
            PraxisRenderManifestV1.model_validate(manifest | {field: "forbidden"})


def test_canonical_json_rejects_float_fields() -> None:
    # Given: an otherwise serializable model containing a float.
    class FloatModel(BaseModel):
        value: float

    # When/Then: canonical serialization refuses floating-point values.
    with pytest.raises(PraxisConfigContractError):
        canonical_json_bytes(FloatModel(value=7.0))


def test_archive_is_exact_posix_ustar() -> None:
    # Given: a complete deterministic bundle.
    archive = _artifact().archive_bytes
    # When: the standard library parses its records.
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
        members = bundle.getmembers()
    # Then: paths and metadata match the canonical archive profile.
    assert [member.name for member in members] == sorted(member.name for member in members)
    assert all(member.isreg() and member.uid == 0 and member.gid == 0 for member in members)
    assert all(member.uname == member.gname == "" and member.mode == 0o600 and member.mtime == 0 for member in members)
    assert archive[-1024:] == bytes(1024)
    assert archive[-1536:-1024] != bytes(512)
    assert len(archive) % 512 == 0


@pytest.mark.parametrize("archive_format", [tarfile.PAX_FORMAT, tarfile.GNU_FORMAT], ids=["pax", "gnu"])
def test_archive_validator_rejects_pax_or_gnu_archives(archive_format: int) -> None:
    # Given: a non-ustar archive using PAX or GNU formatting.
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=archive_format) as bundle:
        info = tarfile.TarInfo("praxis.yaml")
        info.size = 1
        info.pax_headers = {"comment": "not-ustar"}
        bundle.addfile(info, BytesIO(b"x"))
    # When/Then: the strict archive boundary rejects noncanonical extensions.
    with pytest.raises(PraxisConfigContractError):
        validate_canonical_archive(output.getvalue())


@pytest.mark.parametrize("path", ["../praxis.yaml", "/praxis.yaml", "cpex//server.yaml", f"cpex/{'x' * 236}"])
def test_rendered_document_rejects_noncanonical_paths(path: str) -> None:
    # Given/When/Then: traversal, absolute, normalized, and oversized paths fail closed.
    with pytest.raises(ValidationError):
        PraxisRenderedDocument(path=path, content=b"x")


def test_bundle_rejects_duplicates_and_oversized_archive() -> None:
    # Given: duplicate paths and a payload beyond the download ceiling.
    document = PraxisRenderedDocument(path="praxis.yaml", content=b"x")
    with pytest.raises(ValidationError):
        PraxisBundleBuildRequest(snapshot=_snapshot(), compatibility=_compatibility(), documents=(document, document))
    oversized = PraxisRenderedDocument(path="praxis.yaml", content=b"x" * MAX_ARCHIVE_BYTES)
    # When/Then: neither malformed bundle reaches publication.
    with pytest.raises(PraxisConfigContractError):
        _artifact((oversized,))


def test_generation_envelope_requires_utc_and_matching_compatibility() -> None:
    # Given: a complete artifact envelope.
    artifact = _artifact()
    metadata = PraxisGenerationEncryptionMetadata(
        ciphertext_hash="22" * 32,
        envelope_version=1,
        key_id="key-2026-08",
        created_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )
    # When: UTC input is parsed.
    envelope = artifact.generation_envelope(metadata)
    values = envelope.model_dump()
    # Then: it serializes canonically and rejects naive or incompatible variants.
    assert b'"created_at":"2026-08-10T12:00:00Z"' in canonical_json_bytes(envelope)
    with pytest.raises(ValidationError):
        PraxisGenerationEncryptionMetadata.model_validate(metadata.model_dump() | {"created_at": datetime(2026, 8, 10, 12, 0)})
    with pytest.raises(ValidationError):
        PraxisGenerationEnvelope.model_validate(values | {"renderer_version": "incompatible"})


def test_cursor_changes_response_etag_without_changing_directive() -> None:
    # Given: one immutable activation directive and its frozen cohort.
    directive = build_directive(_directive_identity())
    cohort = PraxisActivationCohort(
        target_id=directive.target_id,
        rollout_id=directive.rollout_id,
        directive_id=directive.directive_id,
        replica_ids=("replica-a", "replica-b"),
    )
    # When: report cursors advance.
    first = PraxisDirectiveResponse.create(PraxisDirectiveResponseInput(directive=directive, cohort=cohort, last_accepted_report_cursor=0, next_report_cursor=1))
    second = PraxisDirectiveResponse.create(PraxisDirectiveResponseInput(directive=directive, cohort=cohort, last_accepted_report_cursor=1, next_report_cursor=2))
    # Then: only the HTTP response identity changes.
    assert first.directive.directive_id == second.directive.directive_id
    assert first.response_etag != second.response_etag
    assert second.response_etag == compute_response_etag(directive.directive_id, 1, 2)


def test_directive_rejects_an_identity_not_derived_from_its_fields() -> None:
    # Given: a valid directive whose stable ID is replaced.
    directive = build_directive(_directive_identity())
    values = directive.model_dump()
    values["directive_id"] = "00" * 32
    # When/Then: direct external model parsing cannot bypass ID derivation.
    with pytest.raises(ValidationError):
        type(directive).model_validate(values)


def test_one_generation_can_back_multiple_rollouts() -> None:
    # Given: the same generation issued under two rollout IDs.
    first = build_directive(_directive_identity("rollout-001"))
    second = build_directive(_directive_identity("rollout-002"))
    # When/Then: generation remains reusable while rollout/directive identity changes.
    assert first.generation_id == second.generation_id
    assert first.rollout_id != second.rollout_id
    assert first.directive_id != second.directive_id


def test_response_rejects_wrong_target_or_directive_cohort() -> None:
    # Given: a valid directive with a cohort bound to another target.
    directive = build_directive(_directive_identity())
    cohort = PraxisActivationCohort(
        target_id="target-other",
        rollout_id=directive.rollout_id,
        directive_id=directive.directive_id,
        replica_ids=("replica-a",),
    )
    # When/Then: the external response cannot combine cross-target state.
    with pytest.raises(ValidationError):
        PraxisDirectiveResponse.create(PraxisDirectiveResponseInput(directive=directive, cohort=cohort, last_accepted_report_cursor=0, next_report_cursor=1))


@pytest.mark.parametrize("field", ["target_id", "replica_id", "plaintext", "ciphertext", "authorization", "token"])
def test_replica_reports_reject_identity_body_and_secret_fields(field: str) -> None:
    # Given: a prepared report plus one caller-controlled or secret field.
    report = {"report_schema": "praxis-replica-report/v1", "directive_id": "33" * 32, "sequence": 1, "state": ReportState.PREPARED, field: "forbidden"}
    # When/Then: report parsing rejects the field rather than exposing it.
    with pytest.raises(PraxisConfigContractError):
        parse_replica_report(json.dumps(report))


def test_replica_report_boundary_hides_the_raw_validation_adapter() -> None:
    assert not hasattr(praxis_config_models, "PRAXIS_REPLICA_REPORT_ADAPTER")
    assert "PRAXIS_REPLICA_REPORT_ADAPTER" not in praxis_config_models.__all__


def test_replica_report_error_discards_secret_validation_input() -> None:
    sentinel = "TOP-SECRET-SENTINEL"
    report = {
        "report_schema": "praxis-replica-report/v1",
        "directive_id": "33" * 32,
        "sequence": 1,
        "state": ReportState.PREPARED,
        "authorization": f"Bearer {sentinel}",
    }

    with pytest.raises(PraxisConfigContractError) as captured:
        parse_replica_report(json.dumps(report))

    error = captured.value
    rendered_channels = {
        "message": str(error),
        "arguments": repr(error.args),
        "attributes": repr(vars(error)),
        "json": json.dumps({"code": error.code, "detail": error.detail}),
        "traceback": "".join(traceback.format_exception(error)),
        "cause": repr(error.__cause__),
        "context": repr(error.__context__),
    }
    assert error.code is PraxisContractErrorCode.INVALID_CANONICAL_VALUE
    assert error.detail == "replica report is invalid"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(sentinel not in rendered for rendered in rendered_channels.values()), rendered_channels


def test_replica_reports_parse_explicit_success_and_failure_variants() -> None:
    # Given: one progress report and one sanitized failure report.
    prepared = {"report_schema": "praxis-replica-report/v1", "directive_id": "33" * 32, "sequence": 1, "state": "prepared"}
    failed = {"report_schema": "praxis-replica-report/v1", "directive_id": "33" * 32, "sequence": 2, "state": "failed", "failure_category": "policy_canary"}
    # When: the discriminated report boundary parses each variant.
    parsed = (parse_replica_report(json.dumps(prepared)), parse_replica_report(json.dumps(failed)))
    # Then: state is explicit and an unknown state fails closed.
    assert (parsed[0].state, parsed[1].state) == (ReportState.PREPARED, ReportState.FAILED)
    assert PraxisFailedReport.model_validate(failed).failure_category is ReplicaFailureCategory.POLICY_CANARY
    with pytest.raises(PraxisConfigContractError):
        parse_replica_report(json.dumps(prepared | {"state": "unknown"}))
