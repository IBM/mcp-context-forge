# -*- coding: utf-8 -*-
"""Location: ./tests/unit/scripts/test_fetch_catalog_icons.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for offline-safe catalog icon generation helpers.
"""

# Standard
from argparse import Namespace
from io import BytesIO
from pathlib import Path
import socket
from unittest.mock import patch

# Third-Party
import httpx
from PIL import Image
import pytest
import yaml

# Local
from scripts.fetch_catalog_icons import (
    _fetch,
    _has_normalized_icon_bounds,
    _image_to_png,
    _parse_args,
    _registrable_domain,
    _safe_asset_id,
    _set_logo_urls,
    _validate_public_https_url,
    generate_icons,
    IconFetchError,
    IconLinkParser,
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
    parser.feed('<link rel="icon" href="/favicon.ico">' '<link rel="apple-touch-icon" href="/apple.png">' '<link rel="stylesheet" href="/style.css">')
    assert sorted(parser.links) == [(0, "/apple.png"), (1, "/favicon.ico")]


def test_image_to_png_normalizes_dimensions() -> None:
    source = Image.new("RGB", (32, 16), "red")
    raw = BytesIO()
    source.save(raw, format="PNG")
    normalized = Image.open(BytesIO(_image_to_png(raw.getvalue())))
    assert normalized.size == (128, 128)
    assert normalized.mode == "RGBA"


def test_image_to_png_trims_transparent_padding() -> None:
    source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    source.paste(Image.new("RGBA", (16, 16), "red"), (56, 56))
    raw = BytesIO()
    source.save(raw, format="PNG")

    normalized = Image.open(BytesIO(_image_to_png(raw.getvalue())))

    assert normalized.getchannel("A").getbbox() == (48, 48, 80, 80)


def test_image_to_png_caps_upscale_and_marks_result() -> None:
    source = Image.new("RGBA", (16, 8), "red")
    raw = BytesIO()
    source.save(raw, format="PNG")

    normalized_bytes = _image_to_png(raw.getvalue())
    normalized = Image.open(BytesIO(normalized_bytes))

    assert normalized.getchannel("A").getbbox() == (48, 56, 80, 72)
    assert _has_normalized_icon_bounds(normalized_bytes) is True


def test_icon_normalization_rejects_empty_canvas() -> None:
    source = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    raw = BytesIO()
    source.save(raw, format="PNG")

    with pytest.raises(IconFetchError, match="Image has no visible pixels"):
        _image_to_png(raw.getvalue())

    source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    raw = BytesIO()
    source.save(raw, format="PNG")
    with pytest.raises(IconFetchError, match="Image has no visible pixels"):
        _has_normalized_icon_bounds(raw.getvalue())


@pytest.mark.parametrize(("extent", "expected"), [(16, False), (120, True), (128, True)])
def test_has_normalized_icon_bounds_uses_visible_extent(extent: int, expected: bool) -> None:
    source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    offset = (128 - extent) // 2
    source.paste(Image.new("RGBA", (extent, extent), "red"), (offset, offset))
    raw = BytesIO()
    source.save(raw, format="PNG")

    assert _has_normalized_icon_bounds(raw.getvalue()) is expected


def test_normalize_existing_does_not_fetch_missing_icons(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text(
        "catalog_servers:\n" "  - id: existing\n" "    url: https://existing.example/mcp\n" "  - id: missing\n" "    url: https://missing.example/mcp\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "icons"
    output_dir.mkdir()
    image = Image.new("RGBA", (16, 16), "red")
    image.save(output_dir / "existing.png", format="PNG")
    args = Namespace(
        catalog=catalog_path,
        output_dir=output_dir,
        overrides=tmp_path / "overrides.json",
        timeout=1.0,
        force=False,
        normalize_existing=True,
        dry_run=False,
        strict=False,
    )

    with patch("scripts.fetch_catalog_icons._fetch_icon") as fetch_icon:
        assert generate_icons(args) == 0
        normalized = (output_dir / "existing.png").read_bytes()
        assert generate_icons(args) == 0

    fetch_icon.assert_not_called()
    assert (output_dir / "existing.png").read_bytes() == normalized


def test_normalize_existing_reports_corrupt_assets_and_continues(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text(
        "catalog_servers:\n" "  - id: corrupt\n" "    url: https://corrupt.example/mcp\n" "  - id: valid\n" "    url: https://valid.example/mcp\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "icons"
    output_dir.mkdir()
    (output_dir / "corrupt.png").write_bytes(b"not a PNG")
    Image.new("RGBA", (16, 16), "red").save(output_dir / "valid.png", format="PNG")
    args = Namespace(
        catalog=catalog_path,
        output_dir=output_dir,
        overrides=tmp_path / "overrides.json",
        timeout=1.0,
        force=False,
        normalize_existing=True,
        dry_run=False,
        strict=False,
    )

    with patch("scripts.fetch_catalog_icons._fetch_icon") as fetch_icon:
        assert generate_icons(args) == 0

    output = capsys.readouterr().out
    fetch_icon.assert_not_called()
    assert "MISS corrupt: Image decode failed:" in output
    assert "NORMALIZE valid:" in output
    assert _has_normalized_icon_bounds((output_dir / "valid.png").read_bytes()) is True

    args.strict = True
    assert generate_icons(args) == 1


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


def test_icon_fetch_pins_validated_address_and_preserves_hostname_for_tls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")

    resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with patch("scripts.fetch_catalog_icons.socket.getaddrinfo", return_value=resolved) as getaddrinfo:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = _fetch(client, "https://catalog.example/logo.png", expected_image=True)

    assert result.url == "https://catalog.example/logo.png"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "catalog.example"
    assert request.extensions["sni_hostname"] == "catalog.example"
    getaddrinfo.assert_called_once_with("catalog.example", 443, type=socket.SOCK_STREAM)


def test_icon_fetch_revalidates_each_redirect_before_connecting() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://internal.example/logo.png"})

    def resolve(host: str, *_: object, **__: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        address = "93.184.216.34" if host == "catalog.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    with patch("scripts.fetch_catalog_icons.socket.getaddrinfo", side_effect=resolve):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(IconFetchError, match="Private or special-purpose"):
                _fetch(client, "https://catalog.example/logo.png", expected_image=True)

    assert len(requests) == 1


def test_icon_generation_disables_environment_proxies(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("catalog_servers: []\n", encoding="utf-8")
    args = Namespace(
        catalog=catalog_path,
        output_dir=tmp_path / "icons",
        overrides=tmp_path / "overrides.json",
        timeout=1.0,
        force=False,
        normalize_existing=False,
        dry_run=False,
        strict=False,
    )

    with patch("scripts.fetch_catalog_icons.httpx.Client") as client_class:
        assert generate_icons(args) == 0

    assert client_class.call_args.kwargs["trust_env"] is False


def test_icon_refresh_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--force", "--normalize-existing"])
