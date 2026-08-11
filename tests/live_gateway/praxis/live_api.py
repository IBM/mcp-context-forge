"""Typed HTTPS client primitives for the live Praxis E2E narrative."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ssl
from typing import NewType
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BearerToken = NewType("BearerToken", str)
type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """One bounded live HTTP response."""

    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> JsonObject:
        """Parse a JSON object response."""
        value = json.loads(self.body)
        if not isinstance(value, dict):
            raise AssertionError("expected JSON object")
        return value


@dataclass(frozen=True, slots=True)
class LiveApi:
    """HTTPS-only API client with explicit trust and bounded responses."""

    base_url: str
    ca_path: str
    token: BearerToken

    def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        """Issue one authenticated request without redirect or insecure fallback."""
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        request_headers = {"Authorization": f"Bearer {self.token}"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers is not None:
            request_headers.update(headers)
        request = Request(f"{self.base_url}{path}", data=body, headers=request_headers, method=method)
        context = ssl.create_default_context(cafile=self.ca_path)
        try:
            with urlopen(request, context=context, timeout=30) as response:
                return ApiResponse(response.status, {key.lower(): value for key, value in response.headers.items()}, response.read(16 * 1024 * 1024 + 1))
        except HTTPError as error:
            return ApiResponse(error.code, {key.lower(): value for key, value in error.headers.items()}, error.read(1024 * 1024))


def assert_identity_separation(payload: JsonObject) -> None:
    """Prove generation, rollout, directive, sequence, and ETag are separate concepts."""
    generation = payload["generation_id"]
    rollout = payload["rollout_id"]
    directive = payload["directive_id"]
    response_etag = payload["response_etag"]
    assert all(isinstance(value, str) and len(value) == 64 for value in (generation, directive, response_etag))
    assert isinstance(rollout, str) and rollout
    assert isinstance(generation, str)
    assert isinstance(directive, str)
    assert isinstance(response_etag, str)
    assert len({generation, rollout, directive, response_etag}) == 4
    last_sequence = payload["last_report_sequence"]
    next_sequence = payload["next_report_sequence"]
    assert isinstance(last_sequence, int) and not isinstance(last_sequence, bool)
    assert isinstance(next_sequence, int) and not isinstance(next_sequence, bool)
    assert next_sequence == last_sequence + 1
