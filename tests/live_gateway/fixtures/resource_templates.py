# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/fixtures/resource_templates.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Serve controlled MCP peers for resource-template federation tests.
"""

# Future
from __future__ import annotations

# Standard
import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import socket
import threading
import time
import uuid

# Third-Party
from mcp.server.fastmcp import FastMCP
from mcp.types import Resource, ResourceTemplate
import uvicorn


@dataclass
class TemplatePeer:
    """Describe one upstream and retain the URIs it receives."""

    label: str
    root: str
    url: str = ""
    local_url: str = ""
    reads: list[str] = field(default_factory=list)

    @property
    def template(self) -> str:
        """Return the upstream's exact URI template."""
        return f"{self.root}/items/{{item_id}}"

    @property
    def concrete(self) -> str:
        """Return the upstream's concrete resource URI."""
        return f"{self.root}/index"

    def expanded(self, item_id: str) -> str:
        """Expand the fixture's single path parameter.

        Args:
            item_id: Item identifier without path separators.
        """
        return f"{self.root}/items/{item_id}"

    def content(self, item_id: str) -> str:
        """Return content that identifies the upstream and parameter.

        Args:
            item_id: Requested item identifier.
        """
        return f"{self.label}:item:{item_id}"


def _application(peer: TemplatePeer, variant: str) -> FastMCP:
    """Build a real upstream with optional nonstandard discovery metadata.

    Args:
        peer: Upstream identity and request recorder.
        variant: Standard, resources/list advertisement, or MIME probe.
    """
    app = FastMCP(peer.label, host="0.0.0.0", stateless_http=True, json_response=True)

    @app.resource(peer.concrete, name="Index", mime_type="text/plain")
    def index() -> str:
        """Return the concrete resource content."""
        peer.reads.append(peer.concrete)
        return f"{peer.label}:index"

    @app.resource(peer.template, name="Shared Template", mime_type="application/octet-stream" if variant == "binary" else "text/plain")
    def item(item_id: str) -> str | bytes:
        """Return content for an expanded template URI.

        Args:
            item_id: Expanded path parameter supplied by the MCP server.
        """
        peer.reads.append(peer.expanded(item_id))
        content = peer.content(item_id)
        return content.encode() if variant == "binary" else content

    if variant.startswith("list-"):

        @app._mcp_server.list_resources()  # type: ignore[no-untyped-call, untyped-decorator]  # pylint: disable=protected-access
        async def list_resources() -> list[Resource]:
            """Advertise a nonstandard template entry through resources/list."""
            extra: dict[str, object] = {}
            if variant == "list-extension":
                extra["uriTemplate"] = peer.template
            elif variant == "list-invalid-template":
                extra["uriTemplate"] = {"invalid": "template"}
            return [
                Resource(uri=peer.concrete, name="Index", mimeType="text/plain"),
                Resource.model_validate({"uri": peer.template, "name": "Shared Template", "mimeType": "text/plain", **extra}),
            ]

    if variant != "standard":

        @app._mcp_server.list_resource_templates()  # type: ignore[no-untyped-call, untyped-decorator]  # pylint: disable=protected-access
        async def list_templates() -> list[ResourceTemplate]:
            """Expose the selected metadata variant on the MCP wire."""
            if variant.startswith("list-"):
                return []
            return [ResourceTemplate(uriTemplate=peer.template, name="Shared Template", mimeType=None if variant == "no-mime" else "application/octet-stream")]

    return app


@contextmanager
def template_upstreams(variant: str = "standard") -> Iterator[list[TemplatePeer]]:
    """Start two HTTP peers and stop only the listeners owned by this fixture.

    Args:
        variant: Metadata variant advertised by both peers.

    Yields:
        Two peers with distinct URI patterns and the same original template name.
    """
    host = os.getenv("MCP_TEMPLATE_UPSTREAM_HOST", "host.docker.internal")
    run_id = uuid.uuid4().hex[:12]
    peers = []
    running = []
    try:
        for index in range(2):
            peer = TemplatePeer(label=f"templates{run_id}{index}", root=f"test://templates/{run_id}/{index}")
            app = _application(peer, variant)
            listener = socket.socket()
            listener.bind(("0.0.0.0", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app.streamable_http_app(), log_level="error"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            running.append((server, thread, listener))
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, f"Template upstream {peer.label} failed to start"
            peer.url = f"http://{host}:{port}/mcp/"
            peer.local_url = f"http://127.0.0.1:{port}/mcp/"
            peers.append(peer)
        yield peers
    finally:
        for server, thread, listener in running:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            assert not thread.is_alive(), "Template upstream failed to stop"


def main() -> None:
    """Serve fixtures for an independent MCP client until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("standard", "list-extension", "list-missing-template", "list-invalid-template", "no-mime", "binary"), default="standard")
    args = parser.parse_args()
    with template_upstreams(args.variant) as peers:
        for peer in peers:
            print(json.dumps({"name": peer.label, "gateway_url": peer.url, "local_url": peer.local_url, "uriTemplate": peer.template, "read_uri": peer.expanded("42"), "expected_text": peer.content("42")}), flush=True)
        positions = [0] * len(peers)
        try:
            while True:
                for index, peer in enumerate(peers):
                    for uri in peer.reads[positions[index] :]:
                        print(json.dumps({"upstream": peer.label, "received_uri": uri}), flush=True)
                    positions[index] = len(peer.reads)
                time.sleep(0.25)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
