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
from PIL import Image, PngImagePlugin
import pytest
import yaml

# Local
from scripts.fetch_catalog_icons import (
    _fetch,
    _fetch_icon,
    _has_normalized_icon_bounds,
    _image_to_png,
    _parse_args,
    _registrable_domain,
    _safe_asset_id,
    _set_logo_urls,
    _strip_pale_backdrop,
    _validate_public_https_url,
    BACKDROP_STRIPPED_MARKER,
    generate_icons,
    IconFetchError,
    IconLinkParser,
    NORMALIZED_ICON_MARKER,
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

    # Cropped 16x16 content upscales (capped at 8x) to fill the 128px canvas,
    # so trimmed padding no longer leaves the icon visually smaller than peers.
    assert normalized.getchannel("A").getbbox() == (0, 0, 128, 128)


def test_image_to_png_caps_upscale_and_marks_result() -> None:
    source = Image.new("RGBA", (16, 8), "red")
    raw = BytesIO()
    source.save(raw, format="PNG")

    normalized_bytes = _image_to_png(raw.getvalue())
    normalized = Image.open(BytesIO(normalized_bytes))

    assert normalized.getchannel("A").getbbox() == (0, 32, 128, 96)
    assert _has_normalized_icon_bounds(normalized_bytes) is True
    with Image.open(BytesIO(normalized_bytes)) as decoded:
        assert decoded.info.get(NORMALIZED_ICON_MARKER) == "3"


def test_strip_pale_backdrop_removes_white_badge_around_smaller_mark() -> None:
    source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    # A pale circle "badge" filling the canvas, with a small colored mark in the center.
    source.paste(Image.new("RGBA", (128, 128), (250, 250, 250, 255)), (0, 0))
    source.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))

    stripped = _strip_pale_backdrop(source)

    bbox = stripped.getchannel("A").getbbox()
    assert bbox == (52, 52, 76, 76)
    assert stripped.getpixel((0, 0))[3] == 0
    assert stripped.getpixel((60, 60)) == (30, 120, 220, 255)


def test_strip_pale_backdrop_leaves_saturated_badge_untouched() -> None:
    """A deliberate brand-color block (not padding) must not be stripped."""
    source = Image.new("RGBA", (128, 128), (10, 20, 200, 255))
    source.paste(Image.new("RGBA", (24, 24), (255, 255, 255, 255)), (52, 52))

    stripped = _strip_pale_backdrop(source)

    assert stripped.getchannel("A").getbbox() == (0, 0, 128, 128)
    assert stripped.getpixel((0, 0)) == (10, 20, 200, 255)


def test_strip_pale_backdrop_leaves_off_hue_corner_accent_untouched() -> None:
    """A light but distinctly-hued corner accent must not match the white majority.

    Seeding a perimeter cell's match reference with its own color would make the
    tolerance check compare that pixel to itself, letting any sufficiently light
    pixel pass regardless of hue.
    """
    source = Image.new("RGBA", (128, 128), (250, 250, 250, 255))
    source.paste(Image.new("RGBA", (20, 20), (255, 200, 220, 255)), (0, 0))
    source.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))

    stripped = _strip_pale_backdrop(source)

    assert stripped.getpixel((5, 5)) == (255, 200, 220, 255)
    assert stripped.getpixel((100, 5))[3] == 0
    assert stripped.getpixel((60, 60)) == (30, 120, 220, 255)


def test_strip_pale_backdrop_reverts_when_result_would_be_blank() -> None:
    source = Image.new("RGBA", (128, 128), (250, 250, 250, 255))

    stripped = _strip_pale_backdrop(source)

    assert stripped.getchannel("A").getbbox() == (0, 0, 128, 128)


def test_strip_pale_backdrop_follows_a_vignette_gradient() -> None:
    """A GitHub-avatar-style vignette (top corners near-white, bottom corners

    noticeably darker) must not leave disconnected pale islands behind: a
    fixed-reference match stops mid-sweep once the drift exceeds tolerance,
    but the sweep must track the gradient locally instead.
    """
    source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    top, bottom = 254, 217
    for y in range(128):
        shade = round(top + (bottom - top) * (y / 127))
        for x in range(128):
            source.putpixel((x, y), (shade, shade, shade, 255))
    source.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))

    stripped = _strip_pale_backdrop(source)

    assert stripped.getpixel((0, 0))[3] == 0
    assert stripped.getpixel((0, 127))[3] == 0
    assert stripped.getpixel((127, 127))[3] == 0
    assert stripped.getpixel((60, 60)) == (30, 120, 220, 255)


def test_image_to_png_strips_pale_backdrop_only_when_requested() -> None:
    source = Image.new("RGBA", (128, 128), (250, 250, 250, 255))
    source.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))
    raw = BytesIO()
    source.save(raw, format="PNG")

    untouched = Image.open(BytesIO(_image_to_png(raw.getvalue())))
    assert untouched.getchannel("A").getbbox() == (0, 0, 128, 128)

    stripped = Image.open(BytesIO(_image_to_png(raw.getvalue(), strip_pale_backdrop=True)))
    # The 24x24 mark upscales (capped at 8x) to fill the canvas once the badge is gone.
    assert stripped.getchannel("A").getbbox() == (0, 0, 128, 128)
    assert stripped.getpixel((64, 64)) == (30, 120, 220, 255)


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


