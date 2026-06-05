# -*- coding: utf-8 -*-
"""Worker-side IPC client for the Approach 2 coordinator-worker prototype.

Persistent Unix-socket connection to ``mcpgateway.coordinator``. One
background task reads inbound frames and resolves the matching ``req_id``
future, so multiple concurrent dispatches share a single connection. See
`docs/docs/architecture/experiments/coordinator-worker-design.md` for the
wire format and the rationale.

Milestone B scope: ``call_tool`` only. Other operations (``tools/list``,
``resources/read``, ``prompts/get``) follow the same pattern when wired
in later milestones.
"""

# Standard
import asyncio
import json
import logging
import struct
import uuid
from typing import Any, Optional

logger = logging.getLogger("mcpgateway.coordinator_client")

_LENGTH_PREFIX = struct.Struct(">I")
DEFAULT_TIMEOUT_S = 30.0


class CoordinatorUnavailableError(RuntimeError):
    """Raised when the IPC connection to the coordinator is gone."""


class CoordinatorClient:
    """One-instance-per-worker UDS client to the coordinator."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the UDS connection and spawn the reader task. Idempotent."""
        async with self._connect_lock:
            if self._connected:
                return
            self._reader, self._writer = await asyncio.open_unix_connection(self.socket_path)
            self._reader_task = asyncio.create_task(self._reader_loop(), name="coordinator-reader")
            self._connected = True
            logger.info("connected to coordinator at %s", self.socket_path)

    async def close(self) -> None:
        """Tear down the connection. Pending futures resolve with an error."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # pragma: no cover - shutdown best-effort
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._connected = False
        # Resolve any pending futures so callers don't hang.
        for fut in list(self._futures.values()):
            if not fut.done():
                fut.set_exception(CoordinatorUnavailableError("client closed"))
        self._futures.clear()

    # ------------------------------------------------------------------
    # Reader loop
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                try:
                    header = await self._reader.readexactly(4)
                except asyncio.IncompleteReadError:
                    break
                (length,) = _LENGTH_PREFIX.unpack(header)
                payload = await self._reader.readexactly(length)
                try:
                    message = json.loads(payload.decode("utf-8"))
                except Exception:
                    logger.exception("malformed frame from coordinator")
                    continue
                req_id = message.get("req_id")
                future = self._futures.pop(req_id, None)
                if future is None:
                    logger.warning("response for unknown req_id %r dropped", req_id)
                    continue
                if not future.done():
                    future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reader loop crashed")
        finally:
            self._connected = False
            for fut in list(self._futures.values()):
                if not fut.done():
                    fut.set_exception(CoordinatorUnavailableError("coordinator connection lost"))
            self._futures.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _send_and_await(self, message: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if not self._connected:
            await self.connect()
        assert self._writer is not None
        req_id = uuid.uuid4().hex
        message["req_id"] = req_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._futures[req_id] = future
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        async with self._write_lock:
            self._writer.write(_LENGTH_PREFIX.pack(len(payload)))
            self._writer.write(payload)
            await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=timeout_s + 5.0)
        except asyncio.TimeoutError:
            self._futures.pop(req_id, None)
            raise

    async def ping(self, timeout_s: float = 5.0) -> dict[str, Any]:
        """Round-trip a ping/pong to confirm the coordinator is alive."""
        return await self._send_and_await({"type": "ping"}, timeout_s=timeout_s)

    async def call_tool(
        self,
        *,
        downstream_session_id: str,
        gateway_id: str,
        url: str,
        headers: Optional[dict[str, str]],
        transport_type: Any,  # TransportType enum or its .value string
        tool_name: str,
        arguments: dict[str, Any],
        meta: Optional[dict[str, Any]] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Dispatch ``tools/call`` to the coordinator and return the JSON result.

        Returns the raw response frame -- callers reconstruct a
        ``CallToolResult`` from ``response["result"]`` when needed.
        """
        message = {
            "type": "call_tool",
            "downstream_session_id": downstream_session_id,
            "gateway_id": gateway_id,
            "url": url,
            "headers": headers,
            "transport_type": (
                transport_type.value if hasattr(transport_type, "value") else transport_type
            ),
            "tool_name": tool_name,
            "arguments": arguments,
            "meta": meta,
            "timeout_s": timeout_s,
        }
        return await self._send_and_await(message, timeout_s=timeout_s)


# Module-level singleton, instantiated from main.py on startup if
# COORDINATOR_UDS_PATH is set. Workers reuse this for the lifetime of the
# process; the registry path in tool_service.py branches on whether it's
# bound.
_client: Optional[CoordinatorClient] = None


def get_coordinator_client() -> Optional[CoordinatorClient]:
    """Return the process-wide client, or ``None`` if not configured."""
    return _client


def set_coordinator_client(client: Optional[CoordinatorClient]) -> None:
    """Install the singleton. Called once at startup."""
    global _client  # pylint: disable=global-statement
    _client = client
