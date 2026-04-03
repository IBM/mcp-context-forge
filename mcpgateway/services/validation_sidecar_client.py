# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/validation_sidecar_client.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Validation sidecar client for framed Unix domain socket requests.
"""

# Standard
import asyncio
import json
import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

FRAME_PREFIX = struct.Struct(">I")
METADATA_PREFIX = struct.Struct(">I")
MAX_FRAME_SIZE = 16 * 1024 * 1024
MAX_REQUEST_BODY_SIZE = 1 * 1024 * 1024


class ValidationSidecarError(Exception):
    """Base error for validation sidecar transport and protocol failures."""

    status_code = 503

    def __init__(self, message: str) -> None:
        """Initialize the error with a user-facing message.

        Args:
            message: Human-readable error detail.
        """
        super().__init__(message)
        self.message = message


class ValidationSidecarTransportError(ValidationSidecarError):
    """Raised when the sidecar cannot be reached or the connection fails."""


class ValidationSidecarTimeoutError(ValidationSidecarTransportError):
    """Raised when a sidecar operation exceeds the configured timeout."""


class ValidationSidecarProtocolError(ValidationSidecarError):
    """Raised when the sidecar response is malformed or cannot be decoded."""


class ValidationSidecarValidationError(ValidationSidecarError):
    """Raised when the sidecar rejects a request body."""

    status_code = 422

    def __init__(self, message: str, *, key: str | None = None, error_type: str | None = None, detail: str | None = None) -> None:
        """Initialize the validation error with sidecar rejection details.

        Args:
            message: Human-readable validation failure message.
            key: Rejected key name reported by the sidecar.
            error_type: Rejection category reported by the sidecar.
            detail: Raw detail string returned by the sidecar.
        """
        super().__init__(message)
        self.key = key
        self.error_type = error_type
        self.detail = detail


def encode_frame(payload: bytes) -> bytes:
    """Encode a payload with a 4-byte big-endian length prefix.

    Args:
        payload: Unframed payload bytes.

    Returns:
        The framed byte sequence.

    Raises:
        ValidationSidecarProtocolError: If the payload exceeds the maximum frame size.
    """
    if len(payload) > MAX_FRAME_SIZE:
        raise ValidationSidecarProtocolError(f"Frame payload exceeds maximum size of {MAX_FRAME_SIZE} bytes")
    return FRAME_PREFIX.pack(len(payload)) + payload


def decode_frame(frame: bytes) -> bytes:
    """Decode a 4-byte big-endian framed payload.

    Args:
        frame: Length-prefixed frame bytes.

    Returns:
        The decoded payload bytes.

    Raises:
        ValidationSidecarProtocolError: If the frame is malformed or length mismatched.
    """
    if len(frame) < FRAME_PREFIX.size:
        raise ValidationSidecarProtocolError("Framed payload is too short to contain a length prefix")

    expected_length = FRAME_PREFIX.unpack(frame[: FRAME_PREFIX.size])[0]
    payload = frame[FRAME_PREFIX.size :]
    if len(payload) != expected_length:
        raise ValidationSidecarProtocolError(
            f"Framed payload length mismatch: expected {expected_length} bytes, received {len(payload)} bytes",
        )
    return payload


@dataclass(frozen=True, slots=True)
class ValidationSidecarRequest:
    """Typed helper for the validation sidecar request envelope."""

    raw_body_len: int
    max_param_length: int
    dangerous_patterns: tuple[str, ...]
    request_id: str | None = None

    @classmethod
    def from_body(
        cls,
        body: bytes,
        *,
        max_param_length: int,
        dangerous_patterns: Sequence[str],
        request_id: str | None = None,
        parser: str | None = None,
        allow_parser_selection: bool = False,
    ) -> "ValidationSidecarRequest":
        """Build a request envelope from raw request-body bytes.

        Args:
            body: Raw JSON request body bytes.
            max_param_length: Maximum allowed string length.
            dangerous_patterns: Regex patterns to enforce.
            request_id: Optional request correlation id.
            parser: Deprecated parser override that is no longer supported.
            allow_parser_selection: Deprecated benchmark flag retained for call compatibility.

        Returns:
            A sidecar request envelope instance.

        Raises:
            ValueError: If the body is too large or parser selection is requested.
        """
        if len(body) > MAX_REQUEST_BODY_SIZE:
            raise ValueError(f"request body exceeds maximum size of {MAX_REQUEST_BODY_SIZE} bytes")
        if parser is not None:
            raise ValueError(f"unsupported parser selection: {parser}")

        return cls(
            raw_body_len=len(body),
            max_param_length=max_param_length,
            dangerous_patterns=tuple(dangerous_patterns),
            request_id=request_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable request envelope.

        Returns:
            A dictionary ready for JSON serialization.
        """
        payload: dict[str, Any] = {
            "raw_body_len": self.raw_body_len,
            "max_param_length": self.max_param_length,
            "dangerous_patterns": self.dangerous_patterns,
        }
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        return payload

    def to_json_bytes(self) -> bytes:
        """Serialize the request envelope to canonical JSON bytes.

        Returns:
            Canonical UTF-8 JSON bytes for the request envelope.
        """
        return json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ValidationSidecarResponse:
    """Typed helper for the validation sidecar response envelope."""

    ok: bool
    key: str | None = None
    error_type: str | None = None
    detail: str | None = None

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "ValidationSidecarResponse":
        """Decode a JSON response envelope.

        Args:
            payload: Raw UTF-8 JSON response bytes.

        Returns:
            A parsed response envelope instance.

        Raises:
            ValidationSidecarProtocolError: If the response JSON is malformed.
        """
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationSidecarProtocolError("Malformed sidecar response: invalid JSON") from exc

        if not isinstance(decoded, dict):
            raise ValidationSidecarProtocolError("Malformed sidecar response: expected a JSON object")

        ok = decoded.get("ok")
        if not isinstance(ok, bool):
            raise ValidationSidecarProtocolError("Malformed sidecar response: missing boolean ok field")

        if ok:
            return cls(ok=True)

        key = decoded.get("key")
        error_type = decoded.get("error_type")
        detail = decoded.get("detail")
        if not isinstance(key, str) or not isinstance(error_type, str) or not isinstance(detail, str):
            raise ValidationSidecarProtocolError("Malformed sidecar response: rejected responses must include key, error_type, and detail strings")
        return cls(ok=False, key=key, error_type=error_type, detail=detail)


