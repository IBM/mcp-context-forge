# -*- coding: utf-8 -*-
"""Location: ./plugins/web_bot_auth/web_bot_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Tejaswi Suresh

Web Bot Auth Signing Plugin.

Signs the gateway's outbound tool and A2A calls with Web Bot Auth
(draft-ietf-webbotauth-httpsig-protocol, built on RFC 9421 HTTP Message
Signatures), so an upstream server, or the CDN in front of it, can verify that
a request comes from this gateway. Each signed request gets three headers
under the label ``sig1``::

    Signature-Agent: sig1="<signature_agent>"
    Signature-Input: sig1=("@authority" "signature-agent";key="sig1");created=...;
                     keyid="<JWK thumbprint>";alg="ed25519";expires=...;nonce="...";tag="web-bot-auth"
    Signature: sig1=:<Ed25519 signature>:

The signature covers the destination host and the Signature-Agent URL. A
verifier fetches the public key from that URL (the operator hosts it; see
``WebBotAuthSigner.directory``) and checks the signature.

Hooks: tool_pre_invoke, agent_pre_invoke
"""

# Future
from __future__ import annotations

# Standard
import base64
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Optional
from urllib.parse import urlsplit

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field, field_validator

# First-Party
from cpex.framework import (
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from cpex.framework.hooks.http import HttpHeaderPayload

logger = logging.getLogger(__name__)

LABEL = "sig1"
TAG = "web-bot-auth"
MAX_EXPIRES_IN = 86400  # The draft recommends no more than 24 hours after created.
DIRECTORY_MEDIA_TYPE = "application/http-message-signatures-directory+json"
SIGNATURE_HEADERS = ("signature", "signature-input", "signature-agent")
_DEFAULT_PORT = {"http": 80, "https": 443}


def _b64url(data: bytes) -> str:
    """Encode bytes as unpadded base64url.

    Args:
        data: Bytes to encode.

    Returns:
        The unpadded base64url text.

    Examples:
        >>> _b64url(b"\\xfb\\xff")
        '-_8'
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    """Decode unpadded base64url.

    Args:
        text: Base64url text, with or without padding.

    Returns:
        The decoded bytes.

    Examples:
        >>> _b64url_decode("-_8")
        b'\\xfb\\xff'
    """
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sf_string(value: str) -> str:
    """Serialize an RFC 9651 structured-field string.

    Args:
        value: Printable ASCII text.

    Returns:
        The quoted, escaped string.

    Raises:
        ValueError: If the value is not printable ASCII.

    Examples:
        >>> _sf_string('a"b')
        '"a\\\\"b"'
    """
    if not all(0x20 <= ord(c) <= 0x7E for c in value):
        raise ValueError(f"{value!r} is not printable ASCII, so it cannot be a structured-field string")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _split(url: str) -> Optional[tuple[str, str, Optional[int]]]:
    """Return (scheme, lowercase host, port) of an http(s) URL, else None.

    Args:
        url: The URL.

    Returns:
        The parts, or None for a URL that is not http(s) or has no host.

    Examples:
        >>> _split("https://API.example.com:8443/mcp")
        ('https', 'api.example.com', 8443)
        >>> _split("ftp://example.com") is None
        True
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORT or not parts.hostname:
        return None
    try:
        host = parts.hostname.encode("idna").decode("ascii") if not parts.hostname.isascii() else parts.hostname.lower()
    except UnicodeError:
        return None
    return parts.scheme, host, port


def authority(url: str) -> Optional[str]:
    """Return the RFC 9421 ``@authority`` of an http(s) URL.

    The host is lowercased, an IPv6 host is bracketed, and the port appears only
    when it is not the scheme's default.

    Args:
        url: The request URL.

    Returns:
        The authority, or None for any other URL.

    Examples:
        >>> authority("https://Shop.Example.com/mcp")
        'shop.example.com'
        >>> authority("https://shop.example.com:443/mcp")
        'shop.example.com'
        >>> authority("http://127.0.0.1:9000/mcp")
        '127.0.0.1:9000'
        >>> authority("https://[::1]:8443/")
        '[::1]:8443'
    """
    parts = _split(url)
    if parts is None:
        return None
    scheme, host, port = parts
    host = f"[{host}]" if ":" in host else host
    return host if port in (None, _DEFAULT_PORT[scheme]) else f"{host}:{port}"


def _is_loopback(host: str) -> bool:
    """Return True for localhost names and loopback addresses.

    Args:
        host: A lowercase host.

    Returns:
        Whether the host is loopback.

    Examples:
        >>> _is_loopback("localhost"), _is_loopback("127.0.0.1"), _is_loopback("example.com")
        (True, True, False)
    """
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_private_key(material: Any) -> Ed25519PrivateKey:
    """Load an Ed25519 private key.

    Args:
        material: PEM text or bytes, a private JWK (dict or JSON text), or an
            ``Ed25519PrivateKey``.

    Returns:
        The private key.

    Raises:
        ValueError: If the material is not an Ed25519 private key.
    """
    if isinstance(material, Ed25519PrivateKey):
        return material
    if isinstance(material, bytes):
        material = material.decode("utf-8")
    if isinstance(material, str) and material.lstrip().startswith("{"):
        material = json.loads(material)
    if isinstance(material, dict):
        if material.get("kty") != "OKP" or material.get("crv") != "Ed25519" or not material.get("d"):
            raise ValueError('A JWK key must be a private Ed25519 key: kty "OKP", crv "Ed25519" and d')
        return Ed25519PrivateKey.from_private_bytes(_b64url_decode(material["d"]))
    if not isinstance(material, str) or "-----BEGIN" not in material:
        raise ValueError("The key must be a PEM private key or a private JWK")
    loaded = serialization.load_pem_private_key(material.encode("utf-8"), password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError(f"The key must be an Ed25519 key, not {type(loaded).__name__}")
    return loaded


class WebBotAuthSigner:
    """Builds Web Bot Auth headers with one Ed25519 key."""

    def __init__(self, key: Ed25519PrivateKey, signature_agent: str, *, expires_in: int = 60, legacy_signature_agent: bool = False) -> None:
        """Set up the signer and compute the RFC 7638 key id.

        Args:
            key: The Ed25519 private key.
            signature_agent: The https URL of the operator's key directory.
            expires_in: Seconds each signature stays valid.
            legacy_signature_agent: Send Signature-Agent as a bare string, the form
                of earlier drafts, for verifiers that do not accept the dictionary form yet.
        """
        self._key = key
        self.signature_agent = signature_agent
        self.expires_in = expires_in
        self.legacy_signature_agent = legacy_signature_agent
        thumbprint_input = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": _b64url(self.public_bytes())}, separators=(",", ":"), sort_keys=True)
        self.keyid = _b64url(hashlib.sha256(thumbprint_input.encode("ascii")).digest())

    def __repr__(self) -> str:
        """Describe the signer without the key.

        Returns:
            A safe representation.
        """
        return f"WebBotAuthSigner(signature_agent={self.signature_agent!r}, keyid={self.keyid!r})"

    def public_bytes(self) -> bytes:
        """Return the raw 32-byte public key.

        Returns:
            The public key bytes.
        """
        return self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def directory(self) -> dict[str, Any]:
        """Return the JWK Set to serve at ``signature_agent``.

        Serve it with Content-Type ``application/http-message-signatures-directory+json``.

        Returns:
            A JWK Set holding the public key only.
        """
        return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64url(self.public_bytes()), "kid": self.keyid, "use": "sig"}]}

    def sign(self, url: str, *, created: Optional[int] = None, nonce: Optional[str] = None) -> dict[str, str]:
        """Return the three Web Bot Auth headers for a request to ``url``.

        Args:
            url: The destination URL.
            created: Signature creation time (Unix seconds). Defaults to now.
            nonce: A unique nonce. Defaults to 64 random bytes, base64.

        Returns:
            The Signature-Agent, Signature-Input and Signature headers.

        Raises:
            ValueError: If the URL has no http(s) authority.
        """
        target = authority(url)
        if target is None:
            raise ValueError("Only http(s) URLs can be signed")
        created = int(time.time()) if created is None else created
        nonce = base64.b64encode(os.urandom(64)).decode("ascii") if nonce is None else nonce
        agent = _sf_string(self.signature_agent)
        component = '"signature-agent"' if self.legacy_signature_agent else f'"signature-agent";key="{LABEL}"'
        params = f'("@authority" {component});created={created};keyid={_sf_string(self.keyid)};alg="ed25519";expires={created + self.expires_in};nonce={_sf_string(nonce)};tag="{TAG}"'
        base = f'"@authority": {target}\n{component}: {agent}\n"@signature-params": {params}'
        signature = base64.b64encode(self._key.sign(base.encode("ascii"))).decode("ascii")
        return {
            "signature-agent": agent if self.legacy_signature_agent else f"{LABEL}={agent}",
            "signature-input": f"{LABEL}={params}",
            "signature": f"{LABEL}=:{signature}:",
        }


