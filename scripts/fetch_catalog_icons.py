#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch and bundle MCP catalog icons for local, air-gapped serving.

This maintainer-side tool runs before release. Gateway requests never fetch
remote icons. Remote content becomes inert, normalized PNG assets.
"""

# Future
from __future__ import annotations

# Standard
import argparse
from collections import Counter, deque
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import re
import socket
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

# Third-Party
import httpx
from PIL import Image, ImageOps, PngImagePlugin
import yaml

try:
    # Third-Party
    import tldextract
except ImportError:  # pragma: no cover - installed by the maintainer dev group.
    tldextract = None  # type: ignore[assignment]


DEFAULT_CATALOG = Path("mcp-catalog.yml")
DEFAULT_OUTPUT_DIR = Path("mcpgateway/static/catalog-icons")
DEFAULT_OVERRIDES = Path("scripts/catalog_icon_overrides.json")
LOCAL_PREFIX = "/static/catalog-icons/"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ICON_SIZE = 128
MAX_UPSCALE_FACTOR = 8.0
NORMALIZED_ICON_MIN_EXTENT = 120
NORMALIZED_ICON_MARKER = "contextforge_normalized"
NORMALIZED_ICON_VERSION = "3"
BACKDROP_STRIPPED_MARKER = "contextforge_backdrop_stripped"
PALE_BACKDROP_FLOOR = 225
PALE_BACKDROP_TOLERANCE = 28
PALE_BACKDROP_MIN_PERIMETER_SHARE = 0.25
PALE_BACKDROP_DRIFT_FLOOR = 185
TIMEOUT_SECONDS = 10.0
USER_AGENT = "ContextForge catalog icon curator/1.0"

_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=()) if tldextract else None
_COMMON_MULTI_LABEL_SUFFIXES = frozenset({"co.uk", "org.uk", "com.au", "co.jp", "co.nz", "com.br", "com.cn", "co.in"})
_ENTRY_RE = re.compile(r"^(?P<indent>\s*)-\s+id:\s*(?P<value>.+?)\s*$")
_FIELD_RE = re.compile(r"^(?P<indent>\s+)(?P<field>[A-Za-z_][A-Za-z0-9_]*):(?:\s|$)")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}


class IconFetchError(RuntimeError):
    """Raised when remote content cannot be safely fetched or decoded."""


@dataclass(frozen=True)
class FetchResult:
    """Fetched response body and metadata."""

    url: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ValidatedDestination:
    """An HTTPS destination whose resolved address passed network checks."""

    url: str
    hostname: str
    host_header: str
    address: str

    @property
    def pinned_url(self) -> str:
        """Return URL that connects to validated address while retaining request path."""
        parsed = urlsplit(self.url)
        address = f"[{self.address}]" if ":" in self.address else self.address
        port = parsed.port
        netloc = address if port is None else f"{address}:{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


class IconLinkParser(HTMLParser):
    """Extract candidate icon links without executing page content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): value for key, value in attrs}
        href = values.get("href")
        rel = {token.lower() for token in (values.get("rel") or "").split()}
        if not href:
            return
        if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
            self.links.append((0, href))
        elif "icon" in rel:
            self.links.append((1, href))


def _registrable_domain(host: str) -> str:
    """Return eTLD+1, with safe host fallback for unusual names."""
    normalized = host.rstrip(".").lower()
    if _EXTRACTOR:
        extracted = _EXTRACTOR(normalized)
        return extracted.top_domain_under_public_suffix or normalized
    labels = normalized.split(".")
    suffix_size = 2 if ".".join(labels[-2:]) in _COMMON_MULTI_LABEL_SUFFIXES else 1
    return ".".join(labels[-(suffix_size + 1) :]) if len(labels) > suffix_size else normalized


def _safe_asset_id(catalog_id: str) -> str:
    """Convert catalog id to deterministic, path-safe filename component."""
    safe = _SAFE_ID_RE.sub("-", catalog_id).strip(".-")
    if not safe:
        raise ValueError(f"Catalog id has no safe filename form: {catalog_id!r}")
    return safe


