# -*- coding: utf-8 -*-
""" mcpgateway.translate - bridges local JSON-RPC/stdio servers to HTTP/SSE

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Only the stdio→SSE direction is implemented for now.

Usage
-----
# 1. expose an MCP server that talks JSON-RPC on stdio at :9000/sse
python -m mcpgateway.translate --stdio "uvenv run mcp-server-git" --port 9000

# 2. from another shell / browser subscribe to the SSE stream
curl -N http://localhost:9000/sse          # receive the stream

# 3. send a test echo request
curl -X POST http://localhost:9000/message \
     -H 'Content-Type: application/json'   \
     -d '{"jsonrpc":"2.0","id":1,"method":"echo","params":{"value":"hi"}}'

# 4. proper MCP handshake and tool listing
curl -X POST http://localhost:9000/message \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"0.0.1"}}}'

curl -X POST http://localhost:9000/message \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

The SSE stream now emits JSON-RPC responses as `event: message` frames and sends
regular `event: keepalive` frames (default every 30s) so that proxies and
clients never time out.  Each client receives a unique *session-id* that is
appended as a query parameter to the back-channel `/message` URL.
"""

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
from contextlib import suppress
import json
import logging
import shlex
import signal
import sys
from typing import AsyncIterator, List, Optional, Sequence
import uuid

# Third-Party
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse
import uvicorn

LOGGER = logging.getLogger("mcpgateway.translate")
KEEP_ALIVE_INTERVAL = 30  # seconds ── matches the reference implementation
__all__ = ["main"]  # for console-script entry-point


