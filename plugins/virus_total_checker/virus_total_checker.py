# -*- coding: utf-8 -*-
"""Location: ./plugins/virus_total_checker/virus_total_checker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

VirusTotal URL Checker Plugin.
Integrates with VirusTotal API v3 to evaluate URLs, domains, and IP
addresses before fetching resources. Optionally submits unknown URLs for
analysis and waits briefly for results. Caches lookups in-memory to reduce
latency.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

# Third-Party
import httpx
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPosthookPayload,
    PromptPosthookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.utils.retry_manager import ResilientHttpClient


class VirusTotalConfig(BaseModel):
    """Configuration for VirusTotal URL/file checking plugin.

    Attributes:
        enabled: Enable VirusTotal checks.
        api_key_env: Environment variable name for VirusTotal API key.
        base_url: Base URL for VirusTotal API.
        timeout_seconds: Request timeout in seconds.
        check_url: Enable URL reputation checks.
        check_domain: Enable domain reputation checks.
        check_ip: Enable IP address reputation checks.
        scan_if_unknown: Submit unknown URLs for analysis.
        wait_for_analysis: Poll for analysis completion.
        max_wait_seconds: Maximum time to wait for analysis.
        poll_interval_seconds: Polling interval for analysis status.
        block_on_verdicts: List of verdicts that trigger blocking.
        min_malicious: Minimum malicious engine count to block.
        cache_ttl_seconds: Cache TTL in seconds.
        max_retries: Maximum retry attempts for HTTP requests.
        base_backoff: Base backoff delay for retries.
        max_delay: Maximum backoff delay.
        jitter_max: Maximum jitter for backoff.
        enable_file_checks: Enable file reputation checks.
        file_hash_alg: Hash algorithm for files (sha256/md5/sha1).
        upload_if_unknown: Upload unknown files for analysis.
        upload_max_bytes: Maximum file size for upload.
        scan_tool_outputs: Scan URLs in tool outputs.
        max_urls_per_call: Maximum URLs to check per call.
        url_pattern: Regex pattern for URL extraction.
        scan_prompt_outputs: Scan URLs in prompt outputs.
        scan_resource_contents: Scan URLs in resource contents.
        min_harmless_ratio: Minimum harmless ratio required.
        allow_url_patterns: URL patterns to allow.
        deny_url_patterns: URL patterns to deny.
        allow_domains: Domains to allow.
        deny_domains: Domains to deny.
        allow_ip_cidrs: IP CIDR ranges to allow.
        deny_ip_cidrs: IP CIDR ranges to deny.
        override_precedence: Override precedence (deny_over_allow/allow_over_deny).
    """

    enabled: bool = Field(default=True, description="Enable VirusTotal checks")
    api_key_env: str = Field(default="VT_API_KEY", description="Env var name for VirusTotal API key")
    base_url: str = Field(default="https://www.virustotal.com/api/v3")
    timeout_seconds: float = Field(default=8.0)

    check_url: bool = Field(default=True)
    check_domain: bool = Field(default=True)
    check_ip: bool = Field(default=True)

    # Behavior when resource unknown
    scan_if_unknown: bool = Field(default=False, description="Submit URL for scan when unknown")
    wait_for_analysis: bool = Field(default=False, description="Poll briefly for analysis completion")
    max_wait_seconds: int = Field(default=8)
    poll_interval_seconds: float = Field(default=1.0)

    # Blocking policy
    block_on_verdicts: list[str] = Field(default_factory=lambda: ["malicious"])  # malicious|suspicious|harmless|undetected|timeout
    min_malicious: int = Field(default=1, ge=0, description="Min malicious engines to block")

    # Simple in-memory cache
    cache_ttl_seconds: int = Field(default=300)

    # Retry config (ResilientHttpClient)
    max_retries: int = Field(default=3)
    base_backoff: float = Field(default=0.5)
    max_delay: float = Field(default=8.0)
    jitter_max: float = Field(default=0.2)

    # File reputation settings
    enable_file_checks: bool = Field(default=True)
    file_hash_alg: str = Field(default="sha256")  # sha256|md5|sha1
    upload_if_unknown: bool = Field(default=False)
    upload_max_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB default

    # Scan URLs in tool outputs
    scan_tool_outputs: bool = Field(default=True)
    max_urls_per_call: int = Field(default=5, ge=0)
    url_pattern: str = Field(default=r"https?://[\w\-\._~:/%#\[\]@!\$&'\(\)\*\+,;=]+")

    # Scan URLs in prompts and resource contents
    scan_prompt_outputs: bool = Field(default=True)
    scan_resource_contents: bool = Field(default=True)

    # Policy extras
    min_harmless_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Require harmless/(total) >= ratio; 0 disables")

    # Local overrides
    allow_url_patterns: list[str] = Field(default_factory=list)
    deny_url_patterns: list[str] = Field(default_factory=list)
    allow_domains: list[str] = Field(default_factory=list)
    deny_domains: list[str] = Field(default_factory=list)
    allow_ip_cidrs: list[str] = Field(default_factory=list)
    deny_ip_cidrs: list[str] = Field(default_factory=list)
    override_precedence: str = Field(default="deny_over_allow", description="deny_over_allow | allow_over_deny")


_CACHE: Dict[str, tuple[float, dict[str, Any]]] = {}


def _get_api_key(cfg: VirusTotalConfig) -> Optional[str]:
    """Get VirusTotal API key from environment.

    Args:
        cfg: VirusTotal configuration.

    Returns:
        API key string or None if not found.
    """
    return os.getenv(cfg.api_key_env)


def _b64_url_id(url: str) -> str:
    """Generate VirusTotal URL identifier from URL.

    Args:
        url: URL to encode.

    Returns:
        Base64 URL-safe encoded identifier without padding.
    """
    raw = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
    return raw.strip("=")


def _compute_file_hash(file_path: str, alg: str) -> str:
    """Compute file hash synchronously (called via asyncio.to_thread).

    Args:
        file_path: Path to file to hash.
        alg: Hash algorithm (sha256, md5, sha1).

    Returns:
        Hex digest of the file hash.
    """
    h = hashlib.new(alg)
    with open(file_path, "rb") as f:  # nosec B108
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _upload_file_sync(
    url: str,
    file_path: str,
    headers: dict[str, str],
    timeout: float,
    max_retries: int = 3,
    base_backoff: float = 0.5,
    max_delay: float = 8.0,
    jitter_max: float = 0.2,
) -> dict[str, Any]:
    """Upload file synchronously with streaming and retry logic (called via asyncio.to_thread).

    Implements exponential backoff with jitter matching ResilientHttpClient semantics.

    Args:
        url: URL to upload to.
        file_path: Path to file to upload.
        headers: HTTP headers including API key.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts.
        base_backoff: Base delay in seconds before retrying.
        max_delay: Maximum backoff delay in seconds.
        jitter_max: Maximum jitter to add to backoff.

    Returns:
        JSON response from the upload endpoint.

    Raises:
        httpx.HTTPStatusError: If request fails after all retries.
    """
    import random  # pylint: disable=import-outside-toplevel

    retryable_status_codes = {429, 500, 502, 503, 504}
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            with open(file_path, "rb") as f:  # nosec B108
                files = {"file": (os.path.basename(file_path), f)}
                with httpx.Client(headers=headers, timeout=timeout) as sync_client:
                    resp = sync_client.post(url, files=files)
                    resp.raise_for_status()
                    return resp.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code not in retryable_status_codes:
                raise
            if attempt < max_retries:
                delay = min(base_backoff * (2**attempt), max_delay)
                delay += random.uniform(0, jitter_max)  # nosec B311
                time.sleep(delay)
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(base_backoff * (2**attempt), max_delay)
                delay += random.uniform(0, jitter_max)  # nosec B311
                time.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("Upload failed after retries")


def _from_cache(key: str) -> Optional[dict[str, Any]]:
    """Retrieve cached data if not expired.

    Args:
        key: Cache key.

    Returns:
        Cached data dictionary or None if not found or expired.
    """
    ent = _CACHE.get(key)
    if not ent:
        return None
    expires_at, data = ent
    if time.time() < expires_at:
        return data
    _CACHE.pop(key, None)
    return None


def _to_cache(key: str, data: dict[str, Any], ttl: int) -> None:
    """Store data in cache with TTL.

    Args:
        key: Cache key.
        data: Data to cache.
        ttl: Time-to-live in seconds.
    """
    _CACHE[key] = (time.time() + ttl, data)


async def _http_get(client: ResilientHttpClient, url: str) -> dict[str, Any] | None:
    """Perform HTTP GET request with 404 handling.

    Args:
        client: HTTP client.
        url: URL to fetch.

    Returns:
        JSON response dictionary or None if 404.

    Raises:
        HTTPStatusError: If response status is not 2xx (except 404).
    """
    resp = await client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _should_block(stats: dict[str, Any], cfg: VirusTotalConfig) -> bool:
    """Determine if stats warrant blocking based on configuration.

    Args:
        stats: VirusTotal analysis statistics.
        cfg: Configuration with blocking thresholds.

    Returns:
        True if resource should be blocked, False otherwise.
    """
    # VT stats example: {"harmless": 82, "malicious": 2, "suspicious": 1, "undetected": 12, "timeout": 0}
    malicious = int(stats.get("malicious", 0))
    if malicious >= cfg.min_malicious:
        return True
    for verdict in cfg.block_on_verdicts:
        if int(stats.get(verdict, 0)) > 0 and verdict != "malicious":
            return True
    if cfg.min_harmless_ratio > 0:
        harmless = int(stats.get("harmless", 0))
        total = sum(int(stats.get(k, 0)) for k in ("harmless", "malicious", "suspicious", "undetected", "timeout"))
        if total > 0:
            ratio = harmless / total
            if ratio < cfg.min_harmless_ratio:
                return True
    return False


def _domain_matches(host: str, patterns: list[str]) -> bool:
    """Check if hostname matches any domain pattern.

    Args:
        host: Hostname to check.
        patterns: List of domain patterns to match against.

    Returns:
        True if hostname matches any pattern, False otherwise.
    """
    host = host.lower()
    for p in patterns or []:
        p = p.lower()
        if host == p or host.endswith("." + p):
            return True
    return False


def _url_matches(url: str, patterns: list[str]) -> bool:
    """Check if URL matches any regex pattern.

    Args:
        url: URL to check.
        patterns: List of regex patterns to match against.

    Returns:
        True if URL matches any pattern, False otherwise.
    """
    for pat in patterns or []:
        try:
            if re.search(pat, url):
                return True
        except re.error:
            continue
    return False


def _ip_in_cidrs(ip: str, cidrs: list[str]) -> bool:
    """Check if IP address is in any CIDR range.

    Args:
        ip: IP address string.
        cidrs: List of CIDR ranges.

    Returns:
        True if IP is in any CIDR range, False otherwise.
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
    except Exception:
        return False
    for c in cidrs or []:
        try:
            net = ipaddress.ip_network(c, strict=False)
            if ip_obj in net:
                return True
        except Exception:
            continue
    return False