def _validate_public_https_url(url: str) -> ValidatedDestination:
    """Validate an HTTPS URL and retain an address for the subsequent connection."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise IconFetchError(f"Only HTTPS URLs with host are allowed: {url}")
    if parsed.username or parsed.password:
        raise IconFetchError(f"Credentials in icon URL are not allowed: {url}")

    try:
        port = parsed.port or 443
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)))
    except (OSError, ValueError) as exc:
        raise IconFetchError(f"Could not resolve icon host {parsed.hostname}: {exc}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise IconFetchError(f"Private or special-purpose icon host rejected: {parsed.hostname}")
    if not addresses:
        raise IconFetchError(f"Could not resolve icon host {parsed.hostname}")
    return ValidatedDestination(url=url, hostname=parsed.hostname, host_header=parsed.netloc, address=addresses[0])


def _read_response(response: httpx.Response) -> bytes:
    """Read response body with hard size limit."""
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise IconFetchError(f"Response exceeds {MAX_RESPONSE_BYTES} bytes: {response.url}")
    return bytes(body)


def _fetch(client: httpx.Client, url: str, *, expected_image: bool = False) -> FetchResult:
    """Fetch URL with bounded redirects, body size, and content checks."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        destination = _validate_public_https_url(current)
        request = client.build_request("GET", destination.pinned_url, headers={"host": destination.host_header})
        request.extensions["sni_hostname"] = destination.hostname
        try:
            response = client.send(request, stream=True, follow_redirects=False)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise IconFetchError(f"Redirect has no location: {current}")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise IconFetchError(f"HTTP {response.status_code}: {current}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if expected_image and content_type not in _IMAGE_TYPES:
                    raise IconFetchError(f"Unsupported icon content type {content_type!r}: {current}")
                return FetchResult(url=current, content_type=content_type, body=_read_response(response))
            finally:
                response.close()
        except httpx.HTTPError as exc:
            raise IconFetchError(f"HTTP request failed for {current}: {exc}") from exc
    raise IconFetchError(f"Too many redirects: {url}")


def _strip_pale_backdrop(image: Image.Image) -> Image.Image:
    """Remove a near-white badge (circle or square) enclosing a smaller brand mark.

    Only triggers when the perimeter of the cropped content is dominated by a pale
    color; a saturated or dark backdrop (a deliberate brand-color block, e.g. a
    logo's own colored square) is left untouched, since removing it would strip
    the icon's visual weight rather than excess padding. Any strip that would
    leave nothing visible reverts to the original image. Catalog ids must be
    explicitly opted in via the `strip_pale_backdrop` override list: automatic,
    unreviewed detection risks trimming a genuine white design element (e.g. a
    logo's own white face), not just padding.
    """
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image
    cropped = image.crop(bbox)
    width, height = cropped.size
    pixels = cropped.load()
    perimeter = {(x, 0) for x in range(width)} | {(x, height - 1) for x in range(width)} | {(0, y) for y in range(height)} | {(width - 1, y) for y in range(height)}

    def quantize(channels: tuple[int, int, int]) -> tuple[int, int, int]:
        return tuple(channel // 8 * 8 for channel in channels)  # type: ignore[return-value]

    border_colors = Counter(quantize(pixels[x, y][:3]) for x, y in perimeter if pixels[x, y][3] >= 10)
    if not border_colors:
        return image
    backdrop, count = border_colors.most_common(1)[0]
    if count / len(perimeter) < PALE_BACKDROP_MIN_PERIMETER_SHARE or min(backdrop) < PALE_BACKDROP_FLOOR:
        return image

    # A vignette or gradient backdrop (common on GitHub org avatars) can drift far
    # enough from the dominant perimeter color that matching against one fixed
    # reference stops mid-sweep, leaving disconnected pale islands behind. Each
    # queued cell instead carries the color of the opaque neighbor that reached
    # it, so the sweep can follow a smooth gradient inward; an absolute floor
    # still stops it from wandering into real (non-pale) content.
    def local_reference(pixel: tuple[int, int, int, int], fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b, a = pixel
        return (r, g, b) if a >= 10 else fallback

    def is_backdrop(pixel: tuple[int, int, int, int], reference: tuple[int, int, int]) -> bool:
        r, g, b, a = pixel
        if a < 10:
            return True
        if min(r, g, b) < PALE_BACKDROP_DRIFT_FLOOR:
            return False
        return all(abs(channel - target) <= PALE_BACKDROP_TOLERANCE for channel, target in zip((r, g, b), reference))

    visited = bytearray(width * height)
    # Seed every perimeter cell with the detected majority backdrop, not its own
    # color: seeding an opaque cell with itself made the tolerance check in
    # is_backdrop() compare the pixel to itself, so any sufficiently light
    # perimeter pixel passed regardless of hue. Propagation below still hands
    # each confirmed cell's own color to its neighbors, preserving gradient
    # tracking.
    queue = deque((x, y, backdrop) for x, y in perimeter)
    while queue:
        x, y, reference = queue.popleft()
        if not (0 <= x < width and 0 <= y < height):
            continue
        index = y * width + x
        if visited[index]:
            continue
        pixel = pixels[x, y]
        if not is_backdrop(pixel, reference):
            continue
        visited[index] = 1
        next_reference = local_reference(pixel, reference)
        queue.extend(((x - 1, y, next_reference), (x + 1, y, next_reference), (x, y - 1, next_reference), (x, y + 1, next_reference)))

    trimmed = cropped.copy()
    trimmed_pixels = trimmed.load()
    remaining = False
    for y in range(height):
        for x in range(width):
            if visited[y * width + x]:
                r, g, b, _ = trimmed_pixels[x, y]
                trimmed_pixels[x, y] = (r, g, b, 0)
            elif trimmed_pixels[x, y][3] >= 10:
                remaining = True
    if not remaining:
        return image

    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(trimmed, (bbox[0], bbox[1]))
    return canvas


def _image_to_png(body: bytes, *, strip_pale_backdrop: bool = False) -> bytes:
    """Decode image, trim transparent padding, and emit a deterministic capped PNG."""
    try:
        with Image.open(BytesIO(body)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            alpha_bounds = image.getchannel("A").getbbox()
            if alpha_bounds is None:
                raise IconFetchError("Image has no visible pixels")
            image = image.crop(alpha_bounds)
            if strip_pale_backdrop:
                image = _strip_pale_backdrop(image)
                alpha_bounds = image.getchannel("A").getbbox()
                if alpha_bounds is None:
                    raise IconFetchError("Image has no visible pixels")
                image = image.crop(alpha_bounds)
            scale = min(ICON_SIZE / max(image.size), MAX_UPSCALE_FACTOR)
            target_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            if image.size != target_size:
                image = image.resize(target_size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
            offset = ((ICON_SIZE - image.width) // 2, (ICON_SIZE - image.height) // 2)
            canvas.alpha_composite(image, offset)
            output = BytesIO()
            png_info = PngImagePlugin.PngInfo()
            png_info.add_text(NORMALIZED_ICON_MARKER, NORMALIZED_ICON_VERSION)
            if strip_pale_backdrop:
                # Records that this exact asset has already had the pale-backdrop
                # sweep applied, so a later --normalize-existing run can trust it
                # even though its catalog id stays on the strip_pale_backdrop
                # allowlist (needed for ids newly added to that list, whose
                # existing asset was never actually stripped).
                png_info.add_text(BACKDROP_STRIPPED_MARKER, "1")
            canvas.save(output, format="PNG", optimize=True, pnginfo=png_info)
            return output.getvalue()
    except IconFetchError:
        raise
    except Exception as exc:  # Pillow raises several format-specific exceptions.
        raise IconFetchError(f"Image decode failed: {exc}") from exc


def _has_backdrop_stripped_marker(body: bytes) -> bool:
    """Return whether this exact asset already had the pale-backdrop sweep applied."""
    try:
        with Image.open(BytesIO(body)) as source:
            return source.info.get(BACKDROP_STRIPPED_MARKER) == "1"
    except Exception:  # Pillow raises several format-specific exceptions.
        return False


def _has_normalized_icon_bounds(body: bytes) -> bool:
    """Return whether existing asset was normalized or already fills its canvas."""
    try:
        with Image.open(BytesIO(body)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            if image.size != (ICON_SIZE, ICON_SIZE):
                return False
            # PNG text must survive external processing to retain this fast path.
            # Without it, the geometry fallback can apply one additional capped resize.
            # The version guards against re-trusting assets normalized under a
            # since-changed MAX_UPSCALE_FACTOR; bump it whenever that cap changes.
            if image.info.get(NORMALIZED_ICON_MARKER) == NORMALIZED_ICON_VERSION:
                return True
            alpha_bounds = image.getchannel("A").getbbox()
            if alpha_bounds is None:
                raise IconFetchError("Image has no visible pixels")
            left, top, right, bottom = alpha_bounds
            return max(right - left, bottom - top) >= NORMALIZED_ICON_MIN_EXTENT
    except IconFetchError:
        raise
    except Exception as exc:  # Pillow raises several format-specific exceptions.
        raise IconFetchError(f"Image decode failed: {exc}") from exc


def _icon_candidates(page: FetchResult | None, origin: str, domain: str) -> Iterable[str]:
    """Yield candidates in preferred order, with duplicate suppression."""
    seen: set[str] = set()
    if page and page.content_type in {"text/html", "application/xhtml+xml"}:
        parser = IconLinkParser()
        parser.feed(page.body.decode("utf-8", errors="replace"))
        for _, href in sorted(parser.links):
            candidate = urljoin(page.url, href)
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    for candidate in (urljoin(origin, "/favicon.ico"), f"https://icons.duckduckgo.com/ip3/{domain}.ico"):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _load_overrides(path: Path) -> tuple[set[str], dict[str, str], set[str]]:
    """Load optional skip, explicit source, and pale-backdrop-strip overrides."""
    if not path.exists():
        return set(), {}, set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("skip", [])), dict(data.get("overrides", {})), set(data.get("strip_pale_backdrop", []))


def _fetch_icon(client: httpx.Client, server: dict[str, Any], override: str | None = None, *, strip_pale_backdrop: bool = False) -> tuple[bytes, str]:
    """Resolve and normalize one catalog icon."""
    if override:
        result = _fetch(client, override, expected_image=True)
        return _image_to_png(result.body, strip_pale_backdrop=strip_pale_backdrop), result.url

    endpoint = str(server["url"])
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise IconFetchError("Catalog endpoint is not a public HTTPS URL")
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    domain = _registrable_domain(parsed.hostname)
    page: FetchResult | None = None
    try:
        page = _fetch(client, origin)
        landed_hostname = urlsplit(page.url).hostname
        if not landed_hostname or _registrable_domain(landed_hostname) != domain:
            # A redirect landed on an unrelated site (e.g. an API host redirecting
            # to its GitHub repo); that page's <link rel="icon"> belongs to the
            # OTHER site's brand, not this catalog entry's, so it must not be
            # trusted as a candidate source. Fall through to the domain-anchored
            # favicon.ico / DuckDuckGo lookups below instead.
            page = None
    except IconFetchError:
        pass

    last_error: IconFetchError | None = None
    for candidate in _icon_candidates(page, origin, domain):
        try:
            result = _fetch(client, candidate, expected_image=True)
            return _image_to_png(result.body, strip_pale_backdrop=strip_pale_backdrop), result.url
        except IconFetchError as exc:
            last_error = exc
    raise last_error or IconFetchError("No icon candidate succeeded")


def _catalog_entries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and return catalog server mappings."""
    entries = catalog.get("catalog_servers")
    if not isinstance(entries, list):
        raise ValueError("catalog_servers must be a list")
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("url"):
            raise ValueError("Every catalog entry needs id and url")
        result.append(entry)
    return result


def _set_logo_urls(text: str, logo_urls: dict[str, str]) -> str:
    """Update logo_url fields while preserving YAML comments and ordering."""
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if _ENTRY_RE.match(line)]
    starts.append(len(lines))
    updates: list[tuple[int, int, str]] = []
    for start, end in zip(starts, starts[1:]):
        match = _ENTRY_RE.match(lines[start])
        if not match:
            continue
        catalog_id = yaml.safe_load(f"id: {match.group('value')}")["id"]
        if catalog_id not in logo_urls:
            continue
        replacement = f'{match.group("indent")}  logo_url: "{logo_urls[catalog_id]}"\n'
        field_index = next(
            (index for index in range(start + 1, end) if _FIELD_RE.match(lines[index]) and _FIELD_RE.match(lines[index]).group("field") == "logo_url"),
            None,
        )
        if field_index is not None:
            updates.append((field_index, field_index + 1, replacement))
            continue
        url_index = next(
            (index for index in range(start + 1, end) if _FIELD_RE.match(lines[index]) and _FIELD_RE.match(lines[index]).group("field") == "url"),
            None,
        )
        if url_index is None:
            raise ValueError(f"Catalog entry has no url field: {catalog_id}")
        updates.append((url_index + 1, url_index + 1, replacement))

    for start, end, replacement in reversed(updates):
        lines[start:end] = [replacement]
    return "".join(lines)


def generate_icons(args: argparse.Namespace) -> int:
    """Generate assets and update catalog; return process status."""
    catalog_path = args.catalog
    catalog_text = catalog_path.read_text(encoding="utf-8")
    catalog = yaml.safe_load(catalog_text) or {}
    entries = _catalog_entries(catalog)
    skip_ids, overrides, strip_backdrop_ids = _load_overrides(args.overrides)
    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    logo_urls: dict[str, str] = {}
    misses: list[str] = []

    with httpx.Client(headers={"user-agent": USER_AGENT}, timeout=args.timeout, trust_env=False) as client:
        for server in entries:
            catalog_id = str(server["id"])
            asset_name = f"{_safe_asset_id(catalog_id)}.png"
            asset_path = args.output_dir / asset_name
            local_url = f"{LOCAL_PREFIX}{asset_name}"
            if catalog_id in skip_ids:
                print(f"SKIP {catalog_id}: override list")
                continue
            strip_pale_backdrop = catalog_id in strip_backdrop_ids
            if args.normalize_existing:
                if not asset_path.exists():
                    print(f"SKIP {catalog_id}: no local asset to normalize")
                    continue
                try:
                    existing = asset_path.read_bytes()
                    # A backdrop-strip candidate may have full alpha bounds (the pale
                    # badge, not the mark, fills the canvas) before it has ever been
                    # stripped, so the geometry fast-path can't be trusted until the
                    # asset itself records that the sweep already ran. Once it does,
                    # trust it like any other id — this also protects manual touch-ups
                    # (padding, size) applied to the asset after stripping from being
                    # silently undone by a later --normalize-existing run.
                    needs_backdrop_strip = strip_pale_backdrop and not _has_backdrop_stripped_marker(existing)
                    if not needs_backdrop_strip and _has_normalized_icon_bounds(existing):
                        print(f"KEEP {catalog_id}: normalized bounds")
                    else:
                        if not args.dry_run:
                            normalized = _image_to_png(existing, strip_pale_backdrop=strip_pale_backdrop)
                            temporary = asset_path.with_suffix(".tmp")
                            temporary.write_bytes(normalized)
                            temporary.replace(asset_path)
                        print(f"NORMALIZE {catalog_id}: {asset_path}")
                    logo_urls[catalog_id] = local_url
                except (IconFetchError, OSError, ValueError) as exc:
                    misses.append(catalog_id)
                    print(f"MISS {catalog_id}: {exc}")
                continue
            if asset_path.exists() and not args.force:
                logo_urls[catalog_id] = local_url
                print(f"KEEP {catalog_id}: {asset_path}")
                continue
            try:
                body, source_url = _fetch_icon(client, server, overrides.get(catalog_id), strip_pale_backdrop=strip_pale_backdrop)
                if not args.dry_run:
                    temporary = asset_path.with_suffix(".tmp")
                    temporary.write_bytes(body)
                    temporary.replace(asset_path)
                    logo_urls[catalog_id] = local_url
                print(f"OK {catalog_id}: {source_url}")
            except (IconFetchError, OSError, ValueError) as exc:
                misses.append(catalog_id)
                print(f"MISS {catalog_id}: {exc}")

    if not args.dry_run and logo_urls:
        catalog_path.write_text(_set_logo_urls(catalog_text, logo_urls), encoding="utf-8")
    print(f"Resolved: {len(logo_urls)}; misses: {len(misses)}")
    if misses:
        print("Placeholder fallback: " + ", ".join(misses))
    return 1 if args.strict and misses else 0


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and bundle MCP catalog icons. Normalization trims transparent padding and upscales source artwork by at most 8x.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    refresh_mode = parser.add_mutually_exclusive_group()
    refresh_mode.add_argument("--force", action="store_true", help="Refresh existing assets")
    refresh_mode.add_argument(
        "--normalize-existing",
        action="store_true",
        help="Trim and resize existing local assets up to 8x without refetching remote icons",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing")
    parser.add_argument("--strict", action="store_true", help="Return failure when any icon is unresolved")
    return parser.parse_args(args)


if __name__ == "__main__":
    raise SystemExit(generate_icons(_parse_args()))
