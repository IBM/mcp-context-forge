# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_bundle_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for strict Praxis bundle document validation deny paths.
"""

from __future__ import annotations

import json

from cpex.framework.models import Config
from pydantic import BaseModel
import pytest

from mcpgateway.services import praxis_bundle_validation
from mcpgateway.services.praxis_bundle_renderer import render_praxis_bundle
from mcpgateway.services.praxis_bundle_validation import (
    PraxisBundleRenderError,
    PraxisBundleRenderErrorCode,
    parse_cpex_document,
    parse_praxis_document,
    validate_bundle_documents,
)
from mcpgateway.services.praxis_config_models import (
    PraxisConfigSourceSnapshot,
    PraxisGatewaySource,
    PraxisPromptSource,
    PraxisRenderedDocument,
    PraxisResourceSource,
    PraxisServerSource,
    PraxisToolSource,
    validate_canonical_archive,
)


def _gateway(gateway_id: str) -> PraxisGatewaySource:
    return PraxisGatewaySource(
        id=gateway_id,
        name=gateway_id,
        url=f"https://{gateway_id}.example.test/mcp",
        transport="STREAMABLEHTTP",
        passthrough_headers=("x-request-id",),
    )


def _tool(tool_id: str, name: str, gateway_id: str) -> PraxisToolSource:
    return PraxisToolSource(id=tool_id, name=name, gateway_id=gateway_id, compiled_config=Config(plugins=[]))


def _snapshot() -> PraxisConfigSourceSnapshot:
    server = PraxisServerSource(
        id="server-a",
        name="Team server",
        scope="team-a",
        gateways=(_gateway("gateway-a"),),
        tools=(_tool("tool-a", "search", "gateway-a"),),
        resources=(PraxisResourceSource(id="resource-a", name="guide", uri="https://docs.example.test/guide", gateway_id="gateway-a"),),
        prompts=(PraxisPromptSource(id="prompt-a", name="brief", gateway_id="gateway-a"),),
    )
    return PraxisConfigSourceSnapshot(target_id="target-alpha", source_fingerprint="1" * 64, servers=(server,))


def _documents() -> tuple[PraxisRenderedDocument, ...]:
    archive = render_praxis_bundle(_snapshot()).archive_bytes
    return tuple(document for document in validate_canonical_archive(archive) if document.path != "render-manifest.json")


def _encoded(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _refusal_code(documents: tuple[PraxisRenderedDocument, ...]) -> PraxisBundleRenderErrorCode:
    with pytest.raises(PraxisBundleRenderError) as captured:
        validate_bundle_documents(documents)
    return captured.value.code


def test_unordered_documents_are_refused() -> None:
    documents = _documents()

    assert _refusal_code(tuple(reversed(documents))) is PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL


def test_missing_root_document_is_refused() -> None:
    documents = tuple(document for document in _documents() if document.path != "praxis.yaml")

    assert _refusal_code(documents) is PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL


def test_policy_suffix_mismatch_is_refused() -> None:
    documents = _documents()
    root_path = "praxis.yaml"
    root_content = next(document.content for document in documents if document.path == root_path)
    root = parse_praxis_document(root_content)
    dispatcher = root.filter_chains[0].filters[1]
    mappings = dispatcher.policies or ()
    assert mappings
    mismatched = mappings[0].model_copy(update={"server_id": "mismatched-server"})
    changed = dispatcher.model_copy(update={"policies": (mismatched, *mappings[1:])})
    chain = root.filter_chains[0].model_copy(update={"filters": (root.filter_chains[0].filters[0], changed)})
    rewritten = root.model_copy(update={"filter_chains": (chain,)})
    documents = tuple(PraxisRenderedDocument(path=document.path, content=_encoded(rewritten) if document.path == root_path else document.content) for document in documents)

    assert _refusal_code(documents) is PraxisBundleRenderErrorCode.DANGLING_CONFIG_PATH


def test_unwrap_refuses_unknown_seam_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(praxis_bundle_validation, "_parse", lambda content, cpex: "not-a-document")

    with pytest.raises(AssertionError):
        parse_praxis_document(b"{}")


def test_parse_praxis_document_refuses_cpex_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    cpex_document = parse_cpex_document(next(document.content for document in _documents() if document.path.startswith("cpex/")))
    monkeypatch.setattr(praxis_bundle_validation, "_parse", lambda content, cpex: cpex_document)

    with pytest.raises(PraxisBundleRenderError) as captured:
        parse_praxis_document(b"{}")

    assert captured.value.code is PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL


def test_parse_cpex_document_refuses_bundle_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_document = parse_praxis_document(next(document.content for document in _documents() if document.path == "praxis.yaml"))
    monkeypatch.setattr(praxis_bundle_validation, "_parse", lambda content, cpex: bundle_document)

    with pytest.raises(PraxisBundleRenderError) as captured:
        parse_cpex_document(b"{}")

    assert captured.value.code is PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL


def test_parse_praxis_document_exhaustiveness_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(praxis_bundle_validation, "_unwrap", lambda outcome: "not-a-document")

    with pytest.raises(AssertionError):
        parse_praxis_document(b"{}")


def test_parse_cpex_document_exhaustiveness_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(praxis_bundle_validation, "_unwrap", lambda outcome: "not-a-document")

    with pytest.raises(AssertionError):
        parse_cpex_document(b"{}")
