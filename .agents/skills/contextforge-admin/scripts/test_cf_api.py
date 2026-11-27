#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exercise the command-line client against a loopback HTTP fixture.
Location: ./.agents/skills/contextforge-admin/scripts/test_cf_api.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any, cast
import unittest

import cf_api


CLI = Path(__file__).with_name("cf_api.py")


class FixtureServer(ThreadingHTTPServer):
    """Store fixture values and requests in memory."""

    received: list[tuple[str, str, str | None, Any]]
    login: dict[str, str]
    token: str
    location: str
    invitation: str
    private_link: str


class Handler(BaseHTTPRequestHandler):
    """Return fixture responses for the CLI tests."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP request logs in the fixture."""

    def handle_request(self) -> None:
        """Record the request and send its fixture response."""
        server = cast(FixtureServer, self.server)
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size)) if size else None
        token = self.headers.get("Authorization")
        server.received.append((self.command, self.path, token, body))
        path = self.path.removeprefix("/gateway")

        if path == "/v1/auth/email/login":
            if body == server.login:
                self.json_response(200, {"access_token": server.token})
            else:
                password = body.get("password", "") if isinstance(body, dict) else ""
                self.json_response(401, {"detail": "Rejected password: " + password})
            return
        if token != "Bearer " + server.token:
            self.json_response(401, {"detail": "Authorization required"})
            return
        if path == "/redirect":
            self.send_response(307)
            self.send_header("Location", server.location)
            self.end_headers()
        elif path == "/openapi.json":
            self.json_response(200, OPENAPI)
        elif path.startswith("/v1/teams/"):
            self.json_response(200, {"teams": [{"name": "Support", "authTokenUnmasked": server.token}]})
        elif path == "/v1/example/invitation":
            self.json_response(
                201,
                {
                    "token": server.invitation,
                    "repeated_link": "https://gateway.example.com/join/" + server.invitation,
                    "invitation_url": "https://gateway.example.com/join/" + server.private_link,
                },
            )
        elif path == "/v1/example":
            if body and "client_secret" in body:
                self.json_response(422, {"detail": [{"loc": ["body", "client_secret"], "input": body["client_secret"], "msg": "Rejected: " + body["client_secret"]}]})
            else:
                self.json_response(200, {"received": body})
        else:
            self.json_response(404, {})

    do_GET = do_POST = do_PUT = handle_request

    def json_response(self, status: int, value: Any) -> None:
        """Write a JSON response to the CLI."""
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


OPENAPI = {
    "paths": {
        "/v1/example/{id}": {
            "parameters": [{"$ref": "#/components/parameters/Id"}],
            "get": {"summary": "Read example"},
            "put": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}}},
        }
    },
    "components": {
        "parameters": {"Id": {"name": "id", "in": "path", "required": True}},
        "schemas": {
            "Node": {
                "properties": {
                    "password": {"type": "string", "default": "omit-this-example"},
                    "invite_url": {"type": "string"},
                    "description": {"type": "string"},
                    "child": {"$ref": "#/components/schemas/Node"},
                }
            }
        },
    },
}