# ---------------------------------------------------------------------------#
# Helpers - trivial in-process Pub/Sub                                       #
# ---------------------------------------------------------------------------#
class _PubSub:
    """Very small fan-out helper - one async Queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue[str]] = []

    async def publish(self, data: str) -> None:
        dead: List[asyncio.Queue[str]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            with suppress(ValueError):
                self._subscribers.remove(q)

    def subscribe(self) -> "asyncio.Queue[str]":
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[str]") -> None:
        with suppress(ValueError):
            self._subscribers.remove(q)


# ---------------------------------------------------------------------------#
# StdIO endpoint (child process ↔ async queues)                              #
# ---------------------------------------------------------------------------#
class StdIOEndpoint:
    """Wrap a child process whose stdin/stdout speak line-delimited JSON-RPC."""

    def __init__(self, cmd: str, pubsub: _PubSub) -> None:
        self._cmd = cmd
        self._pubsub = pubsub
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stdin: Optional[asyncio.StreamWriter] = None
        self._pump_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        LOGGER.info("Starting stdio subprocess: %s", self._cmd)
        self._proc = await asyncio.create_subprocess_exec(
            *shlex.split(self._cmd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,  # passthrough for visibility
        )
        assert self._proc.stdin and self._proc.stdout
        self._stdin = self._proc.stdin
        self._pump_task = asyncio.create_task(self._pump_stdout())

    async def stop(self) -> None:
        if self._proc is None:
            return
        LOGGER.info("Stopping subprocess (pid=%s)", self._proc.pid)
        self._proc.terminate()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._proc.wait(), timeout=5)
        if self._pump_task:
            self._pump_task.cancel()

    async def send(self, raw: str) -> None:
        if not self._stdin:
            raise RuntimeError("stdio endpoint not started")
        LOGGER.debug("→ stdio: %s", raw.strip())
        self._stdin.write(raw.encode())
        await self._stdin.drain()

    async def _pump_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        reader = self._proc.stdout
        try:
            while True:
                line = await reader.readline()
                if not line:  # EOF
                    break
                text = line.decode(errors="replace")
                LOGGER.debug("← stdio: %s", text.strip())
                await self._pubsub.publish(text)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover --best-effort logging
            LOGGER.exception("stdout pump crashed - terminating bridge")
            raise


# ---------------------------------------------------------------------------#
# FastAPI app exposing /sse  &  /message                                     #
# ---------------------------------------------------------------------------#


def _build_fastapi(
    pubsub: _PubSub,
    stdio: StdIOEndpoint,
    keep_alive: int = KEEP_ALIVE_INTERVAL,
    sse_path: str = "/sse",
    message_path: str = "/message",
) -> FastAPI:
    app = FastAPI()

    # ----- GET /sse ---------------------------------------------------------#
    @app.get(sse_path)
    async def get_sse(request: Request) -> EventSourceResponse:  # noqa: D401
        """Stream subprocess stdout to any number of SSE clients.

        Args:
            request (Request): The incoming ``GET`` request that will be
                upgraded to a Server-Sent Events (SSE) stream.

        Returns:
            EventSourceResponse: A streaming response that forwards JSON-RPC
            messages from the child process and emits periodic ``keepalive``
            frames so that clients and proxies do not time out.
        """
        queue = pubsub.subscribe()
        session_id = uuid.uuid4().hex

        async def event_gen() -> AsyncIterator[dict]:
            # 1️⃣ Mandatory "endpoint" bootstrap required by the MCP spec
            endpoint_url = f"{str(request.base_url).rstrip('/')}{message_path}?session_id={session_id}"
            yield {
                "event": "endpoint",
                "data": endpoint_url,
                "retry": int(keep_alive * 1000),
            }

            # 2️⃣ Immediate keepalive so clients know the stream is alive
            yield {"event": "keepalive", "data": "{}", "retry": keep_alive * 1000}

            try:
                while True:
                    if await request.is_disconnected():
                        break

                    try:
                        msg = await asyncio.wait_for(queue.get(), keep_alive)
                        yield {"event": "message", "data": msg.rstrip()}
                    except asyncio.TimeoutError:
                        yield {
                            "event": "keepalive",
                            "data": "{}",
                            "retry": keep_alive * 1000,
                        }
            finally:
                pubsub.unsubscribe(queue)

        return EventSourceResponse(
            event_gen(),
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    # ----- POST /message ----------------------------------------------------#
    @app.post(message_path, status_code=status.HTTP_202_ACCEPTED)
    async def post_message(raw: Request, session_id: str | None = None) -> Response:  # noqa: D401
        """Forward a raw JSON-RPC request to the stdio subprocess.

        Args:
            raw (Request): The incoming ``POST`` request whose body contains
                a single JSON-RPC message.
            session_id (str | None): The SSE session identifier that originated
                this back-channel call (present when the client obtained the
                endpoint URL from an ``endpoint`` bootstrap frame).

        Returns:
            Response: ``202 Accepted`` if the payload is forwarded successfully,
            or ``400 Bad Request`` when the body is not valid JSON.
        """
        payload = await raw.body()
        try:
            json.loads(payload)  # validate
        except Exception as exc:  # noqa: BLE001
            return PlainTextResponse(
                f"Invalid JSON payload: {exc}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        await stdio.send(payload.decode().rstrip() + "\n")
        return PlainTextResponse("forwarded", status_code=status.HTTP_202_ACCEPTED)

    # ----- Liveness ---------------------------------------------------------#
    @app.get("/healthz")
    async def health() -> Response:  # noqa: D401
        return PlainTextResponse("ok")

    return app


# ---------------------------------------------------------------------------#
# CLI & orchestration                                                        #
# ---------------------------------------------------------------------------#


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mcpgateway.translate",
        description="Bridges stdio JSON-RPC to SSE.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--stdio", help='Command to run, e.g. "uv run mcp-server-git"')
    src.add_argument("--sse", help="[NOT IMPLEMENTED]")
    src.add_argument("--streamableHttp", help="[NOT IMPLEMENTED]")

    p.add_argument("--port", type=int, default=8000, help="HTTP port to bind")
    p.add_argument(
        "--logLevel",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level",
    )

    args = p.parse_args(argv)
    if args.sse or args.streamableHttp:
        raise NotImplementedError("Only --stdio → SSE is available in this build.")
    return args


async def _run_stdio_to_sse(cmd: str, port: int, log_level: str = "info") -> None:
    pubsub = _PubSub()
    stdio = StdIOEndpoint(cmd, pubsub)
    await stdio.start()

    app = _build_fastapi(pubsub, stdio)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level=log_level,
        lifespan="off",
    )
    server = uvicorn.Server(config)

    shutting_down = asyncio.Event()  # 🔄 make shutdown idempotent

    async def _shutdown() -> None:
        if shutting_down.is_set():
            return
        shutting_down.set()
        LOGGER.info("Shutting down …")
        await stdio.stop()
        await server.shutdown()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # Windows lacks add_signal_handler
            loop.add_signal_handler(sig, lambda _s=sig: asyncio.create_task(_shutdown()))

    LOGGER.info("Bridge ready → http://127.0.0.1:%s/sse", port)
    await server.serve()
    await _shutdown()  # final cleanup


def main(argv: Optional[Sequence[str]] | None = None) -> None:  # entry-point
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=getattr(logging, args.logLevel.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run_stdio_to_sse(args.stdio, args.port, args.logLevel))
    except KeyboardInterrupt:
        print("")  # restore shell prompt
        sys.exit(0)
    except NotImplementedError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # python -m mcpgateway.translate …
    main()
