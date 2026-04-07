# -*- coding: utf-8 -*-
"""Tests for the validation sidecar client and its config-path support."""

# Standard
import asyncio
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import uuid

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.config import Settings
from mcpgateway.services.validation_sidecar_client import (
    METADATA_PREFIX,
    ValidationSidecarClient,
    ValidationSidecarProtocolError,
    ValidationSidecarRequest,
    ValidationSidecarTimeoutError,
    ValidationSidecarTransportError,
    ValidationSidecarValidationError,
    decode_frame,
    encode_frame,
)


async def _read_framed_payload(reader: asyncio.StreamReader) -> bytes:
    """Read one length-prefixed payload from a test sidecar connection."""
    prefix = await reader.readexactly(4)
    length = struct.unpack(">I", prefix)[0]
    return await reader.readexactly(length)


class _FakeWriter:
    """Minimal async writer stub for monkeypatched client tests."""

    def __init__(self) -> None:
        """Initialize the fake writer in an open state."""
        self._closing = False

    def is_closing(self) -> bool:
        """Return whether the fake writer has been closed."""
        return self._closing

    def close(self) -> None:
        """Mark the fake writer as closed."""
        self._closing = True

    async def wait_closed(self) -> None:
        """Provide an awaitable close hook matching StreamWriter."""
        return None

    def write(self, data: bytes) -> None:
        """Accept bytes without performing any I/O."""
        return None

    async def drain(self) -> None:
        """Provide an awaitable flush hook matching StreamWriter."""
        return None


def test_frame_round_trip_uses_big_endian_length_prefix() -> None:
    """Frames should preserve payload bytes and use a big-endian length header."""
    payload = b"\x00\x01hello"

    frame = encode_frame(payload)

    assert frame[:4] == struct.pack(">I", len(payload))
    assert decode_frame(frame) == payload


def test_request_envelope_preserves_raw_body_outside_metadata() -> None:
    """Request payloads should carry raw body bytes outside the metadata JSON."""
    body = b'{"hello":"world"}'

    request = ValidationSidecarRequest.from_body(
        body,
        max_param_length=42,
        dangerous_patterns=[r"<script", r"javascript:"],
        request_id="req-1",
    )

    metadata = json.loads(request.to_json_bytes())
    assert metadata["raw_body_len"] == len(body)
    assert metadata["max_param_length"] == 42
    assert metadata["dangerous_patterns"] == [r"<script", r"javascript:"]
    assert metadata["request_id"] == "req-1"
    assert "request_body_b64" not in metadata


def test_client_builds_binary_request_payload_without_base64(tmp_path: Path) -> None:
    """Client request payloads should encode metadata length plus raw body bytes."""
    client = ValidationSidecarClient(uds_path=str(tmp_path / "sidecar.sock"), timeout_seconds=0.1)
    body = b'{"hello":"world"}'

    payload = client._build_request_payload_bytes(
        body,
        max_param_length=42,
        dangerous_patterns=[r"<script", r"javascript:"],
        request_id="req-1",
    )

    metadata_len = METADATA_PREFIX.unpack(payload[: METADATA_PREFIX.size])[0]
    metadata = json.loads(payload[METADATA_PREFIX.size : METADATA_PREFIX.size + metadata_len])
    raw_body = payload[METADATA_PREFIX.size + metadata_len :]

    assert metadata["raw_body_len"] == len(body)
    assert metadata["max_param_length"] == 42
    assert metadata["dangerous_patterns"] == [r"<script", r"javascript:"]
    assert metadata["request_id"] == "req-1"
    assert raw_body == body