class ClientTests(unittest.TestCase):
    """Test the CLI against loopback HTTP endpoints."""

    def setUp(self) -> None:
        """Start a fixture server and create a temporary directory."""
        self.server, self.url = self.start_server()
        self.login = {"email": "operator@example.com", "password": secrets.token_urlsafe(24)}
        self.server.login = self.login
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def start_server(self) -> tuple[FixtureServer, str]:
        """Start a fixture server on an available loopback port."""
        server = FixtureServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        server.received = []
        server.token = secrets.token_urlsafe(24)
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        return server, f"http://127.0.0.1:{server.server_port}"

    def run_cli(self, *args: str, url: str | None = None, **credentials: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        """Run the CLI with fixture credentials and parse its JSON output."""
        env = {key: value for key, value in os.environ.items() if not key.startswith("CONTEXTFORGE_")}
        env.update(credentials or {"CONTEXTFORGE_TOKEN": self.server.token})
        result = subprocess.run([sys.executable, "-B", str(CLI), "--base-url", url or self.url, *args], env=env, capture_output=True, text=True, timeout=15, check=False)
        return result, json.loads(result.stdout)

    def body_file(self, payload: Any) -> str:
        """Write a JSON request body to the temporary directory."""
        path = self.directory / "request.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_bearer_read_keeps_prefix_and_redacts_secrets(self) -> None:
        """Keep the gateway path prefix and mask the token in the response."""
        proc, result = self.run_cli("request", "GET", "/v1/teams/?limit=1", url=self.url + "/gateway", CONTEXTFORGE_TOKEN=self.server.token, CONTEXTFORGE_EMAIL="unused@example.com")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(result["data"]["teams"], [{"name": "Support", "authTokenUnmasked": "[REDACTED]"}])
        self.assertEqual(self.server.received, [("GET", "/gateway/v1/teams/?limit=1", "Bearer " + self.server.token, None)])
        self.assertNotIn(self.server.token, proc.stdout)

    def test_write_requires_opt_in_and_uses_login_token(self) -> None:
        """Require the write flag before login or a write request."""
        path = self.body_file({"associated_tools": ["first-id", "second-id"]})
        credentials = {"CONTEXTFORGE_EMAIL": self.login["email"], "CONTEXTFORGE_PASSWORD": self.login["password"]}
        proc, result = self.run_cli("request", "PUT", "/v1/example", "--body-file", path, **credentials)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--write", result["data"]["error"])
        self.assertEqual(self.server.received, [])
        proc, result = self.run_cli("request", "PUT", "/v1/example", "--body-file", path, "--write", **credentials)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self.server.received,
            [
                ("POST", "/v1/auth/email/login", None, self.login),
                ("PUT", "/v1/example", "Bearer " + self.server.token, {"associated_tools": ["first-id", "second-id"]}),
            ],
        )
        self.assertEqual(result["data"]["received"]["associated_tools"], ["first-id", "second-id"])

    def test_redirect_returns_the_original_status_without_sending_auth_elsewhere(self) -> None:
        """Keep the token on the selected gateway when a redirect occurs."""
        other, other_url = self.start_server()
        self.server.location = other_url + "/v1/example"
        for args in [("GET", "/redirect"), ("POST", "/redirect", "--write", "--body-file", self.body_file({"name": "Support"}))]:
            proc, result = self.run_cli("request", *args, HTTP_PROXY=other_url, NO_PROXY="", CONTEXTFORGE_TOKEN=self.server.token)
            self.assertEqual((proc.returncode, result["status"]), (1, 307))
        self.assertEqual(len(self.server.received), 2)
        self.assertEqual(other.received, [])

    def test_request_secret_does_not_escape_in_validation_errors(self) -> None:
        """Mask a request secret in a gateway validation error."""
        secret = secrets.token_urlsafe(24)
        path = self.body_file({"client_secret": secret})
        proc, result = self.run_cli("request", "PUT", "/v1/example", "--body-file", path, "--write")
        self.assertEqual((proc.returncode, result["status"]), (1, 422))
        self.assertNotIn(secret, proc.stdout + proc.stderr)
        self.assertEqual(result["data"]["detail"][0]["input"], "[REDACTED]")

    def test_failed_login_does_not_echo_password_or_make_the_api_request(self) -> None:
        """Mask the password and stop after a login failure."""
        password = secrets.token_urlsafe(24)
        proc, result = self.run_cli("request", "GET", "/v1/teams/", CONTEXTFORGE_EMAIL=self.login["email"], CONTEXTFORGE_PASSWORD=password)
        self.assertEqual((proc.returncode, result["status"]), (1, 401))
        self.assertNotIn(password, proc.stdout + proc.stderr)
        self.assertEqual([entry[1] for entry in self.server.received], ["/v1/auth/email/login"])

    def test_new_response_secrets_are_masked_in_fields_and_repeated_links(self) -> None:
        """Mask an invitation token in its response fields and links."""
        self.server.invitation = secrets.token_urlsafe(24)
        self.server.private_link = secrets.token_urlsafe(24)
        proc, result = self.run_cli("request", "POST", "/v1/example/invitation", "--write")
        self.assertEqual((proc.returncode, result["status"]), (0, 201))
        self.assertNotIn(self.server.invitation, proc.stdout)
        self.assertNotIn(self.server.private_link, proc.stdout)
        self.assertEqual(result["data"]["repeated_link"], "https://gateway.example.com/join/[REDACTED]")
        self.assertEqual(result["data"]["invitation_url"], "[REDACTED]")

    def test_live_schema_preserves_fields_and_includes_referenced_components(self) -> None:
        """Find local schema references and remove example values."""
        proc, result = self.run_cli("describe", "PUT", "/v1/example/{id}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        components = result["data"]["components"]
        self.assertEqual(components["schemas"]["Node"]["properties"]["password"], {"type": "string"})
        self.assertEqual(components["schemas"]["Node"]["properties"]["invite_url"], {"type": "string"})
        self.assertEqual(components["parameters"]["Id"]["in"], "path")
        self.assertNotIn("omit-this-example", proc.stdout)
        proc, result = self.run_cli("catalog")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual({item["method"] for item in result["data"]}, {"GET", "PUT"})


class URLTests(unittest.TestCase):
    """Test validation of gateway URLs and API paths."""

    def test_rejects_hosts_with_credentials_and_paths_that_escape_the_base(self) -> None:
        """Reject URLs that contain secrets or alter the gateway origin or prefix."""
        base = "https://gateway.example.com/gateway/"
        cases = [
            ("http://gateway.example.com", "/v1/teams/"),
            (f"https://operator:{secrets.token_urlsafe(24)}@gateway.example.com", "/v1/teams/"),
            ("https://gateway.example.com/?token=embedded", "/v1/teams/"),
            ("https://gateway.example.com:99999", "/v1/teams/"),
            (base, "//example.net/v1/teams/"),
            (base, "/\\example.net/v1/teams/"),
            (base, "/..//example.net"),
            (base, "/%252e%252e/example"),
            (base, "/example%2fdata"),
            (base, "/%0d%0aInjected"),
        ]
        for origin, path in cases:
            with self.subTest(origin=origin, path=path), self.assertRaises(ValueError):
                cf_api.checked_url(origin, path)
        self.assertEqual(cf_api.checked_url(base, "/v1/users/a%40example.com?limit=2"), base + "v1/users/a%40example.com?limit=2")


if __name__ == "__main__":
    unittest.main()