def test_normalize_existing_upgrades_assets_marked_by_older_cap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Assets normalized under a lower MAX_UPSCALE_FACTOR must be revisited, not trusted forever."""
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("catalog_servers:\n  - id: legacy\n    url: https://legacy.example/mcp\n", encoding="utf-8")
    output_dir = tmp_path / "icons"
    output_dir.mkdir()

    legacy = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    legacy.paste(Image.new("RGBA", (32, 32), "red"), (48, 48))
    raw = BytesIO()
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text(NORMALIZED_ICON_MARKER, "1")
    legacy.save(raw, format="PNG", pnginfo=png_info)
    (output_dir / "legacy.png").write_bytes(raw.getvalue())

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

    assert generate_icons(args) == 0
    output = capsys.readouterr().out
    assert "NORMALIZE legacy:" in output

    upgraded_bytes = (output_dir / "legacy.png").read_bytes()
    with Image.open(BytesIO(upgraded_bytes)) as upgraded:
        assert upgraded.getchannel("A").getbbox() == (0, 0, 128, 128)
        assert upgraded.info.get(NORMALIZED_ICON_MARKER) == "3"


def test_normalize_existing_forces_reprocessing_for_strip_backdrop_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A pale-backdrop candidate can already have full alpha bounds (the badge fills the

    canvas, not the mark), so the geometry fast-path must not skip it.
    """
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("catalog_servers:\n  - id: badged\n    url: https://badged.example/mcp\n", encoding="utf-8")
    output_dir = tmp_path / "icons"
    output_dir.mkdir()

    badged = Image.new("RGBA", (128, 128), (250, 250, 250, 255))
    badged.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))
    raw = BytesIO()
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text(NORMALIZED_ICON_MARKER, "3")
    badged.save(raw, format="PNG", pnginfo=png_info)
    (output_dir / "badged.png").write_bytes(raw.getvalue())
    assert _has_normalized_icon_bounds(raw.getvalue()) is True

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text('{"strip_pale_backdrop": ["badged"]}', encoding="utf-8")
    args = Namespace(
        catalog=catalog_path,
        output_dir=output_dir,
        overrides=overrides_path,
        timeout=1.0,
        force=False,
        normalize_existing=True,
        dry_run=False,
        strict=False,
    )

    assert generate_icons(args) == 0
    output = capsys.readouterr().out
    assert "NORMALIZE badged:" in output

    with Image.open(output_dir / "badged.png") as result:
        rgba = result.convert("RGBA")
        # The badge is gone and the mark now fills the canvas (128/24 upscale < the 8x cap).
        assert rgba.getpixel((0, 0))[:3] == (30, 120, 220)
        assert rgba.getpixel((64, 64))[:3] == (30, 120, 220)


def test_normalize_existing_trusts_an_already_stripped_backdrop_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Once an asset records that the backdrop sweep already ran, a later

    --normalize-existing run must not reprocess it just because its catalog id
    stays on the strip_pale_backdrop allowlist — that would silently undo a
    manual touch-up (padding, size) applied to the asset afterward.
    """
    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text("catalog_servers:\n  - id: badged\n    url: https://badged.example/mcp\n", encoding="utf-8")
    output_dir = tmp_path / "icons"
    output_dir.mkdir()

    # Padded well below the 8x-cap fill a fresh strip+upscale would produce;
    # if this got reprocessed, the mark would end up filling the canvas.
    stripped = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    stripped.paste(Image.new("RGBA", (24, 24), (30, 120, 220, 255)), (52, 52))
    raw = BytesIO()
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text(NORMALIZED_ICON_MARKER, "3")
    png_info.add_text(BACKDROP_STRIPPED_MARKER, "1")
    stripped.save(raw, format="PNG", pnginfo=png_info)
    (output_dir / "badged.png").write_bytes(raw.getvalue())

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text('{"strip_pale_backdrop": ["badged"]}', encoding="utf-8")
    args = Namespace(
        catalog=catalog_path,
        output_dir=output_dir,
        overrides=overrides_path,
        timeout=1.0,
        force=False,
        normalize_existing=True,
        dry_run=False,
        strict=False,
    )

    assert generate_icons(args) == 0
    output = capsys.readouterr().out
    assert "KEEP badged:" in output

    assert (output_dir / "badged.png").read_bytes() == raw.getvalue()


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


def test_fetch_icon_ignores_link_tags_from_off_domain_redirect() -> None:
    """A homepage redirect to an unrelated site (e.g. an API host redirecting to

    its GitHub repo) must not donate that other site's <link rel="icon"> as
    this catalog entry's icon; the domain-anchored favicon.ico must win instead.
    """
    icon = Image.new("RGBA", (32, 32), "red")
    icon_bytes = BytesIO()
    icon.save(icon_bytes, format="PNG")

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        path = request.url.path
        if host == "mcp.example.com" and path == "/":
            return httpx.Response(302, headers={"location": "https://other-site.example/repo"})
        if host == "other-site.example" and path == "/repo":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b'<link rel="icon" href="/wrong-icon.png">')
        if host == "mcp.example.com" and path == "/favicon.ico":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=icon_bytes.getvalue())
        raise AssertionError(f"unexpected request: host={host} path={path}")

    def resolve(host: str, *_: object, **__: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    with patch("scripts.fetch_catalog_icons.socket.getaddrinfo", side_effect=resolve):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            _body, source_url = _fetch_icon(client, {"id": "example", "url": "https://mcp.example.com/sse"})

    assert source_url == "https://mcp.example.com/favicon.ico"


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
