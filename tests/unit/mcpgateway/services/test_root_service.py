# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_root_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from unittest.mock import MagicMock, patch

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.root_service import RootService, RootServiceError, RootServiceValidationError


@pytest.fixture(autouse=True)
def secure_root_defaults(monkeypatch):
    """Reset root URI policy to secure defaults."""
    monkeypatch.setattr(settings, "root_allowed_schemes", [])
    monkeypatch.setattr(settings, "root_allow_file_scheme", False)
    monkeypatch.setattr(settings, "root_allowed_file_prefixes", [])
    monkeypatch.setattr(settings, "default_roots", [])


@pytest.mark.asyncio
async def test_rejects_scheme_less_paths_by_default():
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.add_root("/tmp/project")

    assert excinfo.value.reason_code == "scheme_missing"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [(None, "non-string"), ("http://[", "invalid"), ("/tmp/root", "missing"), ("HTTPS://example.com/root", "https")],
)
def test_safe_scheme_never_returns_raw_input(uri, expected):
    assert RootService._safe_scheme(uri) == expected


def test_canonical_root_model_validation_maps_to_policy_error(monkeypatch):
    service = RootService()
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])

    def invalid_root(**_kwargs):
        raise ValidationError.from_exception_data("Root", [{"type": "string_type", "loc": ("uri",), "input": None}])

    monkeypatch.setattr("mcpgateway.services.root_service.Root", invalid_root)

    with pytest.raises(RootServiceValidationError) as excinfo:
        service._validate_and_canonicalize_root_uri("https://example.com/root")

    assert excinfo.value.reason_code == "scheme_not_allowed"


def test_canonical_root_model_unexpected_error_propagates(monkeypatch):
    service = RootService()
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    monkeypatch.setattr("mcpgateway.services.root_service.Root", MagicMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        service._validate_and_canonicalize_root_uri("https://example.com/root")


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["file:///etc/passwd", "file:///proc/self/environ"])
async def test_rejects_file_roots_by_default(uri):
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.add_root(uri)

    assert excinfo.value.reason_code == "file_disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["ftp://example.com/root", "data:text/plain,hi", "javascript:alert(1)", "vbscript:msgbox(1)", "custom://root"])
async def test_rejects_non_allowlisted_schemes(uri):
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.add_root(uri)

    assert excinfo.value.reason_code in {"scheme_not_allowed", "query_not_allowed"}


@pytest.mark.asyncio
async def test_accepts_explicitly_allowlisted_network_scheme(monkeypatch):
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    service = RootService()

    root = await service.add_root("HTTPS://Example.COM:443/base/path", "Docs")

    assert str(root.uri) == "https://example.com/base/path"
    assert root.name == "Docs"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uri", "reason_code"),
    [
        ("https://user:pass@example.com/root", "userinfo_not_allowed"),  # pragma: allowlist secret
        ("https://example.com/root?token=secret", "query_not_allowed"),
        ("https://example.com/root#frag", "fragment_not_allowed"),
        ("https://example.com/%zz", "invalid_percent_encoding"),
        ("https://example.com/\r\nx", "control_character"),
        ("https://:bad", "network_host_missing"),
    ],
)
async def test_rejects_unsafe_network_uri_components(monkeypatch, uri, reason_code):
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.add_root(uri)

    assert excinfo.value.reason_code == reason_code


@pytest.mark.asyncio
async def test_duplicate_equivalent_network_uri_raises(monkeypatch):
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    service = RootService()

    await service.add_root("https://example.com:443/root")

    with pytest.raises(RootServiceError) as excinfo:
        await service.add_root("HTTPS://EXAMPLE.COM/root")

    assert "Root already exists" in str(excinfo.value)


@pytest.mark.asyncio
async def test_optional_file_policy_accepts_allowed_descendant(monkeypatch):
    monkeypatch.setattr(settings, "root_allow_file_scheme", True)
    monkeypatch.setattr(settings, "root_allowed_file_prefixes", ["/workspace"])
    service = RootService()

    root = await service.add_root("file:///workspace/project")

    assert str(root.uri) == "file:///workspace/project"
    assert root.name == "project"


@pytest.mark.asyncio
async def test_optional_file_policy_canonicalizes_single_dot_segments(monkeypatch):
    monkeypatch.setattr(settings, "root_allow_file_scheme", True)
    monkeypatch.setattr(settings, "root_allowed_file_prefixes", ["/workspace"])
    service = RootService()

    root = await service.add_root("file:///workspace/./project/./docs")

    assert str(root.uri) == "file:///workspace/project/docs"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uri", "reason_code"),
    [
        ("file://localhost/workspace/project", "file_authority_not_allowed"),
        ("file:///workspace/../etc", "file_path_traversal"),
        ("file:///workspace%2fsecret", "file_path_unsafe_encoding"),
        ("file:///workspace-evil/root", "file_path_outside_allowed_prefix"),
        ("file:///C:/workspace/root", "file_path_unsupported"),
    ],
)
async def test_optional_file_policy_rejects_unsafe_forms(monkeypatch, uri, reason_code):
    monkeypatch.setattr(settings, "root_allow_file_scheme", True)
    monkeypatch.setattr(settings, "root_allowed_file_prefixes", ["/workspace"])
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.add_root(uri)

    assert excinfo.value.reason_code == reason_code


@pytest.mark.asyncio
async def test_update_validates_name_and_notifies(monkeypatch):
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    service = RootService()
    await service.add_root("https://example.com/root", name="Initial")
    notifications = []

    async def collect_notification():
        async for event in service.subscribe_changes():
            notifications.append(event)
            if event["type"] == "root_updated":
                break

    task = asyncio.create_task(collect_notification())
    await asyncio.sleep(0)
    updated = await service.update_root("HTTPS://EXAMPLE.COM:443/root", name="Updated")
    await asyncio.wait_for(task, timeout=1.0)

    assert updated.name == "Updated"
    assert notifications[0]["type"] == "root_updated"


@pytest.mark.asyncio
async def test_initialize_fails_on_invalid_default_root(monkeypatch):
    monkeypatch.setattr(settings, "default_roots", ["https://example.com/root"])
    service = RootService()

    with pytest.raises(RootServiceValidationError) as excinfo:
        await service.initialize()

    assert excinfo.value.reason_code == "scheme_not_allowed"


@pytest.mark.asyncio
async def test_list_roots_creates_span(monkeypatch):
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    service = RootService()
    await service.add_root("https://example.com/root-one")
    span_cm = MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))

    with patch("mcpgateway.services.root_service.create_span", return_value=span_cm) as mock_create_span:
        roots = await service.list_roots()

    assert len(roots) == 1
    mock_create_span.assert_called_once_with("root.list", {"root.count": 1})
