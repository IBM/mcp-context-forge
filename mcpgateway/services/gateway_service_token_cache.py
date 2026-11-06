# -*- coding: utf-8 -*-
# mcpgateway/services/gateway_service_token_cache.py
"""Location: ./mcpgateway/services/gateway_service_token_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Cache for per-gateway service tokens, such as the token-exchange discovery credential.
Kept apart from the per-user ``TokenExchangeCache`` so that a user lookup can never
return a service token, and a service lookup can never return a user token.
"""

# Standard
import asyncio
import hashlib
import json
from typing import Any, Dict, Optional, Set

# First-Party
from mcpgateway.services.token_exchange_cache import _BearerTokenStore

_FINGERPRINT_KEYS = ("token_url", "client_id", "token_endpoint_auth_method", "client_secret", "private_key", "private_key_jwt_kid", "token_endpoint_auth_signing_alg")
_KEY_PREFIX = "gateway_service_token"


def service_token_fingerprint(effective_config: Dict[str, Any]) -> str:
    """Return a SHA-256 fingerprint of the client-auth settings that produce a service token.

    The fingerprint covers the stored ciphertext of the secret or private key, so a
    rotation through the API or UI changes the cache key on every worker.

    Args:
        effective_config: Effective client-credentials config for the service token.

    Returns:
        Hex SHA-256 digest.

    Examples:
        >>> a = service_token_fingerprint({"client_id": "c", "scopes": ["b", "a"]})
        >>> a == service_token_fingerprint({"client_id": "c", "scopes": ["a", "b"]})
        True
        >>> a == service_token_fingerprint({"client_id": "other", "scopes": ["a", "b"]})
        False
    """
    material = {key: effective_config.get(key) for key in _FINGERPRINT_KEYS}
    material["scopes"] = sorted(effective_config.get("scopes") or [])
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class GatewayServiceTokenCache(_BearerTokenStore):
    """Stores service tokens keyed by purpose, gateway, and config fingerprint.

    The key is ``gateway_service_token:{purpose}:{sha256(gateway_id)}:{fingerprint}``.
    A config change on any worker misses the old entry without a cross-worker
    message. ``invalidate()`` removes every entry of a gateway, locally and in Redis.

    SECURITY: cached values are bearer tokens. Never log a cached value.
    """

    _log_name = "GatewayServiceTokenCache"

    @staticmethod
    def _gateway_prefix(gateway_id: str) -> str:
        """Return the key prefix shared by every entry of one gateway, across purposes.

        Args:
            gateway_id: Gateway identifier.

        Returns:
            Key prefix ending in ``:``.
        """
        return f"{hashlib.sha256(str(gateway_id).encode('utf-8')).hexdigest()}:"

    @classmethod
    def _key(cls, purpose: str, gateway_id: str, fingerprint: str) -> str:
        """Build the namespaced key for one service token.

        Args:
            purpose: Token purpose, for example ``discovery``.
            gateway_id: Gateway identifier.
            fingerprint: Output of ``service_token_fingerprint()``.

        Returns:
            Namespaced cache key.

        Raises:
            ValueError: If ``purpose`` or ``gateway_id`` is empty, or ``purpose`` contains ``:``.
        """
        if not purpose or ":" in purpose:
            raise ValueError("Service token cache requires a purpose without ':'")
        if not gateway_id:
            raise ValueError("Service token cache requires a gateway id")
        return f"{_KEY_PREFIX}:{purpose}:{cls._gateway_prefix(gateway_id)}{fingerprint}"

    def lock(self, purpose: str, gateway_id: str, fingerprint: str) -> asyncio.Lock:
        """Return the single-flight lock for this key.

        Args:
            purpose: Token purpose.
            gateway_id: Gateway identifier.
            fingerprint: Config fingerprint.

        Returns:
            The ``asyncio.Lock`` instance associated with this key.
        """
        return self._lock_for_key(self._key(purpose, gateway_id, fingerprint))

    async def get(self, purpose: str, gateway_id: str, fingerprint: str) -> Optional[str]:
        """Return a cached service token if present and still inside its serve window.

        Args:
            purpose: Token purpose.
            gateway_id: Gateway identifier.
            fingerprint: Config fingerprint.

        Returns:
            The cached token, or ``None`` on a miss or expiry.
        """
        return await self._get_key(self._key(purpose, gateway_id, fingerprint))

    async def set(self, purpose: str, gateway_id: str, fingerprint: str, token: str, expires_in: int) -> None:
        """Cache a service token.

        Args:
            purpose: Token purpose.
            gateway_id: Gateway identifier.
            fingerprint: Config fingerprint.
            token: The access token to cache.
            expires_in: Token lifetime in seconds as returned by the token endpoint.
        """
        await self._set_key(self._key(purpose, gateway_id, fingerprint), token, expires_in)

    async def invalidate(self, gateway_id: str) -> None:
        """Remove every cached service token of a gateway, for every purpose and fingerprint.

        Args:
            gateway_id: Gateway identifier.
        """
        if not gateway_id:
            return
        gateway_prefix = self._gateway_prefix(gateway_id)
        # Key layout: <prefix>:<purpose>:<gateway hash>:<fingerprint>. Purpose never contains ":".
        stale: Set[str] = {key for key in self._mem if key.split(":", 2)[-1].startswith(gateway_prefix)}
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                async for key in self._redis.scan_iter(match=f"{_KEY_PREFIX}:*:{gateway_prefix}*"):
                    stale.add(key.decode("utf-8") if isinstance(key, bytes) else key)
                self._note_redis_ok()
            except Exception as e:  # pragma: no cover - defensive
                self._note_redis_failure("scan", e)
        for key in stale:
            await self._delete_key(key)