class WebBotAuthConfig(BaseModel):
    """Configuration for the Web Bot Auth signing plugin.

    Attributes:
        signature_agent: The https URL where the operator serves the public key
            directory, usually ``https://<domain>/.well-known/http-message-signatures-directory``.
        private_key_env: Environment variable holding the Ed25519 private key
            (PEM or private JWK JSON).
        private_key_file: Path to a file holding the key. Used when set,
            instead of ``private_key_env``.
        hosts: Destination hosts to sign for: exact names, ``*.example.com``
            for subdomains, or ``*`` for every host. Empty signs nothing.
        expires_in: Seconds each signature stays valid, 1 to 86400.
        legacy_signature_agent: Send Signature-Agent as a bare string, the form
            of earlier drafts.
        allow_insecure_loopback: Also sign plain http requests to loopback hosts,
            for local testing. Other plain http requests are never signed.
    """

    signature_agent: str
    private_key_env: str = "WEB_BOT_AUTH_PRIVATE_KEY"
    private_key_file: Optional[str] = None
    hosts: list[str] = Field(default_factory=list)
    expires_in: int = Field(default=60, ge=1, le=MAX_EXPIRES_IN)
    legacy_signature_agent: bool = False
    allow_insecure_loopback: bool = False

    @field_validator("signature_agent")
    @classmethod
    def _check_signature_agent(cls, value: str) -> str:
        """Require an https URL that can be a structured-field string.

        Args:
            value: The configured URL.

        Returns:
            The URL.

        Raises:
            ValueError: If it is not a printable-ASCII https URL with a host.
        """
        if not value.startswith("https://") or authority(value) is None or not all(0x21 <= ord(c) <= 0x7E for c in value):
            raise ValueError("signature_agent must be the https URL of your key directory, for example https://example.com/.well-known/http-message-signatures-directory")
        return value

    @field_validator("hosts")
    @classmethod
    def _normalize_hosts(cls, value: list[str]) -> list[str]:
        """Lowercase host patterns and drop blanks.

        Args:
            value: Configured host patterns.

        Returns:
            Normalized patterns.
        """
        return [h.strip().lower().rstrip(".") for h in value if h and h.strip()]


