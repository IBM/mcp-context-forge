# -*- coding: utf-8 -*-
"""Tests for translate_header_utils helpers."""

# Third-Party
import pytest

# First-Party
from mcpgateway.translate_header_utils import (
    HeaderMappingError,
    NormalizedMappings,
    extract_env_vars_from_headers,
    parse_header_mappings,
    sanitize_header_value,
    validate_header_mapping,
)


def test_validate_header_mapping_errors():
    validate_header_mapping("Authorization", "AUTH_TOKEN")
    with pytest.raises(HeaderMappingError):
        validate_header_mapping("Invalid Header!", "VAR")
    with pytest.raises(HeaderMappingError):
        validate_header_mapping("Header", "123_VAR")


def test_sanitize_header_value():
    assert sanitize_header_value("Bearer token123") == "Bearer token123"
    assert sanitize_header_value("a" * 10, max_length=5) == "aaaaa"
    assert sanitize_header_value("hello\x00world") == "helloworld"


def test_parse_header_mappings_and_duplicates():
    mappings = parse_header_mappings(["Authorization=AUTH_TOKEN", "X-Api-Key=API_KEY"])
    assert mappings["Authorization"] == "AUTH_TOKEN"
    assert mappings["X-Api-Key"] == "API_KEY"

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["InvalidMapping"])

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["Authorization=AUTH1", "authorization=AUTH2"])


def test_normalized_mappings_and_extract():
    nm = NormalizedMappings({"Authorization": "AUTH"})
    assert nm.get_env_var("authorization") == "AUTH"
    assert list(nm) == [("authorization", "AUTH")]
    assert len(nm) == 1

    headers = {"authorization": "Bearer token", "Content-Type": "application/json"}
    env_vars = extract_env_vars_from_headers(headers, nm)
    assert env_vars == {"AUTH": "Bearer token"}
