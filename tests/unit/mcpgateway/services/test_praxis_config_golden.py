"""Cross-language golden tests for Praxis configuration contracts."""

import hashlib
import json
from pathlib import Path

from mcpgateway.services.praxis_config_models import (
    PraxisBundleBuildRequest,
    PraxisCompatibilityContract,
    PraxisDirectiveIdentity,
    PraxisRenderedDocument,
    PraxisSourceSnapshot,
    build_directive,
    build_praxis_bundle,
    compute_response_etag,
    length_frame_utf8,
)

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "praxis_config"


def test_golden_vector_locks_cross_language_bytes() -> None:
    # Given: language-neutral inputs and committed expected bytes.
    vector = json.loads((FIXTURE_DIR / "contract-v1.json").read_text(encoding="utf-8"))
    documents = tuple(PraxisRenderedDocument(path=item["path"], content=item["content_utf8"].encode()) for item in vector["input"]["documents"])
    request = PraxisBundleBuildRequest(
        snapshot=PraxisSourceSnapshot.model_validate(vector["input"]["snapshot"]),
        compatibility=PraxisCompatibilityContract.model_validate(vector["input"]["compatibility"]),
        documents=documents,
    )
    # When: Python builds the complete contract vector.
    artifact = build_praxis_bundle(request)
    directive = build_directive(PraxisDirectiveIdentity.model_validate_json(json.dumps(vector["input"]["directive"])))
    archive_vector = json.loads((FIXTURE_DIR / "archive-v1.json").read_text(encoding="utf-8"))
    documents_by_path = sorted(vector["input"]["documents"], key=lambda item: item["path"])
    payload_fields = tuple(value for item in documents_by_path for value in (item["path"], item["content_utf8"]))
    compatibility = vector["input"]["compatibility"]
    snapshot = vector["input"]["snapshot"]
    generation_fields = (
        snapshot["target_id"],
        snapshot["source_fingerprint"],
        compatibility["bundle_schema"],
        compatibility["renderer_version"],
        compatibility["praxis_revision"],
        compatibility["cpex_contract_version"],
        compatibility["mcp_protocol_version"],
        compatibility["minimum_launcher_version"],
        vector["expected"]["payload_hash"],
    )
    directive_input = vector["input"]["directive"]
    directive_fields = (
        directive_input["target_id"],
        directive_input["rollout_id"],
        str(directive_input["policy_epoch"]),
        directive_input["action"],
        directive_input["generation_id"],
        directive_input["eligibility_deadline"],
    )
    # Then: every byte/hash matches consumers in any implementation language.
    assert artifact.manifest.model_dump(mode="json") == vector["expected"]["manifest"]
    assert artifact.manifest_bytes.hex() == vector["expected"]["manifest_hex"]
    assert len(artifact.archive_bytes) == archive_vector["length_bytes"]
    assert [hashlib.sha256(artifact.archive_bytes[offset : offset + 512]).hexdigest() for offset in range(0, len(artifact.archive_bytes), 512)] == archive_vector["blocks_sha256"]
    assert artifact.payload_hash == vector["expected"]["payload_hash"]
    assert artifact.generation_id == vector["expected"]["generation_id"]
    assert artifact.content_hash == vector["expected"]["content_hash"]
    assert directive.directive_id == vector["expected"]["directive_id"]
    assert compute_response_etag(directive.directive_id, 4, 5) == vector["expected"]["response_etag"]
    assert length_frame_utf8(payload_fields).hex() == vector["expected"]["payload_preimage_hex"]
    assert length_frame_utf8(generation_fields).hex() == vector["expected"]["generation_preimage_hex"]
    assert length_frame_utf8(directive_fields).hex() == vector["expected"]["directive_preimage_hex"]
    assert length_frame_utf8((directive.directive_id, "4", "5")).hex() == vector["expected"]["response_etag_preimage_hex"]
