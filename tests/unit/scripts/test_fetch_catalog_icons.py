# -*- coding: utf-8 -*-
"""Location: ./tests/unit/scripts/test_fetch_catalog_icons.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for offline-safe catalog icon generation helpers.
"""

# Standard
from io import BytesIO
from pathlib import Path

# Third-Party
import pytest
from PIL import Image
import yaml

# First-Party
from scripts.fetch_catalog_icons import (
    IconFetchError,
    IconLinkParser,
    _image_to_png,
    _registrable_domain,
    _safe_asset_id,
    _set_logo_urls,
    _validate_public_https_url,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_registrable_domain_handles_subdomains() -> None:
    assert _registrable_domain("mcp.example.co.uk") == "example.co.uk"
    assert _registrable_domain("mcp.example.com") == "example.com"


@pytest.mark.parametrize("catalog_id, expected", [("github", "github"), ("microsoft/365", "microsoft-365"), ("..", "")])
def test_safe_asset_id(catalog_id: str, expected: str) -> None:
    if expected:
        assert _safe_asset_id(catalog_id) == expected
    else:
        with pytest.raises(ValueError):
            _safe_asset_id(catalog_id)


def test_icon_link_parser_prioritizes_apple_touch_icon() -> None:
    parser = IconLinkParser()
    parser.feed(
        '<link rel="icon" href="/favicon.ico">'
        '<link rel="apple-touch-icon" href="/apple.png">'
        '<link rel="stylesheet" href="/style.css">'
    )
    assert sorted(parser.links) == [(0, "/apple.png"), (1, "/favicon.ico")]


def test_image_to_png_normalizes_dimensions() -> None:
    source = Image.new("RGB", (32, 16), "red")
    raw = BytesIO()
    source.save(raw, format="PNG")
    normalized = Image.open(BytesIO(_image_to_png(raw.getvalue())))
    assert normalized.size == (128, 128)
    assert normalized.mode == "RGBA"


def test_set_logo_urls_preserves_comments_and_updates_existing_field() -> None:
    source = (
        "catalog_servers:\n"
        "  # Keep this comment\n"
        "  - id: github\n"
        "    url: https://example.com/mcp\n"
        "    logo_url: https://old.example/icon.png\n"
        "  - id: local\n"
        "    url: http://localhost:9000/mcp\n"
    )
    result = _set_logo_urls(source, {"github": "/static/catalog-icons/github.png"})
    assert "# Keep this comment" in result
    assert 'logo_url: "/static/catalog-icons/github.png"' in result
    assert "old.example" not in result
    assert "id: local" in result


def test_set_logo_urls_inserts_field_after_url() -> None:
    source = "catalog_servers:\n  - id: github\n    url: https://example.com/mcp\n"
    result = _set_logo_urls(source, {"github": "/static/catalog-icons/github.png"})
    assert result.index("url:") < result.index("logo_url:")


def test_catalog_logo_urls_are_local_and_assets_exist() -> None:
    catalog = yaml.safe_load((REPO_ROOT / "mcp-catalog.yml").read_text(encoding="utf-8"))
    entries = catalog["catalog_servers"]
    local_entries = [entry for entry in entries if entry.get("logo_url")]

    assert local_entries
    for entry in local_entries:
        logo_url = entry["logo_url"]
        assert logo_url.startswith("/static/catalog-icons/")
        assert "://" not in logo_url
        asset = REPO_ROOT / "mcpgateway" / logo_url.lstrip("/")
        assert asset.is_file(), entry["id"]
        with Image.open(asset) as image:
            assert image.size == (128, 128)


def test_icon_fetch_rejects_non_https_and_private_hosts() -> None:
    with pytest.raises(IconFetchError, match="Only HTTPS"):
        _validate_public_https_url("http://example.com/favicon.ico")
    with pytest.raises(IconFetchError, match="Private or special-purpose"):
        _validate_public_https_url("https://localhost/favicon.ico")