def test_sidecar_settings_defaults_and_path_validation(tmp_path: Path) -> None:
    """Settings should expose defaults and validate sidecar socket paths."""
    settings = Settings(_env_file=None)
    assert settings.experimental_rust_validation_sidecar_enabled is False
    assert settings.experimental_rust_validation_sidecar_uds is None
    assert settings.experimental_rust_validation_sidecar_timeout_seconds == 30
    assert settings.experimental_rust_validation_sidecar_pool_size == 8

    uds_path = tmp_path / "validation.sock"
    settings = Settings(experimental_rust_validation_sidecar_uds=str(uds_path), _env_file=None)
    assert settings.experimental_rust_validation_sidecar_uds == str(uds_path)

    with pytest.raises(ValidationError, match="absolute path"):
        Settings(experimental_rust_validation_sidecar_uds="relative.sock", _env_file=None)

    missing_parent = tmp_path / "missing" / "validation.sock"
    with pytest.raises(ValidationError, match="parent directory does not exist"):
        Settings(experimental_rust_validation_sidecar_uds=str(missing_parent), _env_file=None)


def test_sidecar_enabled_requires_uds_path() -> None:
    """Enabling the sidecar should require an explicit socket path."""
    with pytest.raises(ValidationError, match="must be set when experimental_rust_validation_sidecar_enabled is true"):
        Settings(experimental_rust_validation_sidecar_enabled=True, _env_file=None)


def test_sidecar_timeout_must_be_positive() -> None:
    """The sidecar timeout must reject zero or negative values."""
    with pytest.raises(ValidationError):
        Settings(experimental_rust_validation_sidecar_timeout_seconds=0, _env_file=None)


def test_sidecar_timeout_accepts_fractional_seconds() -> None:
    """The sidecar timeout should allow positive fractional seconds."""
    settings = Settings(experimental_rust_validation_sidecar_timeout_seconds=0.5, _env_file=None)
    assert settings.experimental_rust_validation_sidecar_timeout_seconds == 0.5


