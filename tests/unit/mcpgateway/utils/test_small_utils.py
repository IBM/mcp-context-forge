# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_small_utils.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for small utility modules that had low coverage.
"""

# Third-Party
from pydantic import BaseModel
import pytest

# First-Party
from mcpgateway.utils.base_models import BaseModelWithConfigDict
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.origin import is_allowed_redirect, is_exact_https_origin, is_same_origin, normalize_origin_parts, origin_from_url


def test_generate_display_name_empty_string() -> None:
    assert generate_display_name("") == ""


def test_generate_display_name_normalizes_separators_and_title_cases() -> None:
    assert generate_display_name("mixed_Case-Name.test") == "Mixed Case Name Test"
    assert generate_display_name("multiple___underscores") == "Multiple Underscores"
    assert generate_display_name("__tool--name..") == "Tool Name"
    # Technical name present but results in empty display name after normalization
    assert generate_display_name("___...---") == ""


def test_base_model_to_dict_uses_aliases_when_requested() -> None:
    class Example(BaseModelWithConfigDict):
        stop_reason: str = "endTurn"

    obj = Example()

    assert obj.to_dict(use_alias=False) == {"stop_reason": "endTurn"}
    assert obj.to_dict(use_alias=True) == {"stopReason": "endTurn"}


def test_base_model_to_dict_recurses_like_model_dump() -> None:
    class Child(BaseModel):
        child_field: str

    class Parent(BaseModelWithConfigDict):
        child: Child

    obj = Parent(child=Child(child_field="x"))

    # Ensure we call through to model_dump and preserve nested structure
    assert obj.to_dict(use_alias=False) == {"child": {"child_field": "x"}}


def test_normalize_origin_parts_normalizes_case_and_default_ports() -> None:
    assert normalize_origin_parts("HTTP", "Example.COM") == ("http", "example.com", 80)
    assert normalize_origin_parts("https", "example.com:443") == ("https", "example.com", 443)


def test_origin_from_url_removes_path_query_and_fragment() -> None:
    assert origin_from_url("https://example.com:8443/path?query=value#fragment") == "https://example.com:8443"


def test_is_same_origin_requires_matching_absolute_origin() -> None:
    origin = "https://example.com"

    assert not is_same_origin("/dashboard", origin)
    assert is_same_origin("https://EXAMPLE.com:443/dashboard", origin)
    assert not is_same_origin("//evil.example/dashboard", origin)
    assert not is_same_origin("http://example.com/dashboard", origin)
    assert not is_same_origin("https://example.com:8443/dashboard", origin)


@pytest.mark.parametrize("url", ["/\\evil.example/dashboard", " /\\evil.example/dashboard", "\\evil.example/dashboard"])
def test_is_same_origin_rejects_browser_normalized_backslashes(url: str) -> None:
    assert not is_same_origin(url, "https://example.com")


def test_is_same_origin_rejects_backslash_in_reference_origin() -> None:
    assert not is_same_origin("https://example.com/dashboard", "https://example.com\\path")


def test_is_exact_https_origin_rejects_url_suffix_state() -> None:
    assert is_exact_https_origin("https://example.com:8443")
    assert not is_exact_https_origin("http://example.com")
    assert not is_exact_https_origin("https://user@example.com")
    assert not is_exact_https_origin("https://example.com/path")
    assert not is_exact_https_origin("https://example.com?query=value")
    assert not is_exact_https_origin("https://example.com:bad")
    assert not is_exact_https_origin("https://example.com\\path")
    assert not is_exact_https_origin("https://[::1")


def test_is_allowed_redirect_accepts_configured_external_https_origin() -> None:
    assert is_allowed_redirect(
        "https://app.example.org/oauth-complete?gateway_id=123",
        "https://gateway.example.com",
        "https://app.example.org",
    )


def test_is_allowed_redirect_accepts_absolute_app_origin_without_external_origin() -> None:
    assert is_allowed_redirect(
        "https://gateway.example.com/oauth-complete",
        "https://gateway.example.com",
        None,
    )


def test_is_allowed_redirect_rejects_untrusted_or_insecure_external_url() -> None:
    app_origin = "https://gateway.example.com"
    allowed_origin = "https://app.example.org"

    assert not is_allowed_redirect("https://evil.example/oauth-complete", app_origin, allowed_origin)
    assert not is_allowed_redirect("http://app.example.org/oauth-complete", app_origin, allowed_origin)
    assert not is_allowed_redirect("https://user@app.example.org/oauth-complete", app_origin, allowed_origin)
    assert not is_allowed_redirect("https://app.example.org:bad/oauth-complete", app_origin, allowed_origin)
    assert not is_allowed_redirect("https://[::1", app_origin, allowed_origin)


@pytest.mark.parametrize("url", ["//evil.example", "///evil.example", "////evil.example", "\\\\evil.example", "/\\evil.example"])
def test_is_allowed_redirect_rejects_network_path_bypasses(url: str) -> None:
    assert not is_allowed_redirect(url, "https://gateway.example.com", None)


@pytest.mark.parametrize("url", ["", " ", "/oauth-complete", "oauth-complete"])
def test_is_allowed_redirect_rejects_relative_targets(url: str) -> None:
    assert not is_allowed_redirect(url, "https://gateway.example.com", None)
