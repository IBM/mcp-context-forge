# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openfga_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Async HTTP client for the OpenFGA API.

Every provider method is a coroutine, so the client speaks HTTP with
``httpx.AsyncClient`` and never blocks the event loop. Authentication is
the preshared key sent as ``Authorization: Bearer <key>``. Transport
errors surface as :class:`OpenFgaUnavailable` so callers can fail
closed with one exception type.
"""

# Standard
import logging
from pathlib import Path
from typing import Any, Optional

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class OpenFgaUnavailable(Exception):
    """Raised when the OpenFGA API cannot answer a request."""


def resolve_openfga_token() -> str:
    """Resolve the preshared key from settings.

    The token file wins over the literal value when both are set. The
    file content is stripped of surrounding whitespace.

    Returns:
        The preshared key, or an empty string when neither source is set.
    """
    if settings.openfga_api_token_file:
        try:
            return Path(settings.openfga_api_token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.error("Failed to read OPENFGA_API_TOKEN_FILE: %s", exc)
            return ""
    return settings.openfga_api_token.get_secret_value()


class OpenFgaClient:
    """Async client for the OpenFGA HTTP API."""

    def __init__(self, api_url: Optional[str] = None, api_token: Optional[str] = None, timeout: Optional[float] = None) -> None:
        """Create a client bound to one OpenFGA server.

        Args:
            api_url: Base URL; defaults to ``Settings.openfga_api_url``.
            api_token: Preshared key; defaults to the resolved settings token.
            timeout: Request timeout in seconds; defaults to the setting.
        """
        self._api_url = (api_url or settings.openfga_api_url).rstrip("/")
        self._api_token = api_token if api_token is not None else resolve_openfga_token()
        self._timeout = timeout if timeout is not None else settings.openfga_timeout_seconds

    async def _request(self, method: str, path: str, json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Issue one API request and return the decoded body.

        Args:
            method: HTTP method.
            path: API path below the server root.
            json: Optional JSON body.

        Returns:
            The decoded JSON response.

        Raises:
            OpenFgaUnavailable: On connection errors, timeouts, and
                non-2xx responses.
        """
        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, f"{self._api_url}{path}", json=json, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise OpenFgaUnavailable(f"OpenFGA request failed: {exc}") from exc

    async def health(self) -> bool:
        """Probe the server health endpoint without authentication.

        Returns:
            True when the server answers 200 on /healthz.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._api_url}/healthz")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_stores(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """List stores, optionally filtered by exact name.

        Args:
            name: Store name to match.

        Returns:
            Matching store objects with their ``id`` fields.
        """
        body = await self._request("GET", "/stores")
        stores = body.get("stores", [])
        return [s for s in stores if name is None or s.get("name") == name]

    async def create_store(self, name: str) -> dict[str, Any]:
        """Create a store.

        Args:
            name: Store name.

        Returns:
            The created store object.
        """
        return await self._request("POST", "/stores", {"name": name})

    async def latest_model(self) -> Optional[dict[str, Any]]:
        """Return the store's latest authorization model.

        Returns:
            The model object with its type definitions, or None when the
            store has no model yet.
        """
        body = await self._request("GET", f"/stores/{settings.openfga_store_id}/authorization-models")
        models = body.get("authorization_models", [])
        return models[0] if models else None

    async def write_model(self, type_definitions: list[dict[str, Any]]) -> str:
        """Write an authorization model to the configured store.

        Args:
            type_definitions: Type definitions in the OpenFGA JSON form.

        Returns:
            The new authorization model id.
        """
        store = settings.openfga_store_id
        body = await self._request("POST", f"/stores/{store}/authorization-models", {"schema_version": "1.1", "type_definitions": type_definitions, "conditions": {}})
        return str(body["authorization_model_id"])

    async def write_tuples(self, writes: list[dict[str, str]], deletes: list[dict[str, str]]) -> None:
        """Apply tuple writes and deletes in one transaction.

        Args:
            writes: Tuple keys to write.
            deletes: Tuple keys to delete.

        Raises:
            OpenFgaUnavailable: When the transaction is rejected.
        """
        if not writes and not deletes:
            return
        payload: dict[str, Any] = {}
        if writes:
            payload["writes"] = {"tuple_keys": writes}
        if deletes:
            payload["deletes"] = {"tuple_keys": deletes}
        await self._request("POST", f"/stores/{settings.openfga_store_id}/write", payload)

    async def read_tuples(self, object_filter: Optional[str] = None) -> list[dict[str, Any]]:
        """Read stored tuples, optionally filtered by object prefix.

        Args:
            object_filter: Exact object (``type:id``) to filter by.

        Returns:
            Stored tuple keys with their relations.
        """
        body: dict[str, Any] = {}
        if object_filter:
            body = {"tuple_key": {"object": object_filter}}
        result = await self._request("POST", f"/stores/{settings.openfga_store_id}/read", body)
        return [item.get("key", item) for item in result.get("tuples", [])]

    async def check(self, user: str, relation: str, obj: str, contextual_tuples: Optional[list[dict[str, str]]] = None, model_id: Optional[str] = None) -> bool:
        """Answer one authorization question.

        Args:
            user: User reference such as ``user:anne`` or ``role:dev#assignee``.
            relation: Relation name on the object type.
            obj: Object reference such as ``tool:42`` or ``tool:*``.
            contextual_tuples: Optional per-request tuples.
            model_id: Pin the authorization model for the check.

        Returns:
            True when OpenFGA allows the relationship.
        """
        payload: dict[str, Any] = {"tuple_key": {"user": user, "relation": relation, "object": obj}}
        if contextual_tuples:
            payload["contextual_tuples"] = {"tuple_keys": contextual_tuples}
        if model_id or settings.openfga_model_id:
            payload["authorization_model_id"] = model_id or settings.openfga_model_id
        body = await self._request("POST", f"/stores/{settings.openfga_store_id}/check", payload)
        return bool(body.get("allowed", False))

    async def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        """List objects of one type related to the user.

        Args:
            user: User reference.
            relation: Relation name.
            object_type: Type name such as ``tool``.

        Returns:
            Object references the user holds the relation on.
        """
        payload = {"user": user, "relation": relation, "type": object_type}
        if settings.openfga_model_id:
            payload["authorization_model_id"] = settings.openfga_model_id
        body = await self._request("POST", f"/stores/{settings.openfga_store_id}/list-objects", payload)
        return list(body.get("objects", []))