def _apply_overrides(url: str, host: str | None, cfg: VirusTotalConfig) -> str | None:
    """Return 'deny', 'allow', or None based on local overrides and precedence.

    Args:
        url: The URL to check for overrides.
        host: The host to check for overrides (optional).
        cfg: The VirusTotal configuration.

    Returns:
        str | None: 'deny', 'allow', or None based on overrides. Precedence order is controlled by cfg.override_precedence.
    """
    host_l = (host or "").lower()
    allow = _url_matches(url, cfg.allow_url_patterns) or (host_l and _domain_matches(host_l, cfg.allow_domains)) or (host_l and _ip_in_cidrs(host_l, cfg.allow_ip_cidrs))
    deny = _url_matches(url, cfg.deny_url_patterns) or (host_l and _domain_matches(host_l, cfg.deny_domains)) or (host_l and _ip_in_cidrs(host_l, cfg.deny_ip_cidrs))
    if cfg.override_precedence == "allow_over_deny":
        if allow:
            return "allow"
        if deny:
            return "deny"
        return None
    # default: deny_over_allow
    if deny:
        return "deny"
    if allow:
        return "allow"
    return None


class VirusTotalURLCheckerPlugin(Plugin):
    """Query VirusTotal for URL/domain/IP verdicts and block on policy breaches."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the VirusTotal URL checker plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = VirusTotalConfig(**(config.config or {}))

    def _client_factory(self, cfg: VirusTotalConfig, headers: dict[str, str]) -> ResilientHttpClient:
        """Create HTTP client with retry configuration.

        Args:
            cfg: VirusTotal configuration.
            headers: HTTP headers including API key.

        Returns:
            Configured resilient HTTP client.
        """
        client_args = {"headers": headers, "timeout": cfg.timeout_seconds}
        return ResilientHttpClient(
            max_retries=cfg.max_retries,
            base_backoff=cfg.base_backoff,
            max_delay=cfg.max_delay,
            jitter_max=cfg.jitter_max,
            client_args=client_args,
        )

    async def _check_url(self, client: ResilientHttpClient, url: str, cfg: VirusTotalConfig) -> dict[str, Any] | None:
        """Check URL reputation with VirusTotal, optionally scanning if unknown.

        Args:
            client: HTTP client.
            url: URL to check.
            cfg: VirusTotal configuration.

        Returns:
            VirusTotal API response or None if not found.
        """
        key = f"vt:url:{_b64_url_id(url)}"
        cached = _from_cache(key)
        if cached is not None:
            return cached

        # GET url info
        url_id = _b64_url_id(url)
        info = await _http_get(client, f"{cfg.base_url}/urls/{url_id}")
        if info is None and cfg.scan_if_unknown:
            # Submit for analysis
            resp = await client.post(f"{cfg.base_url}/urls", data={"url": url})
            resp.raise_for_status()
            data = resp.json()
            analysis_id = data.get("data", {}).get("id")
            if cfg.wait_for_analysis and analysis_id:
                deadline = time.time() + cfg.max_wait_seconds
                while time.time() < deadline:
                    a = await _http_get(client, f"{cfg.base_url}/analyses/{analysis_id}")
                    if a and a.get("data", {}).get("attributes", {}).get("status") == "completed":
                        break
                    await asyncio.sleep(cfg.poll_interval_seconds)
                # Re-fetch URL info after analysis
                info = await _http_get(client, f"{cfg.base_url}/urls/{url_id}")

        if info is not None:
            _to_cache(key, info, cfg.cache_ttl_seconds)
        return info

    async def _check_domain(self, client: ResilientHttpClient, domain: str, cfg: VirusTotalConfig) -> dict[str, Any] | None:
        """Check domain reputation with VirusTotal.

        Args:
            client: HTTP client.
            domain: Domain to check.
            cfg: VirusTotal configuration.

        Returns:
            VirusTotal API response or None if not found.
        """
        key = f"vt:domain:{domain}"
        cached = _from_cache(key)
        if cached is not None:
            return cached
        info = await _http_get(client, f"{cfg.base_url}/domains/{domain}")
        if info is not None:
            _to_cache(key, info, cfg.cache_ttl_seconds)
        return info

    async def _check_ip(self, client: ResilientHttpClient, ip: str, cfg: VirusTotalConfig) -> dict[str, Any] | None:
        """Check IP address reputation with VirusTotal.

        Args:
            client: HTTP client.
            ip: IP address to check.
            cfg: VirusTotal configuration.

        Returns:
            VirusTotal API response or None if not found.
        """
        key = f"vt:ip:{ip}"
        cached = _from_cache(key)
        if cached is not None:
            return cached
        info = await _http_get(client, f"{cfg.base_url}/ip_addresses/{ip}")
        if info is not None:
            _to_cache(key, info, cfg.cache_ttl_seconds)
        return info

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:  # noqa: D401
        """Check resource URL/domain/IP/file with VirusTotal before fetching.

        Args:
            payload: Resource pre-fetch payload containing URI.
            context: Plugin execution context.

        Returns:
            Result blocking fetch if reputation check fails, or allowing with metadata.
        """
        cfg = self._cfg
        if not cfg.enabled:
            return ResourcePreFetchResult(continue_processing=True)

        parsed = urlparse(payload.uri)
        host = (parsed.hostname or "").lower()
        scheme = (parsed.scheme or "").lower()
        is_http = scheme in ("http", "https")
        api_key = _get_api_key(cfg)
        if not api_key:
            # No API key: allow but note in metadata
            return ResourcePreFetchResult(metadata={"virustotal": {"skipped": True, "reason": "no_api_key"}})

        # Local overrides first
        if _url_matches(payload.uri, cfg.deny_url_patterns) or (host and _domain_matches(host, cfg.deny_domains)) or (host and _ip_in_cidrs(host, cfg.deny_ip_cidrs)):
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Local denylist match",
                    description=f"Denied by local policy: {payload.uri}",
                    code="VT_LOCAL_DENY",
                    details={"uri": payload.uri, "host": host},
                ),
            )
        if _url_matches(payload.uri, cfg.allow_url_patterns) or (host and _domain_matches(host, cfg.allow_domains)) or (host and _ip_in_cidrs(host, cfg.allow_ip_cidrs)):
            return ResourcePreFetchResult(metadata={"virustotal": {"skipped": True, "reason": "local_allow"}})

        # Cache short-circuit (no HTTP client created)
        vt_meta: dict[str, Any] = {}
        if cfg.check_url and is_http:
            url_id = _b64_url_id(payload.uri)
            cached = _from_cache(f"vt:url:{url_id}")
            if cached:
                attrs = cached.get("data", {}).get("attributes", {})
                stats = attrs.get("last_analysis_stats", {})
                vt_meta["url_stats"] = stats
                if _should_block(stats, cfg):
                    return ResourcePreFetchResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="VirusTotal URL verdict (cache)",
                            description=f"URL flagged by VT (cache): {payload.uri}",
                            code="VT_URL_BLOCK",
                            details={"stats": stats},
                        ),
                    )
        if cfg.check_domain and host:
            cached = _from_cache(f"vt:domain:{host}")
            if cached:
                attrs = cached.get("data", {}).get("attributes", {})
                stats = attrs.get("last_analysis_stats", {})
                vt_meta["domain_stats"] = stats
                if _should_block(stats, cfg):
                    return ResourcePreFetchResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="VirusTotal domain verdict (cache)",
                            description=f"Domain flagged by VT (cache): {host}",
                            code="VT_DOMAIN_BLOCK",
                            details={"stats": stats, "domain": host},
                        ),
                    )
        is_ip = False
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except Exception:
            is_ip = False
        if cfg.check_ip and host and is_ip:
            cached = _from_cache(f"vt:ip:{host}")
            if cached:
                attrs = cached.get("data", {}).get("attributes", {})
                stats = attrs.get("last_analysis_stats", {})
                vt_meta["ip_stats"] = stats
                if _should_block(stats, cfg):
                    return ResourcePreFetchResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="VirusTotal IP verdict (cache)",
                            description=f"IP flagged by VT (cache): {host}",
                            code="VT_IP_BLOCK",
                            details={"stats": stats, "ip": host},
                        ),
                    )

        headers = {"x-apikey": api_key}
        async with self._client_factory(cfg, headers) as client:
            # vt_meta may already be populated from cache
            try:
                # File checks for local files (hash first, upload if configured and unknown)
                if cfg.enable_file_checks and scheme == "file":
                    # Resolve local path
                    file_path = unquote(parsed.path)
                    if os.path.isfile(file_path):
                        # Compute hash (async via to_thread)
                        if cfg.file_hash_alg.lower() not in ("sha256", "md5", "sha1"):
                            alg = "sha256"
                        else:
                            alg = cfg.file_hash_alg.lower()
                        digest = await asyncio.to_thread(_compute_file_hash, file_path, alg)
                        finfo = await _http_get(client, f"{cfg.base_url}/files/{digest}")
                        if finfo is None and cfg.upload_if_unknown:
                            size = os.path.getsize(file_path)
                            if size <= cfg.upload_max_bytes:
                                # Upload file for analysis (async via to_thread with sync httpx + retry)
                                upload_headers = {"x-apikey": api_key}
                                data = await asyncio.to_thread(
                                    _upload_file_sync,
                                    f"{cfg.base_url}/files",
                                    file_path,
                                    upload_headers,
                                    cfg.timeout_seconds,
                                    cfg.max_retries,
                                    cfg.base_backoff,
                                    cfg.max_delay,
                                    cfg.jitter_max,
                                )
                                analysis_id = data.get("data", {}).get("id")
                                if cfg.wait_for_analysis and analysis_id:
                                    deadline = time.time() + cfg.max_wait_seconds
                                    while time.time() < deadline:
                                        a = await _http_get(client, f"{cfg.base_url}/analyses/{analysis_id}")
                                        if a and a.get("data", {}).get("attributes", {}).get("status") == "completed":
                                            break
                                        await asyncio.sleep(cfg.poll_interval_seconds)
                                # Re-check by digest
                                finfo = await _http_get(client, f"{cfg.base_url}/files/{digest}")
                            else:
                                vt_meta["file_upload_skipped"] = True
                        if finfo:
                            attrs = finfo.get("data", {}).get("attributes", {})
                            stats = attrs.get("last_analysis_stats", {})
                            vt_meta["file_stats"] = stats
                            if _should_block(stats, cfg):
                                return ResourcePreFetchResult(
                                    continue_processing=False,
                                    violation=PluginViolation(
                                        reason="VirusTotal file verdict",
                                        description=f"File flagged by VirusTotal: {file_path}",
                                        code="VT_FILE_BLOCK",
                                        details={"stats": stats, "hash": digest, "alg": alg},
                                    ),
                                )

                # URL check
                if cfg.check_url and is_http:
                    info = await self._check_url(client, payload.uri, cfg)
                    if info:
                        attrs = info.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_meta["url_stats"] = stats
                        if _should_block(stats, cfg):
                            return ResourcePreFetchResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal URL verdict",
                                    description=f"URL flagged by VirusTotal: {payload.uri}",
                                    code="VT_URL_BLOCK",
                                    details={"stats": stats},
                                ),
                            )

                # Domain check
                if cfg.check_domain and host:
                    dinfo = await self._check_domain(client, host, cfg)
                    if dinfo:
                        attrs = dinfo.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_meta["domain_stats"] = stats
                        if _should_block(stats, cfg):
                            return ResourcePreFetchResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal domain verdict",
                                    description=f"Domain flagged by VirusTotal: {host}",
                                    code="VT_DOMAIN_BLOCK",
                                    details={"stats": stats, "domain": host},
                                ),
                            )

                # IP check (if URI host is an IP)
                if cfg.check_ip and host and is_ip:
                    iinfo = await self._check_ip(client, host, cfg)
                    if iinfo:
                        attrs = iinfo.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_meta["ip_stats"] = stats
                        if _should_block(stats, cfg):
                            return ResourcePreFetchResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal IP verdict",
                                    description=f"IP flagged by VirusTotal: {host}",
                                    code="VT_IP_BLOCK",
                                    details={"stats": stats, "ip": host},
                                ),
                            )

                # Pass with metadata if nothing blocked
                return ResourcePreFetchResult(metadata={"virustotal": vt_meta})
            except httpx.HTTPStatusError as exc:
                return ResourcePreFetchResult(metadata={"virustotal": {"error": f"HTTP {exc.response.status_code}", "detail": str(exc)}})
            except httpx.TimeoutException:
                return ResourcePreFetchResult(metadata={"virustotal": {"error": "timeout"}})
            except Exception as exc:  # nosec - isolate plugin errors by design
                return ResourcePreFetchResult(metadata={"virustotal": {"error": "exception", "detail": str(exc)}})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:  # noqa: D401
        """Scan URLs in tool output with VirusTotal.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result blocking if any URL is flagged, or allowing with scan metadata.
        """
        cfg = self._cfg
        if not cfg.scan_tool_outputs:
            return ToolPostInvokeResult(continue_processing=True)
        api_key = _get_api_key(cfg)
        if not api_key:
            return ToolPostInvokeResult(metadata={"virustotal": {"skipped": True, "reason": "no_api_key"}})

        # Local allow/deny on any URL encountered
        urls: list[str] = []
        pattern = re.compile(cfg.url_pattern)

        def add_from(obj: Any):
            """Recursively extract URLs from nested data structures.

            Args:
                obj: Object to extract URLs from (str, dict, or list).
            """
            if isinstance(obj, str):
                urls.extend(pattern.findall(obj))
            elif isinstance(obj, dict):
                for v in obj.values():
                    add_from(v)
            elif isinstance(obj, list):
                for v in obj:
                    add_from(v)

        add_from(payload.result)
        if not urls:
            return ToolPostInvokeResult(continue_processing=True)

        # Limit URLs per call
        urls = urls[: cfg.max_urls_per_call]

        # Apply local overrides before HTTP
        filtered: list[str] = []
        for u in urls:
            h = (urlparse(u).hostname or "").lower()
            ov = _apply_overrides(u, h, cfg)
            if ov == "deny":
                return ToolPostInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Local denylist match",
                        description=f"Denied by local policy: {u}",
                        code="VT_LOCAL_DENY",
                        details={"url": u, "host": h},
                    ),
                )
            if ov == "allow":
                continue
            filtered.append(u)
        urls = filtered
        if not urls:
            return ToolPostInvokeResult(metadata={"virustotal": {"skipped": True, "reason": "local_allow"}})

        headers = {"x-apikey": api_key}
        async with self._client_factory(cfg, headers) as client:
            vt_items: list[dict[str, Any]] = []
            for u in urls:
                try:
                    info = await self._check_url(client, u, cfg)
                    if info:
                        attrs = info.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_items.append({"url": u, "stats": stats})
                        if _should_block(stats, cfg):
                            return ToolPostInvokeResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal URL verdict (output)",
                                    description=f"Output URL flagged by VirusTotal: {u}",
                                    code="VT_URL_BLOCK",
                                    details={"stats": stats, "url": u},
                                ),
                            )
                except Exception as exc:  # nosec - isolate plugin errors
                    vt_items.append({"url": u, "error": str(exc)})

            return ToolPostInvokeResult(metadata={"virustotal": {"outputs": vt_items}})

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:  # noqa: D401
        """Scan URLs in prompt output with VirusTotal.

        Args:
            payload: Prompt post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result blocking if any URL is flagged, or allowing with scan metadata.
        """
        cfg = self._cfg
        if not cfg.scan_prompt_outputs:
            return PromptPosthookResult(continue_processing=True)
        api_key = _get_api_key(cfg)
        if not api_key:
            return PromptPosthookResult(metadata={"virustotal": {"skipped": True, "reason": "no_api_key"}})

        # Extract text from messages
        texts: list[str] = []
        try:
            for m in payload.result.messages:
                c = getattr(m, "content", None)
                t = getattr(c, "text", None)
                if isinstance(t, str):
                    texts.append(t)
        except Exception:
            return PromptPosthookResult(continue_processing=True)

        if not texts:
            return PromptPosthookResult(continue_processing=True)

        pattern = re.compile(cfg.url_pattern)
        urls: list[str] = []
        for t in texts:
            urls.extend(pattern.findall(t))
        urls = urls[: cfg.max_urls_per_call]
        if not urls:
            return PromptPosthookResult(continue_processing=True)

        # Local overrides first
        filtered: list[str] = []
        for u in urls:
            h = (urlparse(u).hostname or "").lower()
            ov = _apply_overrides(u, h, cfg)
            if ov == "deny":
                return PromptPosthookResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Local denylist match",
                        description=f"Denied by local policy: {u}",
                        code="VT_LOCAL_DENY",
                        details={"url": u, "host": h},
                    ),
                )
            if ov == "allow":
                continue
            filtered.append(u)
        urls = filtered
        if not urls:
            return PromptPosthookResult(metadata={"virustotal": {"skipped": True, "reason": "local_allow"}})

        headers = {"x-apikey": api_key}
        async with self._client_factory(cfg, headers) as client:
            vt_items: list[dict[str, Any]] = []
            for u in urls:
                try:
                    info = await self._check_url(client, u, cfg)
                    if info:
                        attrs = info.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_items.append({"url": u, "stats": stats})
                        if _should_block(stats, cfg):
                            return PromptPosthookResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal URL verdict (prompt)",
                                    description=f"Prompt URL flagged by VirusTotal: {u}",
                                    code="VT_URL_BLOCK",
                                    details={"stats": stats, "url": u},
                                ),
                            )
                except Exception as exc:  # nosec
                    vt_items.append({"url": u, "error": str(exc)})
            return PromptPosthookResult(metadata={"virustotal": {"outputs": vt_items}})

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:  # noqa: D401
        """Scan URLs in resource content with VirusTotal.

        Args:
            payload: Resource post-fetch payload containing content.
            context: Plugin execution context.

        Returns:
            Result blocking if any URL is flagged, or allowing with scan metadata.
        """
        cfg = self._cfg
        if not cfg.scan_resource_contents:
            return ResourcePostFetchResult(continue_processing=True)
        api_key = _get_api_key(cfg)
        if not api_key:
            return ResourcePostFetchResult(metadata={"virustotal": {"skipped": True, "reason": "no_api_key"}})

        # Extract text from ResourceContent if present
        text = getattr(payload.content, "text", None)
        if not isinstance(text, str) or not text:
            return ResourcePostFetchResult(continue_processing=True)

        pattern = re.compile(cfg.url_pattern)
        urls = pattern.findall(text)[: cfg.max_urls_per_call]
        if not urls:
            return ResourcePostFetchResult(continue_processing=True)

        # Local overrides first
        filtered_r: list[str] = []
        for u in urls:
            h = (urlparse(u).hostname or "").lower()
            ov = _apply_overrides(u, h, cfg)
            if ov == "deny":
                return ResourcePostFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Local denylist match",
                        description=f"Denied by local policy: {u}",
                        code="VT_LOCAL_DENY",
                        details={"url": u, "host": h},
                    ),
                )
            if ov == "allow":
                continue
            filtered_r.append(u)
        urls = filtered_r
        if not urls:
            return ResourcePostFetchResult(metadata={"virustotal": {"skipped": True, "reason": "local_allow"}})

        headers = {"x-apikey": api_key}
        async with self._client_factory(cfg, headers) as client:
            vt_items: list[dict[str, Any]] = []
            for u in urls:
                try:
                    info = await self._check_url(client, u, cfg)
                    if info:
                        attrs = info.get("data", {}).get("attributes", {})
                        stats = attrs.get("last_analysis_stats", {})
                        vt_items.append({"url": u, "stats": stats})
                        if _should_block(stats, cfg):
                            return ResourcePostFetchResult(
                                continue_processing=False,
                                violation=PluginViolation(
                                    reason="VirusTotal URL verdict (resource)",
                                    description=f"Resource URL flagged by VirusTotal: {u}",
                                    code="VT_URL_BLOCK",
                                    details={"stats": stats, "url": u},
                                ),
                            )
                except Exception as exc:  # nosec
                    vt_items.append({"url": u, "error": str(exc)})
            return ResourcePostFetchResult(metadata={"virustotal": {"outputs": vt_items}})
