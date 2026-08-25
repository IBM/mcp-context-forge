#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch and bundle MCP catalog icons for local, air-gapped serving.

This maintainer-side tool runs before release. Gateway requests never fetch
remote icons. Remote content becomes inert, normalized PNG assets.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, ImageOps
import yaml

try:
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


def _validate_public_https_url(url: str) -> None:
    """Reject non-HTTPS and private-network destinations before fetching."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise IconFetchError(f"Only HTTPS URLs with host are allowed: {url}")
    if parsed.username or parsed.password:
        raise IconFetchError(f"Credentials in icon URL are not allowed: {url}")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise IconFetchError(f"Could not resolve icon host {parsed.hostname}: {exc}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise IconFetchError(f"Private or special-purpose icon host rejected: {parsed.hostname}")


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
        _validate_public_https_url(current)
        try:
            with client.stream("GET", current, follow_redirects=False) as response:
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
        except httpx.HTTPError as exc:
            raise IconFetchError(f"HTTP request failed for {current}: {exc}") from exc
    raise IconFetchError(f"Too many redirects: {url}")


def _image_to_png(body: bytes) -> bytes:
    """Decode image and emit deterministic transparent 128x128 PNG."""
    try:
        with Image.open(BytesIO(body)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
            offset = ((ICON_SIZE - image.width) // 2, (ICON_SIZE - image.height) // 2)
            canvas.alpha_composite(image, offset)
            output = BytesIO()
            canvas.save(output, format="PNG", optimize=True)
            return output.getvalue()
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


def _load_overrides(path: Path) -> tuple[set[str], dict[str, str]]:
    """Load optional skip and explicit source overrides."""
    if not path.exists():
        return set(), {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("skip", [])), dict(data.get("overrides", {}))


def _fetch_icon(client: httpx.Client, server: dict[str, Any], override: str | None = None) -> tuple[bytes, str]:
    """Resolve and normalize one catalog icon."""
    if override:
        result = _fetch(client, override, expected_image=True)
        return _image_to_png(result.body), result.url

    endpoint = str(server["url"])
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise IconFetchError("Catalog endpoint is not a public HTTPS URL")
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    domain = _registrable_domain(parsed.hostname)
    page: FetchResult | None = None
    try:
        page = _fetch(client, origin)
    except IconFetchError:
        pass

    last_error: IconFetchError | None = None
    for candidate in _icon_candidates(page, origin, domain):
        try:
            result = _fetch(client, candidate, expected_image=True)
            return _image_to_png(result.body), result.url
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
            (
                index
                for index in range(start + 1, end)
                if _FIELD_RE.match(lines[index]) and _FIELD_RE.match(lines[index]).group("field") == "logo_url"
            ),
            None,
        )
        if field_index is not None:
            updates.append((field_index, field_index + 1, replacement))
            continue
        url_index = next(
            (
                index
                for index in range(start + 1, end)
                if _FIELD_RE.match(lines[index]) and _FIELD_RE.match(lines[index]).group("field") == "url"
            ),
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
    skip_ids, overrides = _load_overrides(args.overrides)
    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    logo_urls: dict[str, str] = {}
    misses: list[str] = []

    with httpx.Client(headers={"user-agent": USER_AGENT}, timeout=args.timeout) as client:
        for server in entries:
            catalog_id = str(server["id"])
            asset_name = f"{_safe_asset_id(catalog_id)}.png"
            asset_path = args.output_dir / asset_name
            local_url = f"{LOCAL_PREFIX}{asset_name}"
            if catalog_id in skip_ids:
                print(f"SKIP {catalog_id}: override list")
                continue
            if asset_path.exists() and not args.force:
                logo_urls[catalog_id] = local_url
                print(f"KEEP {catalog_id}: {asset_path}")
                continue
            try:
                body, source_url = _fetch_icon(client, server, overrides.get(catalog_id))
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    parser.add_argument("--force", action="store_true", help="Refresh existing assets")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing")
    parser.add_argument("--strict", action="store_true", help="Return failure when any icon is unresolved")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(generate_icons(_parse_args()))
