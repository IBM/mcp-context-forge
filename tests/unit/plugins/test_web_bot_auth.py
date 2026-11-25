# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_web_bot_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the Web Bot Auth signing plugin.

The signer is checked against the Ed25519 test vectors of
draft-ietf-webbotauth-httpsig-protocol. The vectors use the RFC 9421 B.1.4
test key, a published test key.
"""

# Standard
import base64
import json
import re
from types import SimpleNamespace
from typing import Any

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import ValidationError
import pytest

# First-Party
from cpex.framework import (
    AgentPreInvokePayload,
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
)
from cpex.framework.hooks.http import HttpHeaderPayload
from plugins.web_bot_auth import web_bot_auth as wba
from plugins.web_bot_auth.web_bot_auth import load_private_key, WebBotAuthPlugin, WebBotAuthSigner

RFC9421_JWK = {  # pragma: allowlist secret
    "kty": "OKP",
    "crv": "Ed25519",
    "x": "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
    "d": "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU",  # pragma: allowlist secret
}
RFC9421_PEM = (
    Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(RFC9421_JWK["d"] + "="))
    .private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    .decode()
)
DIRECTORY = "https://signature-agent.test/.well-known/http-message-signatures-directory"
KEYID = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"
ENV = "WBA_TEST_PRIVATE_KEY"


def verify(headers: dict[str, str], host: str, public: bytes) -> str:
    """Verify Web Bot Auth headers as an upstream server does.

    Args:
        headers: Received headers, lowercase names.
        host: The authority the request went to.
        public: Raw Ed25519 public key.

    Returns:
        The Signature-Agent URL.
    """
    label, inner, params = re.fullmatch(r"(\w+)=\(([^)]*)\)(.*)", headers["signature-input"]).groups()  # type: ignore[union-attr]
    assert inner == f'"@authority" "signature-agent";key="{label}"'
    assert 'tag="web-bot-auth"' in params and 'alg="ed25519"' in params
    agent = re.fullmatch(rf'{label}=("[^"]*")', headers["signature-agent"]).group(1)  # type: ignore[union-attr]
    signature = re.fullmatch(rf"{label}=:([A-Za-z0-9+/=]+):", headers["signature"]).group(1)  # type: ignore[union-attr]
    base = f'"@authority": {host}\n"signature-agent";key="{label}": {agent}\n"@signature-params": ({inner}){params}'
    Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(signature), base.encode())
    return agent.strip('"')


def make_plugin(monkeypatch: pytest.MonkeyPatch, **config: Any) -> WebBotAuthPlugin:
    """Build the plugin with the test key in the environment.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        **config: Plugin config overrides.

    Returns:
        The plugin.
    """
    monkeypatch.setenv(ENV, RFC9421_PEM)
    settings = {"signature_agent": DIRECTORY, "private_key_env": ENV, "hosts": ["*.shop.test", "api.example.test"], **config}
    return WebBotAuthPlugin(
        PluginConfig(
            name="WebBotAuthPlugin",
            kind="plugins.web_bot_auth.web_bot_auth.WebBotAuthPlugin",
            hooks=["tool_pre_invoke", "agent_pre_invoke"],
            mode="sequential",
            priority=900,
            config=settings,
        )
    )


def context(**metadata: Any) -> PluginContext:
    """Build a plugin context with gateway-published metadata.

    Args:
        **metadata: Global metadata entries.

    Returns:
        The context.
    """
    return PluginContext(global_context=GlobalContext(request_id="req-1", metadata=metadata))


class TestSigner:
    """The signer against the draft's vectors."""

    def test_draft_ed25519_vector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ed25519 is deterministic, so the same base gives the draft's signature byte for byte."""
        monkeypatch.setattr(wba, "LABEL", "sig2")
        signer = WebBotAuthSigner(load_private_key(RFC9421_PEM), DIRECTORY, expires_in=4889289600 - 1735689600)
        nonce = "n9p433xm+NJ3ph3upfBIGmsuwHw387YV7Q/F+6BSpGCVjYCqQw6rznNA8PVVLySrAWsv0hQtFioQb6E1YsauiA=="
        assert signer.sign("https://example.com/path?q=1", created=1735689600, nonce=nonce) == {
            "signature-agent": f'sig2="{DIRECTORY}"',
            "signature-input": f'sig2=("@authority" "signature-agent";key="sig2");created=1735689600;keyid="{KEYID}";alg="ed25519";expires=4889289600;nonce="{nonce}";tag="web-bot-auth"',
            "signature": "sig2=:K/yVRxeBAr93LLpXNu+7VJysBLJzHbx5ei/qkTDFY2qm0ogzJaAWn0p8j/7NoG3VpFpBehIHOGDkczVCm2epDw==:",
        }

    def test_draft_legacy_vector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bare-string Signature-Agent of earlier drafts, covered without key=."""
        monkeypatch.setattr(wba, "LABEL", "sig2")
        signer = WebBotAuthSigner(load_private_key(RFC9421_JWK), DIRECTORY, expires_in=3600, legacy_signature_agent=True)
        nonce = "e8N7S2MFd/qrd6T2R3tdfAuuANngKI7LFtKYI/vowzk4lAZYadIX6wW25MwG7DCT9RUKAJ0qVkU0mEeLElW1qg=="
        assert signer.sign("https://example.com/", created=1735689600, nonce=nonce) == {
            "signature-agent": f'"{DIRECTORY}"',
            "signature-input": f'sig2=("@authority" "signature-agent");created=1735689600;keyid="{KEYID}";alg="ed25519";expires=1735693200;nonce="{nonce}";tag="web-bot-auth"',
            "signature": "sig2=:RgpOdhNGFX7UR38+uNNf79CsAQ/ll8H7FvrSoQyjUHMg0apFVJ691/TZIu4boservbg7ciRcoDnY0XLI4j/AAA==:",
        }

    def test_key_forms_give_the_same_keyid(self) -> None:
        """PEM, JWK dict, JWK JSON and key objects load the same key."""
        forms = [RFC9421_PEM, RFC9421_JWK, json.dumps(RFC9421_JWK), RFC9421_PEM.encode(), load_private_key(RFC9421_PEM)]
        assert {WebBotAuthSigner(load_private_key(f), DIRECTORY).keyid for f in forms} == {KEYID}

    def test_directory_holds_the_public_key_only(self) -> None:
        """The directory is a JWK Set without the private part."""
        signer = WebBotAuthSigner(load_private_key(RFC9421_JWK), DIRECTORY)
        assert signer.directory() == {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": RFC9421_JWK["x"], "kid": KEYID, "use": "sig"}]}
        assert "n4Ni" not in repr(signer)

    @pytest.mark.parametrize(
        "material",
        [
            {"kty": "OKP", "crv": "Ed25519", "x": RFC9421_JWK["x"]},
            {"kty": "EC", "crv": "P-256", "d": "abc"},
            "not a key",
            serialization.load_pem_private_key(
                b"-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgevZzL1gdAFr88hb2\nOF/2NxApJCzGCEDdfSp6VQO30hyhRANCAAQRWz+jn65BtOMvdyHKcvjBeBSDZH2r\n1RTwjmYSi9R/zpBnuQ4EiMnCqfMPWiZqB4QdbAd0E7oH50VpuZ1P087G\n-----END PRIVATE KEY-----\n",  # pragma: allowlist secret
                password=None,
            ).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        ],
        ids=["public-jwk", "ec-jwk", "text", "p256-pem"],
    )
    def test_rejects_keys_that_are_not_private_ed25519(self, material: Any) -> None:
        """Only private Ed25519 keys load."""
        with pytest.raises(ValueError):
            load_private_key(material)


class TestConfig:
    """Configuration checks fail before the plugin runs."""

    def test_missing_key_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An enabled plugin without a key does not load."""
        monkeypatch.delenv("WEB_BOT_AUTH_PRIVATE_KEY", raising=False)
        with pytest.raises(ValueError, match="WEB_BOT_AUTH_PRIVATE_KEY"):
            WebBotAuthPlugin(PluginConfig(name="w", kind="k", hooks=["tool_pre_invoke"], config={"signature_agent": DIRECTORY}))

    @pytest.mark.parametrize("url", ["http://example.com/dir", "https:///dir", "https://exämple.com/dir", "ftp://example.com"])
    def test_signature_agent_must_be_an_ascii_https_url(self, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
        """The Signature-Agent value is a structured-field string over https."""
        with pytest.raises(ValidationError):
            make_plugin(monkeypatch, signature_agent=url)

    @pytest.mark.parametrize("expires_in", [0, 86401])
    def test_expires_in_range(self, monkeypatch: pytest.MonkeyPatch, expires_in: int) -> None:
        """The draft recommends at most 24 hours."""
        with pytest.raises(ValidationError):
            make_plugin(monkeypatch, expires_in=expires_in)

    def test_key_from_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """private_key_file is used instead of the environment."""
        key_file = tmp_path / "wba.pem"
        key_file.write_text(RFC9421_PEM, encoding="utf-8")
        monkeypatch.delenv(ENV, raising=False)
        plugin = WebBotAuthPlugin(PluginConfig(name="w", kind="k", hooks=["tool_pre_invoke"], config={"signature_agent": DIRECTORY, "private_key_file": str(key_file)}))
        assert plugin.signer.keyid == KEYID


class TestToolPreInvoke:
    """Signing of outbound tool calls."""

    @pytest.mark.asyncio
    async def test_signs_mcp_tool_calls_to_the_gateway_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MCP tools go to gateway.url; existing headers stay and the signature verifies."""
        plugin = make_plugin(monkeypatch)
        payload = ToolPreInvokePayload(name="search", args={"q": "x"}, headers=HttpHeaderPayload(root={"authorization": "Bearer abc", "x-trace": "1"}))
        ctx = context(gateway=SimpleNamespace(url="https://mcp.shop.test:8443/mcp"), tool=SimpleNamespace(integration_type="MCP", url="https://mcp.shop.test:8443/mcp"))

        result = await plugin.tool_pre_invoke(payload, ctx)

        headers = result.modified_payload.headers.model_dump()
        assert headers["authorization"] == "Bearer abc" and headers["x-trace"] == "1"
        assert verify(headers, "mcp.shop.test:8443", plugin.signer.public_bytes()) == DIRECTORY
        assert result.metadata["web_bot_auth"] == {"signed": True, "authority": "mcp.shop.test:8443", "keyid": KEYID}

    @pytest.mark.asyncio
    async def test_signs_rest_tools_at_the_tool_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REST tools have no gateway; the tool URL is the destination."""
        plugin = make_plugin(monkeypatch)
        ctx = context(tool={"integration_type": "REST", "url": "https://api.example.test/v1/orders"})
        result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="orders", args={}), ctx)
        assert verify(result.modified_payload.headers.model_dump(), "api.example.test", plugin.signer.public_bytes()) == DIRECTORY

    @pytest.mark.asyncio
    async def test_replaces_signature_headers_from_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A forwarded Signature header never reaches the upstream next to the gateway's own."""
        plugin = make_plugin(monkeypatch)
        forged = {"Signature": "sig1=:AAAA:", "Signature-Input": 'sig1=("@authority")', "Signature-Agent": 'sig1="https://evil.test/"'}
        payload = ToolPreInvokePayload(name="t", args={}, headers=HttpHeaderPayload(root=forged))
        result = await plugin.tool_pre_invoke(payload, context(gateway={"url": "https://mcp.shop.test/mcp"}))
        headers = result.modified_payload.headers.model_dump()
        assert sorted(headers) == ["signature", "signature-agent", "signature-input"]
        assert verify(headers, "mcp.shop.test", plugin.signer.public_bytes()) == DIRECTORY

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata",
        [
            {"gateway": {"url": "https://other.test/mcp"}},
            {"gateway": {"url": "https://shop.test/mcp"}},
            {"gateway": {"url": "https://evilshop.test/mcp"}},
            {"gateway": {"url": "http://mcp.shop.test/mcp"}},
            {"tool": {"integration_type": "MCP", "url": "https://api.example.test/"}},
            {},
        ],
        ids=["other-host", "bare-parent", "suffix-lookalike", "plain-http", "mcp-tool-without-gateway", "no-destination"],
    )
    async def test_leaves_out_of_scope_calls_unsigned(self, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any]) -> None:
        """Hosts outside the list, plain http and unknown destinations are not signed."""
        plugin = make_plugin(monkeypatch)
        result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="t", args={}), context(**metadata))
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_no_hosts_signs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default empty host list keeps the plugin inert."""
        plugin = make_plugin(monkeypatch, hosts=[])
        result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="t", args={}), context(gateway={"url": "https://mcp.shop.test/"}))
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_loopback_http_only_when_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plain http is signed only for loopback hosts and only on request."""
        ctx = context(gateway={"url": "http://127.0.0.1:9000/mcp"})
        payload = ToolPreInvokePayload(name="t", args={})
        assert (await make_plugin(monkeypatch, hosts=["*"]).tool_pre_invoke(payload, ctx)).modified_payload is None
        plugin = make_plugin(monkeypatch, hosts=["*"], allow_insecure_loopback=True)
        result = await plugin.tool_pre_invoke(payload, ctx)
        assert verify(result.modified_payload.headers.model_dump(), "127.0.0.1:9000", plugin.signer.public_bytes()) == DIRECTORY

    @pytest.mark.asyncio
    async def test_each_call_gets_a_fresh_nonce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Signatures are not reused between calls."""
        plugin = make_plugin(monkeypatch)
        ctx = context(gateway={"url": "https://mcp.shop.test/mcp"})
        first = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="t", args={}), ctx)
        second = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="t", args={}), ctx)
        assert first.modified_payload.headers.model_dump()["signature"] != second.modified_payload.headers.model_dump()["signature"]


class TestAgentPreInvoke:
    """Signing of outbound A2A calls."""

    @pytest.mark.asyncio
    async def test_signs_a2a_calls_to_the_endpoint_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A2A agents go to a2a_agent.endpoint_url."""
        plugin = make_plugin(monkeypatch)
        payload = AgentPreInvokePayload(agent_id="agent-1", messages=[], headers=HttpHeaderPayload(root={"x-trace": "1"}))
        result = await plugin.agent_pre_invoke(payload, context(a2a_agent=SimpleNamespace(endpoint_url="https://agents.shop.test/a2a")))
        headers = result.modified_payload.headers.model_dump()
        assert headers["x-trace"] == "1"
        assert verify(headers, "agents.shop.test", plugin.signer.public_bytes()) == DIRECTORY

    @pytest.mark.asyncio
    async def test_out_of_scope_agent_is_unsigned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An agent outside the host list is not signed."""
        plugin = make_plugin(monkeypatch)
        payload = AgentPreInvokePayload(agent_id="agent-1", messages=[])
        result = await plugin.agent_pre_invoke(payload, context(a2a_agent={"endpoint_url": "https://agents.other.test/a2a"}))
        assert result.modified_payload is None
