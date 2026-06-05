# -*- coding: utf-8 -*-
"""Approach 2 prototype - standalone coordinator process.

Milestone A scope: the IPC skeleton.

Listens on a Unix domain socket, parses the length-prefixed JSON framing
described in
`docs/docs/architecture/experiments/coordinator-worker-design.md`,
and handles two message types:

* ``ping`` -> ``pong`` (used to verify the socket is alive).
* ``dispatch`` -> stub error (real implementation lands in Milestone B,
  when the registry actually owns and dispatches sessions).

Workers connect with one persistent UDS connection each. Per-request
correlation is by ``req_id``. The server can interleave responses out of
order; Milestone A doesn't exercise that property yet.

Run with::

    python -m mcpgateway.coordinator

Environment:
    COORDINATOR_UDS_PATH   Path to bind. Defaults to /tmp/mcp-coordinator.sock
                           for local development.
    COORDINATOR_LOG_LEVEL  Python log level (default INFO).
"""

# Standard
import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import struct
from typing import Any, Optional

LOG_LEVEL = os.environ.get("COORDINATOR_LOG_LEVEL", "INFO").upper()
SOCKET_PATH = os.environ.get("COORDINATOR_UDS_PATH", "/tmp/mcp-coordinator.sock")
MAX_FRAME_BYTES = 10 * 1024 * 1024  # 10 MiB hard ceiling on a single frame.

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [coordinator] %(levelname)s %(message)s",
)
logger = logging.getLogger("mcpgateway.coordinator")

# u32 big-endian length prefix. Same on both sides of the wire.
_LENGTH_PREFIX = struct.Struct(">I")


async def _read_frame(reader: asyncio.StreamReader) -> Optional[dict[str, Any]]:
    """Read one length-prefixed JSON frame, or ``None`` on clean EOF."""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as exc:
        if exc.partial:
            logger.warning("partial header before EOF: %d bytes", len(exc.partial))
        return None
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length == 0:
        return {}
    if length > MAX_FRAME_BYTES:
        raise ValueError(f"frame length {length} exceeds {MAX_FRAME_BYTES}")
    payload = await reader.readexactly(length)
    return json.loads(payload.decode("utf-8"))


async def _write_frame(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    """Encode and send a single length-prefixed JSON frame."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"outbound frame {len(payload)} exceeds {MAX_FRAME_BYTES}")
    writer.write(_LENGTH_PREFIX.pack(len(payload)))
    writer.write(payload)
    await writer.drain()


def _handle_message(message: dict[str, Any]) -> dict[str, Any]:
    """Translate one inbound frame into a response frame.

    Milestone A only handles ``ping``; ``dispatch`` returns a structured
    "not implemented" error so the framing path can still be exercised
    end-to-end with the eventual worker client.
    """
    msg_type = message.get("type")
    req_id = message.get("req_id")

    if msg_type == "ping":
        return {"type": "pong", "req_id": req_id}

    if msg_type == "dispatch":
        return {
            "type": "response",
            "req_id": req_id,
            "error": {
                "code": -32601,
                "message": "dispatch not implemented (Milestone A: framing only)",
            },
        }

    return {
        "type": "error",
        "req_id": req_id,
        "error": {
            "code": -32600,
            "message": f"unknown message type: {msg_type!r}",
        },
    }


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Read frames from one worker connection until it closes."""
    logger.info("connection opened")
    try:
        while True:
            message = await _read_frame(reader)
            if message is None:
                break
            try:
                response = _handle_message(message)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("handler crashed on message: %s", exc)
                response = {
                    "type": "error",
                    "req_id": message.get("req_id"),
                    "error": {"code": -32603, "message": f"internal coordinator error: {exc}"},
                }
            await _write_frame(writer, response)
    except (ConnectionResetError, BrokenPipeError) as exc:
        logger.info("connection reset: %s", exc)
    except Exception:
        logger.exception("unexpected error on connection")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("connection closed")


async def main() -> None:
    """Bind the UDS socket, serve until SIGTERM/SIGINT."""
    sock_path = Path(SOCKET_PATH)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        logger.warning("removing stale socket at %s", sock_path)
        sock_path.unlink()

    server = await asyncio.start_unix_server(_handle_client, path=str(sock_path))
    # rw for the owner and the gateway group. The shared volume in K8s /
    # Docker is expected to be group-readable.
    os.chmod(sock_path, 0o660)
    logger.info("listening on %s", sock_path)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        async with server:
            await stop.wait()
            logger.info("shutdown signal received")
    finally:
        # Clean up the socket file so a restart can re-bind.
        try:
            sock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not remove socket file: %s", exc)
        logger.info("shutdown complete")


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    asyncio.run(main())
