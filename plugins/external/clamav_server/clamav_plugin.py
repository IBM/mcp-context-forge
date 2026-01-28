# -*- coding: utf-8 -*-
"""Location: ./plugins/external/clamav_server/clamav_plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

ClamAV Remote Plugin (External MCP server).
Provides malware scanning via ClamAV for resources and content. Designed to run
in an external MCP server process and be called by the gateway through STDIO.

Modes:
- eicar_only: No clamd dependency; flags EICAR string patterns for tests/dev.
- clamd_tcp: Connect to clamd via TCP host/port and use INSTREAM for content.
- clamd_unix: Connect to clamd via UNIX socket path and use INSTREAM.

Hooks implemented:
- resource_pre_fetch: If `file://` URI, scan local file content.
- resource_post_fetch: If text content available, scan text.

Policy:
- block_on_positive: When true, block on any positive detection; else annotate.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import os
import socket
from typing import Any

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

EICAR_SIGNATURES = (
    "EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
)


def _has_eicar(data: bytes) -> bool:
    """Check if data contains EICAR test virus signature.

    Args:
        data: Bytes to scan for EICAR signature.

    Returns:
        True if EICAR signature found, False otherwise.
    """
    blob = data.decode("latin1", errors="ignore")
    return any(sig in blob for sig in EICAR_SIGNATURES)


def _read_file_limited(path: str, max_bytes: int) -> bytes:
    """Read file with size limit (called via asyncio.to_thread).

    Args:
        path: Path to file to read.
        max_bytes: Maximum bytes to read.

    Returns:
        File content bytes (up to max_bytes + 1).
    """
    with open(path, "rb") as f:  # nosec B108
        return f.read(max_bytes + 1)


class ClamAVConfig:
    """ClamAVConfig implementation."""

    def __init__(self, cfg: dict[str, Any] | None) -> None:
        """Initialize the instance.

        Args:
            cfg: Configuration dictionary.
        """
        c = cfg or {}
        self.mode: str = c.get("mode", "eicar_only")  # eicar_only|clamd_tcp|clamd_unix
        self.host: str | None = c.get("clamd_host")
        self.port: int = int(c.get("clamd_port", 3310))
        self.unix_socket: str | None = c.get("clamd_socket")
        self.timeout: float = float(c.get("timeout_seconds", 5.0))
        self.block_on_positive: bool = bool(c.get("block_on_positive", True))
        self.max_bytes: int = int(c.get("max_scan_bytes", 10 * 1024 * 1024))


def _clamd_instream_scan_tcp(host: str, port: int, data: bytes, timeout: float) -> str:
    """Scan data using ClamAV daemon via TCP connection.

    Args:
        host: ClamAV daemon host address.
        port: ClamAV daemon port number.
        data: Bytes to scan.
        timeout: Connection timeout in seconds.

    Returns:
        Scan response from ClamAV daemon.
    """
    # Minimal INSTREAM protocol: https://linux.die.net/man/8/clamd
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    try:
        s.sendall(b"zINSTREAM\n")
        # chunk in 8KB
        idx = 0
        n = len(data)
        while idx < n:
            chunk = data[idx : idx + 8192]
            s.sendall(len(chunk).to_bytes(4, "big") + chunk)
            idx += len(chunk)
        s.sendall((0).to_bytes(4, "big"))
        # read response
        resp = s.recv(4096)
        return resp.decode("utf-8", errors="ignore")
    finally:
        s.close()


def _clamd_instream_scan_unix(path: str, data: bytes, timeout: float) -> str:
    """Scan data using ClamAV daemon via Unix socket connection.

    Args:
        path: Unix socket path.
        data: Bytes to scan.
        timeout: Connection timeout in seconds.

    Returns:
        Scan response from ClamAV daemon.
    """
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(path)
    try:
        s.sendall(b"zINSTREAM\n")
        idx = 0
        n = len(data)
        while idx < n:
            chunk = data[idx : idx + 8192]
            s.sendall(len(chunk).to_bytes(4, "big") + chunk)
            idx += len(chunk)
        s.sendall((0).to_bytes(4, "big"))
        resp = s.recv(4096)
        return resp.decode("utf-8", errors="ignore")
    finally:
        s.close()


class ClamAVRemotePlugin(Plugin):
    """External ClamAV plugin for scanning resources and content."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the instance.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = ClamAVConfig(config.config)
        self._stats: dict[str, int] = {"attempted": 0, "infected": 0, "blocked": 0, "errors": 0}

    def _bump(self, key: str) -> None:
        """Increment statistics counter.

        Args:
            key: Statistics key to increment.
        """
        try:
            self._stats[key] = int(self._stats.get(key, 0)) + 1
        except Exception:
            pass

    def _scan_bytes(self, data: bytes) -> tuple[bool, str]:
        """Scan bytes for malware using configured scan method.

        Args:
            data: Bytes to scan for malware.

        Returns:
            Tuple of (infected: bool, detail: str) indicating if malware was found and scan details.
        """
        if len(data) > self._cfg.max_bytes:
            return False, "SKIPPED: too large"

        mode = self._cfg.mode
        if mode == "eicar_only":
            infected = _has_eicar(data)
            return infected, "EICAR" if infected else "OK"
        if mode == "clamd_tcp" and self._cfg.host:
            try:
                resp = _clamd_instream_scan_tcp(self._cfg.host, self._cfg.port, data, self._cfg.timeout)
                infected = "FOUND" in resp
                return infected, resp
            except Exception as exc:  # nosec - external server may be unavailable
                return False, f"ERROR: {exc}"
        if mode == "clamd_unix" and self._cfg.unix_socket:
            try:
                resp = _clamd_instream_scan_unix(self._cfg.unix_socket, data, self._cfg.timeout)
                infected = "FOUND" in resp
                return infected, resp
            except Exception as exc:  # nosec
                return False, f"ERROR: {exc}"
        return False, "SKIPPED: clamd not configured"

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Scan local file content with ClamAV before fetching.

        Args:
            payload: Resource pre-fetch payload containing URI.
            context: Plugin execution context.

        Returns:
            Result blocking if malware detected, or allowing with scan metadata.
        """
        uri = payload.uri
        if uri.startswith("file://"):
            path = uri[len("file://") :]
            if os.path.isfile(path):
                try:
                    data = await asyncio.to_thread(_read_file_limited, path, self._cfg.max_bytes)
                except Exception as exc:  # nosec - IO errors simply annotate
                    self._bump("errors")
                    return ResourcePreFetchResult(metadata={"clamav": {"error": str(exc)}})
                self._bump("attempted")
                infected, detail = self._scan_bytes(data)
                if infected and self._cfg.block_on_positive:
                    self._bump("infected")
                    self._bump("blocked")
                    return ResourcePreFetchResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="ClamAV detection",
                            description=f"Malware detected in file: {path}",
                            code="CLAMAV_INFECTED",
                            details={"detail": detail},
                        ),
                    )
                if infected:
                    self._bump("infected")
                return ResourcePreFetchResult(metadata={"clamav": {"infected": infected, "detail": detail}})
        return ResourcePreFetchResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Scan resource text content with ClamAV after fetching.

        Args:
            payload: Resource post-fetch payload containing content.
            context: Plugin execution context.

        Returns:
            Result blocking if malware detected, or allowing with scan metadata.
        """
        text = getattr(payload.content, "text", None)
        if isinstance(text, str) and text:
            data = text.encode("utf-8", errors="ignore")
            self._bump("attempted")
            infected, detail = self._scan_bytes(data)
            if infected and self._cfg.block_on_positive:
                self._bump("infected")
                self._bump("blocked")
                return ResourcePostFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="ClamAV detection",
                        description=f"Malware detected in resource content: {payload.uri}",
                        code="CLAMAV_INFECTED",
                        details={"detail": detail},
                    ),
                )
            if infected:
                self._bump("infected")
            return ResourcePostFetchResult(metadata={"clamav": {"infected": infected, "detail": detail}})
        return ResourcePostFetchResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Scan prompt message text with ClamAV after fetching.

        Args:
            payload: Prompt post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result blocking if malware detected, or allowing with scan metadata.
        """
        # Scan rendered prompt messages text
        try:
            for m in payload.result.messages:
                c = getattr(m, "content", None)
                t = getattr(c, "text", None)
                if isinstance(t, str) and t:
                    self._bump("attempted")
                    infected, detail = self._scan_bytes(t.encode("utf-8", errors="ignore"))
                    if infected and self._cfg.block_on_positive:
                        self._bump("infected")
                        self._bump("blocked")
                        return PromptPosthookResult(
                            continue_processing=False,
                            violation=PluginViolation(
                                reason="ClamAV detection",
                                description=f"Malware detected in prompt output: {payload.prompt_id}",
                                code="CLAMAV_INFECTED",
                                details={"detail": detail},
                            ),
                        )
                    if infected:
                        self._bump("infected")
            return PromptPosthookResult(continue_processing=True)
        except Exception as exc:  # nosec - defensive
            self._bump("errors")
            return PromptPosthookResult(metadata={"clamav": {"error": str(exc)}})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Scan tool output strings with ClamAV after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result blocking if malware detected, or allowing with scan metadata.
        """

        # Recursively scan string values in tool outputs
        def iter_strings(obj):
            """Recursively iterate over all string values in an object.

            Args:
                obj: Object to iterate over (str, dict, list, or other).

            Yields:
                String values found in the object.
            """
            if isinstance(obj, str):
                yield obj
            elif isinstance(obj, dict):
                for v in obj.values():
                    yield from iter_strings(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from iter_strings(v)

        try:
            for s in iter_strings(payload.result):
                if s:
                    self._bump("attempted")
                    infected, detail = self._scan_bytes(s.encode("utf-8", errors="ignore"))
                    if infected and self._cfg.block_on_positive:
                        self._bump("infected")
                        self._bump("blocked")
                        return ToolPostInvokeResult(
                            continue_processing=False,
                            violation=PluginViolation(
                                reason="ClamAV detection",
                                description=f"Malware detected in tool output: {payload.name}",
                                code="CLAMAV_INFECTED",
                                details={"detail": detail},
                            ),
                        )
                    if infected:
                        self._bump("infected")
            return ToolPostInvokeResult(continue_processing=True)
        except Exception as exc:  # nosec
            self._bump("errors")
            return ToolPostInvokeResult(metadata={"clamav": {"error": str(exc)}})

    def health(self) -> dict[str, Any]:
        """Return plugin health and metrics; try clamd connectivity when configured.

        Returns:
            Dictionary containing plugin health status and metrics.
        """
        status = {"mode": self._cfg.mode, "block_on_positive": self._cfg.block_on_positive, "stats": dict(self._stats)}
        reachable = None
        try:
            if self._cfg.mode == "clamd_tcp" and self._cfg.host:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self._cfg.timeout)
                s.connect((self._cfg.host, self._cfg.port))
                try:
                    s.sendall(b"PING\n")
                    resp = s.recv(16)
                    reachable = resp.decode("utf-8", errors="ignore").strip().upper() == "PONG"
                finally:
                    s.close()
            elif self._cfg.mode == "clamd_unix" and self._cfg.unix_socket:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(self._cfg.timeout)
                s.connect(self._cfg.unix_socket)
                try:
                    s.sendall(b"PING\n")
                    resp = s.recv(16)
                    reachable = resp.decode("utf-8", errors="ignore").strip().upper() == "PONG"
                finally:
                    s.close()
        except Exception:
            reachable = False
        if reachable is not None:
            status["clamd_reachable"] = reachable
        return status