def host_matches(host: str, patterns: list[str]) -> bool:
    """Return True when a host matches any configured pattern.

    Args:
        host: Lowercase destination host.
        patterns: Exact names, ``*.suffix`` patterns, or ``*``.

    Returns:
        Whether the host is in scope.

    Examples:
        >>> host_matches("api.shop.example", ["*.shop.example"])
        True
        >>> host_matches("shop.example", ["*.shop.example"])
        False
        >>> host_matches("evilshop.example", ["*.shop.example"])
        False
        >>> host_matches("anything.test", ["*"])
        True
    """
    host = host.rstrip(".")
    for pattern in patterns:
        if pattern in ("*", host):
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
    return False


def _destination(context: PluginContext, metadata_key: str, url_attr: str) -> Optional[str]:
    """Read a destination URL from the gateway-published metadata.

    Args:
        context: Plugin context.
        metadata_key: Global metadata key (``gateway``, ``tool`` or ``a2a_agent``).
        url_attr: Attribute holding the URL.

    Returns:
        The URL as text, or None.
    """
    item = context.global_context.metadata.get(metadata_key)
    if item is None:
        return None
    value = item.get(url_attr) if isinstance(item, dict) else getattr(item, url_attr, None)
    return str(value) if value else None


class WebBotAuthPlugin(Plugin):
    """Sign outbound tool and A2A calls with Web Bot Auth."""

    def __init__(self, config: PluginConfig) -> None:
        """Load the configuration and the signing key.

        Args:
            config: Plugin configuration.

        Raises:
            ValueError: If no key is configured or the key is not Ed25519.
        """
        super().__init__(config)
        self._cfg = WebBotAuthConfig(**(config.config or {}))
        if self._cfg.private_key_file:
            material: Any = Path(self._cfg.private_key_file).expanduser().read_text(encoding="utf-8")
        else:
            material = os.environ.get(self._cfg.private_key_env)
        if not material:
            raise ValueError(f"WebBotAuthPlugin needs an Ed25519 private key: set {self._cfg.private_key_env} or private_key_file")
        self._signer = WebBotAuthSigner(
            load_private_key(material),
            self._cfg.signature_agent,
            expires_in=self._cfg.expires_in,
            legacy_signature_agent=self._cfg.legacy_signature_agent,
        )
        if not self._cfg.hosts:
            logger.warning("WebBotAuthPlugin has no hosts configured, so it signs nothing")
        logger.info("WebBotAuthPlugin ready: keyid=%s, signature_agent=%s", self._signer.keyid, self._cfg.signature_agent)

    @property
    def signer(self) -> WebBotAuthSigner:
        """The signer, for example to publish ``signer.directory()``.

        Returns:
            The configured signer.
        """
        return self._signer

    def _in_scope(self, url: Optional[str]) -> bool:
        """Return True when requests to this URL should be signed.

        Args:
            url: The destination URL.

        Returns:
            Whether to sign.
        """
        parts = _split(url) if url else None
        if parts is None:
            return False
        scheme, host, _ = parts
        if scheme != "https" and not (self._cfg.allow_insecure_loopback and _is_loopback(host)):
            return False
        return host_matches(host, self._cfg.hosts)

    def _signed_headers(self, headers: Optional[HttpHeaderPayload], url: Optional[str]) -> Optional[HttpHeaderPayload]:
        """Return the headers with fresh Web Bot Auth headers, or None to leave them as they are.

        Args:
            headers: The outbound headers the gateway passed to the hook.
            url: The destination URL.

        Returns:
            Replacement headers, or None when the destination is out of scope.
        """
        if url is None or not self._in_scope(url):
            return None
        current = headers.model_dump() if headers is not None else {}
        # Drop any signature headers already present (for example passed through
        # from the client) so the upstream sees only the gateway's own.
        kept = {k: v for k, v in current.items() if k.lower() not in SIGNATURE_HEADERS}
        return HttpHeaderPayload(root={**kept, **self._signer.sign(url)})

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Sign an outbound tool call.

        The destination is the upstream MCP server (``gateway.url``) for MCP
        tools, or the tool's own URL for REST tools.

        Args:
            payload: Tool invocation payload.
            context: Plugin context.

        Returns:
            Result with signed headers, or an unchanged result when out of scope.
        """
        url = _destination(context, "gateway", "url")
        if url is None:
            tool = context.global_context.metadata.get("tool")
            integration = tool.get("integration_type") if isinstance(tool, dict) else getattr(tool, "integration_type", None)
            if str(integration).upper() == "REST":
                url = _destination(context, "tool", "url")
        signed = self._signed_headers(payload.headers, url)
        if signed is None:
            return ToolPreInvokeResult()
        logger.debug("Signed tool call %s to %s", payload.name, authority(url or ""))
        return ToolPreInvokeResult(
            modified_payload=payload.model_copy(update={"headers": signed}),
            metadata={"web_bot_auth": {"signed": True, "authority": authority(url or ""), "keyid": self._signer.keyid}},
        )

    async def agent_pre_invoke(self, payload: AgentPreInvokePayload, context: PluginContext) -> AgentPreInvokeResult:
        """Sign an outbound A2A agent call to the agent's ``endpoint_url``.

        Args:
            payload: Agent invocation payload.
            context: Plugin context.

        Returns:
            Result with signed headers, or an unchanged result when out of scope.
        """
        url = _destination(context, "a2a_agent", "endpoint_url")
        signed = self._signed_headers(payload.headers, url)
        if signed is None:
            return AgentPreInvokeResult()
        logger.debug("Signed A2A call %s to %s", payload.agent_id, authority(url or ""))
        return AgentPreInvokeResult(
            modified_payload=payload.model_copy(update={"headers": signed}),
            metadata={"web_bot_auth": {"signed": True, "authority": authority(url or ""), "keyid": self._signer.keyid}},
        )


def main() -> None:  # pragma: no cover - thin CLI wrapper
    """Print the key directory JSON for the key in WEB_BOT_AUTH_PRIVATE_KEY.

    Usage: ``python -m plugins.web_bot_auth.web_bot_auth <signature_agent_url>``
    """
    # Standard
    import sys  # pylint: disable=import-outside-toplevel

    material = os.environ.get("WEB_BOT_AUTH_PRIVATE_KEY")
    if not material or len(sys.argv) != 2:
        sys.exit("Set WEB_BOT_AUTH_PRIVATE_KEY and pass the signature agent URL")
    signer = WebBotAuthSigner(load_private_key(material), sys.argv[1])
    print(json.dumps(signer.directory(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