@dataclass(slots=True)
class _ConnectionState:
    """Holds a pooled reader, writer, and per-connection request lock."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    lock: asyncio.Lock


class ValidationSidecarClient:
    """Async client for framed validation requests over a Unix domain socket."""

    def __init__(self, uds_path: str, *, timeout_seconds: float, pool_size: int = 2) -> None:
        """Initialize a pooled validation-sidecar client.

        Args:
            uds_path: Absolute Unix domain socket path for the sidecar.
            timeout_seconds: Per-operation timeout in seconds.
            pool_size: Maximum number of pooled socket connections.

        Raises:
            ValueError: If the pool size, timeout, or UDS path is invalid.
        """
        if pool_size < 1:
            raise ValueError("pool_size must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        uds = Path(uds_path).expanduser()
        if not uds.is_absolute():
            raise ValueError("uds_path must be an absolute path")

        self._uds_path = str(uds)
        self._timeout_seconds = timeout_seconds
        self._pool_size = pool_size
        self._connections: list[_ConnectionState | None] = [None] * pool_size
        self._slot_locks = [asyncio.Lock() for _ in range(pool_size)]
        self._pool_lock = asyncio.Lock()
        self._next_index = 0
        self._request_metadata_cache: dict[tuple[int, tuple[str, ...]], bytes] = {}

    async def __aenter__(self) -> "ValidationSidecarClient":
        """Enter an async context manager for the client.

        Returns:
            The client instance itself.
        """
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async context manager and close pooled connections.

        Args:
            exc_type: Raised exception type, if any.
            exc: Raised exception instance, if any.
            tb: Raised traceback, if any.
        """
        await self.aclose()

    async def aclose(self) -> None:
        """Close all pooled connections."""
        for index, connection in enumerate(self._connections):
            if connection is None:
                continue
            await self._close_writer(connection.writer)
            self._connections[index] = None

    async def validate_json_body(
        self,
        body: bytes,
        *,
        max_param_length: int,
        dangerous_patterns: Sequence[str],
        request_id: str | None = None,
    ) -> None:
        """Validate a request body by round-tripping it through the sidecar.

        Args:
            body: Raw JSON request body bytes.
            max_param_length: Maximum allowed string length.
            dangerous_patterns: Regex patterns to enforce.
            request_id: Optional request correlation id.

        Raises:
            ValidationSidecarProtocolError: If the sidecar response is malformed.
            ValidationSidecarTimeoutError: If a sidecar operation times out.
            ValidationSidecarTransportError: If the sidecar cannot be reached.
            ValidationSidecarValidationError: If the sidecar rejects the payload.
        """
        request_payload = self._build_request_payload_bytes(
            body,
            max_param_length=max_param_length,
            dangerous_patterns=dangerous_patterns,
            request_id=request_id,
        )
        request_frame = encode_frame(request_payload)

        last_error: Exception | None = None
        for attempt in range(2):
            connection_index = await self._reserve_connection_index()
            try:
                connection = await self._ensure_connection(connection_index)
            except ValidationSidecarTransportError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise

            async with connection.lock:
                try:
                    await self._write_frame(connection.writer, request_frame)
                    response_frame = await self._read_frame(connection.reader)
                    response = ValidationSidecarResponse.from_json_bytes(response_frame)
                except asyncio.TimeoutError as exc:
                    await self._drop_connection(connection_index)
                    raise ValidationSidecarTimeoutError(
                        f"Validation sidecar operation timed out after {self._timeout_seconds} seconds",
                    ) from exc
                except (BrokenPipeError, ConnectionResetError, asyncio.IncompleteReadError, OSError) as exc:
                    await self._drop_connection(connection_index)
                    last_error = exc
                    if attempt == 0:
                        continue
                    raise ValidationSidecarTransportError(f"Validation sidecar transport failed: {exc}") from exc
                except ValidationSidecarProtocolError:
                    await self._drop_connection(connection_index)
                    raise

            if response.ok:
                return

            raise ValidationSidecarValidationError(
                response.detail or "Validation sidecar rejected the request body",
                key=response.key,
                error_type=response.error_type,
                detail=response.detail,
            )

        if last_error is not None:
            raise ValidationSidecarTransportError(f"Validation sidecar transport failed after retry: {last_error}") from last_error
        raise ValidationSidecarTransportError("Validation sidecar transport failed")

    def _build_request_payload_bytes(
        self,
        body: bytes,
        *,
        max_param_length: int,
        dangerous_patterns: Sequence[str],
        request_id: str | None,
    ) -> bytes:
        """Serialize a validation request while caching static metadata for the hot path.

        Args:
            body: Raw JSON request body bytes.
            max_param_length: Maximum allowed string length.
            dangerous_patterns: Regex patterns to enforce.
            request_id: Optional request correlation id.

        Returns:
            Request payload bytes with metadata length, metadata JSON, and raw body bytes.

        Raises:
            ValueError: If the request body is too large.
        """
        if len(body) > MAX_REQUEST_BODY_SIZE:
            raise ValueError(f"request body exceeds maximum size of {MAX_REQUEST_BODY_SIZE} bytes")

        patterns_key = tuple(dangerous_patterns)
        if request_id is not None:
            metadata = ValidationSidecarRequest.from_body(
                body,
                max_param_length=max_param_length,
                dangerous_patterns=patterns_key,
                request_id=request_id,
            ).to_json_bytes()
            return METADATA_PREFIX.pack(len(metadata)) + metadata + body

        metadata = self._request_metadata_cache.get((max_param_length, patterns_key))
        if metadata is None:
            metadata = json.dumps(
                {
                    "raw_body_len": 0,
                    "max_param_length": max_param_length,
                    "dangerous_patterns": patterns_key,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            self._request_metadata_cache[(max_param_length, patterns_key)] = metadata

        metadata = metadata.replace(b'"raw_body_len":0', f'"raw_body_len":{len(body)}'.encode("ascii"), 1)
        return METADATA_PREFIX.pack(len(metadata)) + metadata + body

    async def _reserve_connection_index(self) -> int:
        """Return the next pool slot index using round-robin selection.

        Returns:
            The selected pooled connection slot index.
        """
        async with self._pool_lock:
            index = self._next_index
            self._next_index = (self._next_index + 1) % self._pool_size
            return index

    async def _ensure_connection(self, index: int) -> _ConnectionState:
        """Return a live connection for the requested pool slot.

        Args:
            index: Pooled connection slot index.

        Returns:
            A live pooled connection state object.

        Raises:
            ValidationSidecarTimeoutError: If connecting to the sidecar times out.
            ValidationSidecarTransportError: If opening the socket connection fails.
        """
        async with self._slot_locks[index]:
            connection = self._connections[index]
            if connection is not None and not connection.writer.is_closing():
                return connection

            try:
                reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(self._uds_path), timeout=self._timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise ValidationSidecarTimeoutError(
                    f"Timed out connecting to validation sidecar after {self._timeout_seconds} seconds",
                ) from exc
            except OSError as exc:
                raise ValidationSidecarTransportError(f"Failed to connect to validation sidecar at {self._uds_path}: {exc}") from exc

            connection = _ConnectionState(reader=reader, writer=writer, lock=asyncio.Lock())
            self._connections[index] = connection
            return connection

    async def _drop_connection(self, index: int) -> None:
        """Close and clear a pooled connection slot after transport failure.

        Args:
            index: Pooled connection slot index to clear.
        """
        async with self._slot_locks[index]:
            connection = self._connections[index]
            if connection is None:
                return

            await self._close_writer(connection.writer)
            self._connections[index] = None

    async def _close_writer(self, writer: asyncio.StreamWriter) -> None:
        """Close a writer and suppress cleanup-only shutdown errors.

        Args:
            writer: Stream writer to close.
        """
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=min(self._timeout_seconds, 1.0))
        except Exception:  # nosec B110 - cleanup only
            pass

    async def _write_frame(self, writer: asyncio.StreamWriter, frame: bytes) -> None:
        """Write a framed request to the sidecar within the configured timeout.

        Args:
            writer: Sidecar socket writer.
            frame: Length-prefixed request frame bytes.
        """
        writer.write(frame)
        await asyncio.wait_for(writer.drain(), timeout=self._timeout_seconds)

    async def _read_frame(self, reader: asyncio.StreamReader) -> bytes:
        """Read and decode a single framed response from the sidecar.

        Args:
            reader: Sidecar socket reader.

        Returns:
            The decoded response payload bytes.

        Raises:
            ValidationSidecarProtocolError: If the incoming frame exceeds the maximum size.
        """
        prefix = await asyncio.wait_for(reader.readexactly(FRAME_PREFIX.size), timeout=self._timeout_seconds)
        length = FRAME_PREFIX.unpack(prefix)[0]
        if length > MAX_FRAME_SIZE:
            raise ValidationSidecarProtocolError(f"Frame payload exceeds maximum size of {MAX_FRAME_SIZE} bytes")
        payload = await asyncio.wait_for(reader.readexactly(length), timeout=self._timeout_seconds)
        return decode_frame(prefix + payload)
