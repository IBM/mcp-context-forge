# SPDX-License-Identifier: Apache-2.0
"""Start an echo server and make manual gateway calls with the output guard."""

# Repeat the manual test from the project root. Use three terminals.
#
# Terminal 1: prepare the plugin configuration and keep the echo server running.
#   .venv/bin/python cpex03_manual.py serve
#
# Terminal 2: start the gateway with the plugin enabled and your normal .env settings.
#   PLUGINS_ENABLED=true \
#   PLUGINS_NATIVE_CONFIG_FILE="$PWD/.cache/cpex03-local/manual/config.yaml" \
#   make dev
# Wait for "Application startup complete" before making calls.
#
# Terminal 3: register a temporary tool, call it, and delete it automatically.
#   .venv/bin/python cpex03_manual.py call short
# Expected result text: short
#   .venv/bin/python cpex03_manual.py call abcdefghijklmnopqrstuvwxyz
# Expected result text: abcdefghi... (12 characters, including the three dots).
#
# The call path is: helper -> gateway -> echo server -> CPEX -> output guard -> helper.
# Prerequisites:
# Install this branch's dependencies, including CPEX from the configured Git branch.
# Configure .env and set SSRF_ALLOW_LOCALHOST=true for the local echo server.
# The configured admin must exist, or MCPGATEWAY_BEARER_TOKEN must contain a valid admin token.
# Keep ports 8000 and 9001 available.
# The worker installs CPEX 0.1.4 and output guard 0.1.3 in its separate environment.
# Stop the gateway and echo server with Ctrl+C when finished.

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

REPO = Path(__file__).resolve().parent
MANUAL = REPO / ".cache/cpex03-local/manual"
GATEWAY = "http://127.0.0.1:8000"
ECHO_PORT = 9001


def prepare(strategy: str) -> None:
    """Write the plugin configuration and worker requirements for make dev."""
    MANUAL.mkdir(parents=True, exist_ok=True)
    requirements = MANUAL / "requirements.txt"
    requirements.write_text("cpex==0.1.4\ncpex-output-length-guard==0.1.3\n")
    config = {
        "engine_settings": {"dispatch": "hooks"},
        "plugins": [
            {
                "name": "output-length-guard",
                "kind": "isolated_venv",
                "hooks": ["cmf.tool_post_invoke"],
                "config": {
                    "class_name": "cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
                    "requirements_file": str(requirements),
                    "max_chars": 12,
                    "strategy": strategy,
                    "ellipsis": "...",
                },
            }
        ],
    }
    (MANUAL / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))


class EchoServer(BaseHTTPRequestHandler):
    """Return submitted text as an MCP tool result."""

    def do_POST(self) -> None:
        """Reply with the text supplied by the gateway."""
        arguments = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or "{}")
        text = arguments.get("text", "")
        body = json.dumps({"content": [{"type": "text", "text": text}], "isError": False}).encode()
        print(f"Echo tool received: {text!r}", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def authorization() -> dict[str, str]:
    """Use an explicit token or sign one with the normal development settings."""
    token = os.environ.get("MCPGATEWAY_BEARER_TOKEN")
    if not token:
        from mcpgateway.config import settings
        from mcpgateway.utils.create_jwt_token import _create_jwt_token

        email = settings.platform_admin_email
        token = _create_jwt_token(
            {"sub": email, "email": email, "is_admin": True},
            expires_in_minutes=15,
            user_data={"email": email, "is_admin": True, "auth_provider": "local"},
            teams=None,
        )
    return {"Authorization": "Bearer " + token}


def call(text: str) -> None:
    """Register a temporary tool, call it through the gateway, and delete it."""
    with httpx.Client(base_url=GATEWAY, headers=authorization(), timeout=30) as client:
        # The upstream returns raw text; the gateway's plugin checks the result.
        response = client.post(
            "/tools",
            json={
                "tool": {
                    "name": "cpex-manual-" + uuid4().hex[:8],
                    "url": f"http://127.0.0.1:{ECHO_PORT}/echo",
                    "integration_type": "REST",
                    "request_type": "POST",
                    "visibility": "public",
                    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                }
            },
        )
        response.raise_for_status()
        tool = response.json()
        try:
            response = client.post(
                "/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool["name"], "arguments": {"text": text}},
                },
            )
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
        finally:
            # Delete only the tool created by this call.
            deletion = client.delete("/tools/" + tool["id"])
            if not deletion.is_success:
                raise RuntimeError(f"Delete temporary tool {tool['id']} manually: HTTP {deletion.status_code}")


def main() -> None:
    """Run the echo server or send a manual tool call."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("prepare", help="Write the plugin configuration without starting a server")
    setup.add_argument("--strategy", choices=["truncate", "block"], default="truncate")
    server = actions.add_parser("serve", help="Prepare settings and start the echo server")
    server.add_argument("--strategy", choices=["truncate", "block"], default="truncate")
    caller = actions.add_parser("call", help="Register, call, and delete a temporary tool")
    caller.add_argument("text")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.strategy)
            print(f"Plugin configuration ready: {MANUAL / 'config.yaml'}")
        elif args.action == "serve":
            with ThreadingHTTPServer(("127.0.0.1", ECHO_PORT), EchoServer) as server:
                prepare(args.strategy)
                print(f"Echo tool: http://127.0.0.1:{ECHO_PORT}/echo", flush=True)
                print(f"Guard: {args.strategy}, maximum 12 characters", flush=True)
                print('Gateway terminal: PLUGINS_ENABLED=true PLUGINS_NATIVE_CONFIG_FILE="$PWD/.cache/cpex03-local/manual/config.yaml" make dev', flush=True)
                server.serve_forever()
        else:
            call(args.text)
    except KeyboardInterrupt:
        pass
    except httpx.ConnectError:
        parser.exit(1, "Cannot connect to the gateway on port 8000. Start make dev and wait for startup.\n")


if __name__ == "__main__":
    main()
