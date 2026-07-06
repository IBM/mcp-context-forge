# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context_redis_signing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Unit tests for the Redis-transit forward-envelope signing helpers in ``auth_context``.

These protect the session-affinity Redis pub/sub hop: the publisher signs the
*whole* forwarded envelope (identity + operation + response_channel) and the
consumer verifies it before dispatch. Signing only the identity would let a Redis
writer replay a valid signature with a different method/path/body/response_channel
(CWE-347), so the tests pin that every operation field is bound and that a
redirected response channel is rejected.
"""

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.auth_context import (
    encode_internal_mcp_auth_context,
    FORWARD_SIG_FIELD,
    sign_redis_forward_envelope,
    verify_redis_forward_envelope,
)

_CTX = encode_internal_mcp_auth_context({"email": "u@example.com", "is_authenticated": True, "is_admin": False})
_SID = "abc123def456"  # pragma: allowlist secret


def _rpc_envelope():
    """A representative signed rpc_forward envelope (matches forward_request_to_owner)."""
    env = {
        "type": "rpc_forward",
        "method": "tools/call",
        "params": {"name": "do", "arguments": {"a": 1}},
        "req_id": 7,
        "headers": {"x-mcp-session-id": _SID},
        "response_channel": "mcpgw:pool_rpc_response:chan-1",
        "mcp_session_id": _SID,
        "auth_context": _CTX,
    }
    env[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(env)
    return env


def _http_envelope():
    """A representative signed http_forward envelope (matches forward_to_owner)."""
    env = {
        "type": "http_forward",
        "response_channel": "mcpgw:pool_http_response:chan-1",
        "mcp_session_id": _SID,
        "method": "POST",
        "path": "/servers/abc123/mcp",
        "query_string": "",
        "headers": {"content-type": "application/json"},
        "body": b'{"jsonrpc":"2.0","method":"tools/list","id":1}'.hex(),
        "original_worker": "worker-1",
        "timestamp": 123.0,
        "auth_context": _CTX,
    }
    env[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(env)
    return env


def _wire(env):
    """Round-trip the envelope through JSON exactly as Redis pub/sub does."""
    return orjson.loads(orjson.dumps(env))


def test_rpc_envelope_round_trips():
    """A signed rpc envelope verifies after an orjson round-trip (canonicalization holds)."""
    assert verify_redis_forward_envelope(_wire(_rpc_envelope())) is True


def test_http_envelope_round_trips():
    """A signed http envelope verifies after an orjson round-trip (canonicalization holds)."""
    assert verify_redis_forward_envelope(_wire(_http_envelope())) is True


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("method", "resources/read"),
        ("params", {"name": "evil", "arguments": {}}),
        ("req_id", 9999),
        ("headers", {"x-mcp-session-id": "attacker"}),
        ("response_channel", "mcpgw:pool_rpc_response:attacker"),  # response redirection
        ("mcp_session_id", "attacker-session"),
        ("auth_context", encode_internal_mcp_auth_context({"is_admin": True, "is_authenticated": True})),
    ],
)
def test_rpc_field_tamper_is_rejected(field, new_value):
    """Mutating any rpc operation field (incl. response_channel) invalidates the signature."""
    env = _wire(_rpc_envelope())
    env[field] = new_value
    assert verify_redis_forward_envelope(env) is False


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("method", "DELETE"),
        ("path", "/servers/other/mcp"),
        ("query_string", "x=1"),
        ("headers", {"content-type": "text/plain"}),
        ("body", b'{"jsonrpc":"2.0","method":"tools/call","id":1}'.hex()),
        ("response_channel", "mcpgw:pool_http_response:attacker"),  # response redirection
        ("mcp_session_id", "attacker-session"),
        ("auth_context", encode_internal_mcp_auth_context({"is_admin": True, "is_authenticated": True})),
    ],
)
def test_http_field_tamper_is_rejected(field, new_value):
    """Mutating any http operation field (incl. response_channel) invalidates the signature."""
    env = _wire(_http_envelope())
    env[field] = new_value
    assert verify_redis_forward_envelope(env) is False


def test_missing_forward_sig_is_rejected():
    """An envelope with no forward_sig fails closed."""
    env = _wire(_rpc_envelope())
    del env[FORWARD_SIG_FIELD]
    assert verify_redis_forward_envelope(env) is False


def test_non_string_forward_sig_is_rejected():
    """A non-string forward_sig fails closed rather than raising."""
    env = _wire(_rpc_envelope())
    env[FORWARD_SIG_FIELD] = 12345
    assert verify_redis_forward_envelope(env) is False


def test_empty_forward_sig_is_rejected():
    """An empty forward_sig fails closed."""
    env = _wire(_rpc_envelope())
    env[FORWARD_SIG_FIELD] = ""
    assert verify_redis_forward_envelope(env) is False


def test_garbage_forward_sig_is_rejected():
    """A well-formed-looking but wrong signature is rejected."""
    env = _wire(_rpc_envelope())
    env[FORWARD_SIG_FIELD] = "deadbeef" * 8
    assert verify_redis_forward_envelope(env) is False


def test_legacy_auth_context_sig_alone_is_rejected():
    """An old identity-only ``auth_context_sig`` (no forward_sig) does not verify.

    Guards against silently accepting a pre-envelope publisher during a mixed-version
    rollout: the narrow signature is gone and must not be honored.
    """
    env = {
        "type": "rpc_forward",
        "method": "tools/call",
        "params": {},
        "mcp_session_id": _SID,
        "response_channel": "mcpgw:pool_rpc_response:chan-1",
        "auth_context": _CTX,
        "auth_context_sig": "deadbeef" * 8,
    }
    assert verify_redis_forward_envelope(_wire(env)) is False


def test_wrong_secret_is_rejected(monkeypatch):
    """A signature made under a different secret does not verify (pins the keying)."""
    env = _rpc_envelope()  # signed under the current secret
    monkeypatch.setattr("mcpgateway.auth_context._auth_encryption_secret_value", lambda: "a-different-secret")
    assert verify_redis_forward_envelope(_wire(env)) is False


def test_signature_is_deterministic_for_same_inputs():
    """Same envelope yields the same signature under the same secret."""
    base = {"type": "rpc_forward", "method": "tools/call", "mcp_session_id": _SID, "auth_context": _CTX}
    assert sign_redis_forward_envelope(dict(base)) == sign_redis_forward_envelope(dict(base))


def test_signature_is_key_order_independent():
    """Key insertion order does not change the signature (sorted-keys canonicalization)."""
    a = {"type": "rpc_forward", "method": "tools/call", "mcp_session_id": _SID, "auth_context": _CTX}
    b = {"auth_context": _CTX, "mcp_session_id": _SID, "method": "tools/call", "type": "rpc_forward"}
    assert sign_redis_forward_envelope(a) == sign_redis_forward_envelope(b)
