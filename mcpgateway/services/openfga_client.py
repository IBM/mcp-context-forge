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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


_MAX_TUPLES_PER_WRITE = 100  # engine cap per write request (exceeded_entity_limit)


class OpenFgaUnavailable(Exception):
    """Raised when the OpenFGA API cannot answer a request."""


def _utcnow_rfc3339() -> str:
    """Return the current UTC time as an RFC 3339 string.

    Returns:
        The timestamp the engine compares in temporal conditions.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200]
            raise OpenFgaUnavailable(f"OpenFGA request failed: {exc} body={detail}") from exc
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

    async def write_model(self, type_definitions: list[dict[str, Any]], conditions: Optional[dict[str, Any]] = None) -> str:
        """Write an authorization model to the configured store.

        Args:
            type_definitions: Type definitions in the OpenFGA JSON form.
            conditions: Condition definitions in the OpenFGA JSON form.

        Returns:
            The new authorization model id.
        """
        store = settings.openfga_store_id
        body = await self._request("POST", f"/stores/{store}/authorization-models", {"schema_version": "1.1", "type_definitions": type_definitions, "conditions": conditions or {}})
        return str(body["authorization_model_id"])

    async def write_tuples(self, writes: list[dict[str, str]], deletes: list[dict[str, str]]) -> None:
        """Apply tuple writes and deletes in capped batches.

        Deletes apply before writes so a tuple whose condition changed
        can be removed and rewritten in one call. Both directions ship
        in chunks of 100 (the engine's exceeded_entity_limit cap).
        Batches apply sequentially: a later failure leaves earlier
        batches applied, which the reconciliation loop converges.
        Multiple gateway workers reconcile concurrently and can compute
        the same diff. A worker that loses the write race receives
        ``write_failed_due_to_invalid_input`` naming a tuple that the
        winner already wrote. That outcome satisfies the reconciliation
        goal, so this method treats it as success and proceeds.

        Args:
            writes: Tuple keys to write.
            deletes: Tuple keys to delete.

        Raises:
            OpenFgaUnavailable: When a batch is rejected for any other reason.
        """
        for start in range(0, len(deletes), _MAX_TUPLES_PER_WRITE):
            batch = deletes[start : start + _MAX_TUPLES_PER_WRITE]
            try:
                await self._request("POST", f"/stores/{settings.openfga_store_id}/write", {"deletes": {"tuple_keys": batch}})
            except OpenFgaUnavailable as exc:
                if "already exists" not in str(exc) and "Invalid tuple delete" not in str(exc):
                    raise
                logger.info("OpenFGA delete race: %d tuple(s) in this batch already absent (another worker deleted them)", len(batch))
        for start in range(0, len(writes), _MAX_TUPLES_PER_WRITE):
            batch = writes[start : start + _MAX_TUPLES_PER_WRITE]
            try:
                await self._request("POST", f"/stores/{settings.openfga_store_id}/write", {"writes": {"tuple_keys": batch}})
            except OpenFgaUnavailable as exc:
                if "already exists" not in str(exc):
                    raise
                logger.info("OpenFGA write race: %d tuple(s) in this batch already stored (another worker wrote them)", len(batch))

    async def read_tuples(self, object_filter: Optional[str] = None, user_filter: Optional[str] = None) -> list[dict[str, Any]]:
        """Read stored tuples, optionally filtered by object or user.

        Follows every continuation token: the read endpoint pages its
        results, and a partial read makes the resync diff re-write
        existing tuples, which the engine rejects.

        Args:
            object_filter: Exact object (``type:id``) to filter by.
            user_filter: Exact user reference (``user:<id>``) to filter by.

        Returns:
            Stored tuple entries: each carries ``key`` plus the optional
            ``condition`` the engine attached at write time.
        """
        tuples: list[dict[str, Any]] = []
        continuation: Optional[str] = None
        filter_key: dict[str, str] = {}
        if object_filter:
            filter_key["object"] = object_filter
        if user_filter:
            filter_key["user"] = user_filter
        while True:
            body: dict[str, Any] = {"tuple_key": filter_key} if filter_key else {}
            if continuation:
                body["continuation_token"] = continuation
            result = await self._request("POST", f"/stores/{settings.openfga_store_id}/read", body)
            tuples.extend(result.get("tuples", []))
            continuation = result.get("continuation_token") or None
            if not continuation:
                return tuples

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
        payload: dict[str, Any] = {"tuple_key": {"user": user, "relation": relation, "object": obj}, "context": {"current_time": _utcnow_rfc3339()}}
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
        payload = {"user": user, "relation": relation, "type": object_type, "context": {"current_time": _utcnow_rfc3339()}}
        if settings.openfga_model_id:
            payload["authorization_model_id"] = settings.openfga_model_id
        body = await self._request("POST", f"/stores/{settings.openfga_store_id}/list-objects", payload)
        return list(body.get("objects", []))
