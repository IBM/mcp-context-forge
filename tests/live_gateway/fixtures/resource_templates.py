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
import warnings

# Third-Party
from mcp.server.mcpserver import MCPServer
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


def _application(peer: TemplatePeer, variant: str) -> MCPServer:
    """Build a real upstream with optional nonstandard discovery metadata.

    Args:
        peer: Upstream identity and request recorder.
        variant: Standard, resources/list advertisement, or MIME probe.
    """
    class TemplateMCPServer(MCPServer):
        """Expose controlled discovery metadata for diagnostic variants."""

        async def list_resources(self) -> list[Resource]:
            """Add a nonstandard template entry to ``resources/list``."""
            resources = await super().list_resources()
            if not variant.startswith("list-"):
                return resources
            extra: dict[str, object] = {}
            if variant == "list-extension":
                extra["uriTemplate"] = peer.template
            elif variant == "list-invalid-template":
                extra["uriTemplate"] = {"invalid": "template"}
            resources.append(Resource.model_validate({"uri": peer.template, "name": "Shared Template", "mimeType": "text/plain", **extra}))
            return resources

        async def list_resource_templates(self) -> list[ResourceTemplate]:
            """Expose the selected template metadata on the MCP wire."""
            if variant.startswith("list-"):
                return []
            if variant == "standard":
                return await super().list_resource_templates()
            return [ResourceTemplate(uri_template=peer.template, name="Shared Template", mime_type=None if variant == "no-mime" else "application/octet-stream")]

    app = TemplateMCPServer(peer.label)

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

    return app


@contextmanager
def template_upstreams(variant: str = "standard") -> Iterator[list[TemplatePeer]]:
    """Start two HTTP peers and stop only the listeners owned by this fixture.

    Args:
        variant: Metadata variant advertised by both peers.

    Yields:
        Two peers with distinct URI patterns and the same original template name.
    """
    host = os.getenv("MCP_TEMPLATE_UPSTREAM_HOST", "127.0.0.1")
    bind_host = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "0.0.0.0"
    if bind_host == "0.0.0.0":
        warnings.warn(
            f"The unauthenticated resource-template fixture is binding all interfaces for gateway host {host!r}. Run it only in an isolated test environment.",
            RuntimeWarning,
            stacklevel=2,
        )
    run_id = uuid.uuid4().hex[:12]
    peers = []
    running = []
    try:
        for index in range(2):
            peer = TemplatePeer(label=f"templates{run_id}{index}", root=f"test://templates/{run_id}/{index}")
            app = _application(peer, variant)
            listener = socket.socket()
            listener.bind((bind_host, 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app.streamable_http_app(host=bind_host, stateless_http=True, json_response=True), log_level="error"))
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