def test_sidecar_pool_size_must_be_positive() -> None:
    """The sidecar pool size must reject zero or negative values."""
    with pytest.raises(ValidationError):
        Settings(experimental_rust_validation_sidecar_pool_size=0, _env_file=None)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_client_raises_transport_error_when_socket_unavailable(tmp_path: Path) -> None:
    """Missing sockets should surface a transport error with 503 semantics."""
    client = ValidationSidecarClient(uds_path=str(tmp_path / "missing.sock"), timeout_seconds=0.1)

    try:
        with pytest.raises(ValidationSidecarTransportError) as exc_info:
            await client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[])

        assert exc_info.value.status_code == 503
    finally:
        await client.aclose()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_client_raises_timeout_when_sidecar_never_replies(tmp_path: Path) -> None:
    """Hung sidecar reads should surface a timeout error."""
    socket_path = Path("/tmp") / f"validation-sidecar-{uuid.uuid4().hex[:8]}.sock"
    socket_path.unlink(missing_ok=True)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Consume one request and then intentionally never reply."""
        try:
            await _read_framed_payload(reader)
        except Exception:
            pass
        await asyncio.Event().wait()

    server = await asyncio.start_unix_server(handler, path=str(socket_path))
    client = ValidationSidecarClient(uds_path=str(socket_path), timeout_seconds=0.05)

    try:
        with pytest.raises(ValidationSidecarTimeoutError) as exc_info:
            await client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[])

        assert exc_info.value.status_code == 503
    finally:
        await client.aclose()
        server.close()
        socket_path.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_client_raises_protocol_error_for_malformed_response(tmp_path: Path) -> None:
    """Malformed sidecar JSON responses should raise protocol errors."""
    socket_path = Path("/tmp") / f"validation-sidecar-{uuid.uuid4().hex[:8]}.sock"
    socket_path.unlink(missing_ok=True)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Return invalid JSON after consuming the framed request."""
        try:
            await _read_framed_payload(reader)
            writer.write(encode_frame(b"{not-json"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handler, path=str(socket_path))
    client = ValidationSidecarClient(uds_path=str(socket_path), timeout_seconds=1.0)

    try:
        with pytest.raises(ValidationSidecarProtocolError) as exc_info:
            await client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[])

        assert exc_info.value.status_code == 503
    finally:
        await client.aclose()
        server.close()
        socket_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_client_maps_rejection_response_to_validation_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Rejected sidecar responses should map to validation errors."""
    client = ValidationSidecarClient(uds_path=str(tmp_path / "sidecar.sock"), timeout_seconds=0.1)

    async def fake_open_unix_connection(path: str):
        """Return a fake socket pair without real transport I/O."""
        return SimpleNamespace(), _FakeWriter()

    async def fake_write_frame(writer: _FakeWriter, frame: bytes) -> None:
        """Pretend the client successfully wrote the request frame."""
        return None

    async def fake_read_frame(reader: object) -> bytes:
        """Return a rejected sidecar response envelope."""
        return json.dumps(
            {
                "ok": False,
                "key": "payload.name",
                "error_type": "dangerous_pattern",
                "detail": "payload.name matched a blocked pattern",
            }
        ).encode("utf-8")

    monkeypatch.setattr("mcpgateway.services.validation_sidecar_client.asyncio.open_unix_connection", fake_open_unix_connection)
    monkeypatch.setattr(client, "_write_frame", fake_write_frame)
    monkeypatch.setattr(client, "_read_frame", fake_read_frame)

    with pytest.raises(ValidationSidecarValidationError) as exc_info:
        await client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[r"<script"])

    assert exc_info.value.status_code == 422
    assert exc_info.value.key == "payload.name"
    assert exc_info.value.error_type == "dangerous_pattern"
    assert exc_info.value.detail == "payload.name matched a blocked pattern"


@pytest.mark.asyncio
async def test_client_does_not_exceed_pool_size_under_contention(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Concurrent callers should not create more connections than the pool size."""
    client = ValidationSidecarClient(uds_path=str(tmp_path / "sidecar.sock"), timeout_seconds=0.2, pool_size=2)
    open_started = asyncio.Event()
    release_open = asyncio.Event()
    open_calls = 0

    async def fake_open_unix_connection(path: str):
        """Block connection establishment so contention is observable."""
        nonlocal open_calls
        open_calls += 1
        open_started.set()
        await release_open.wait()
        return SimpleNamespace(), _FakeWriter()

    async def fake_write_frame(writer: _FakeWriter, frame: bytes) -> None:
        """Pretend the pooled write succeeded."""
        return None

    async def fake_read_frame(reader: object) -> bytes:
        """Return a successful response once the fake connection exists."""
        return b'{"ok":true}'

    monkeypatch.setattr("mcpgateway.services.validation_sidecar_client.asyncio.open_unix_connection", fake_open_unix_connection)
    monkeypatch.setattr(client, "_write_frame", fake_write_frame)
    monkeypatch.setattr(client, "_read_frame", fake_read_frame)

    tasks = [asyncio.create_task(client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[])) for _ in range(6)]
    await open_started.wait()
    await asyncio.sleep(0)
    release_open.set()
    await asyncio.gather(*tasks)

    assert open_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("open_error", [OSError("connect failed"), asyncio.TimeoutError()])
async def test_client_retries_connect_time_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, open_error: Exception) -> None:
    """The client should retry once when the initial connect attempt fails."""
    client = ValidationSidecarClient(uds_path=str(tmp_path / "sidecar.sock"), timeout_seconds=0.1, pool_size=1)
    open_calls = 0

    async def fake_open_unix_connection(path: str):
        """Fail the first connect attempt, then succeed."""
        nonlocal open_calls
        open_calls += 1
        if open_calls == 1:
            raise open_error
        return SimpleNamespace(), _FakeWriter()

    async def fake_write_frame(writer: _FakeWriter, frame: bytes) -> None:
        """Pretend the retried write succeeded."""
        return None

    async def fake_read_frame(reader: object) -> bytes:
        """Return a successful response envelope after reconnect."""
        return b'{"ok":true}'

    monkeypatch.setattr("mcpgateway.services.validation_sidecar_client.asyncio.open_unix_connection", fake_open_unix_connection)
    monkeypatch.setattr(client, "_write_frame", fake_write_frame)
    monkeypatch.setattr(client, "_read_frame", fake_read_frame)

    await client.validate_json_body(b"{}", max_param_length=10, dangerous_patterns=[])
    assert open_calls == 2
