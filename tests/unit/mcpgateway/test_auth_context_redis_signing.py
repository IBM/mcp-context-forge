# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context_redis_signing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Unit tests for the Redis-transit auth-context signing helpers in ``auth_context``.

These protect the session-affinity Redis pub/sub hop: the publisher signs the
encoded auth context (bound to its ``mcp_session_id``) and the consumer verifies
before re-stamping it with the runtime-auth token. Without this, the owner worker
is a signing oracle for any context a Redis writer injects.
"""

# First-Party
from mcpgateway.auth_context import encode_internal_mcp_auth_context, sign_redis_auth_context, verify_redis_auth_context

_CTX = encode_internal_mcp_auth_context({"email": "u@example.com", "is_authenticated": True, "is_admin": False})
_SID = "abc123def456"


def test_valid_signature_round_trips():
    """A signature produced by sign_* verifies for the same (session, context)."""
    sig = sign_redis_auth_context(_SID, _CTX)
    assert verify_redis_auth_context(_SID, _CTX, sig) is True


def test_tampered_context_is_rejected():
    """A different context (e.g. a forged admin context) does not verify against the original signature."""
    sig = sign_redis_auth_context(_SID, _CTX)
    forged = encode_internal_mcp_auth_context({"is_admin": True, "is_authenticated": True})
    assert verify_redis_auth_context(_SID, forged, sig) is False


def test_wrong_session_id_is_rejected():
    """A signature bound to one session must not verify under another (blocks cross-session replay)."""
    sig = sign_redis_auth_context(_SID, _CTX)
    assert verify_redis_auth_context("other-session", _CTX, sig) is False


def test_missing_signature_is_rejected():
    """An empty signature fails closed."""
    assert verify_redis_auth_context(_SID, _CTX, "") is False


def test_garbage_signature_is_rejected():
    """A well-formed-looking but wrong signature is rejected."""
    assert verify_redis_auth_context(_SID, _CTX, "deadbeef" * 8) is False


def test_signature_is_deterministic_for_same_inputs():
    """Same (session, context) yields the same signature under the same secret."""
    assert sign_redis_auth_context(_SID, _CTX) == sign_redis_auth_context(_SID, _CTX)


def test_distinct_sessions_produce_distinct_signatures():
    """Session binding changes the signature, so a captured sig cannot be lifted onto another session."""
    assert sign_redis_auth_context("session-a", _CTX) != sign_redis_auth_context("session-b", _CTX)
