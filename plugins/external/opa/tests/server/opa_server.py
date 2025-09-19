# -*- coding: utf-8 -*-
"""Test cases for OPA plugin

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module mocks up an opa server for testing.
"""


# Standard
import json
import threading

# Third-Party
from http.server import BaseHTTPRequestHandler, HTTPServer


# This class mocks up the post request for OPA server to evaluate policies.
class MockOPAHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/data/example/allow":
            content_length = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(post_body)
            if "IBM" in data["input"]["payload"]["args"]["repo_path"]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"result": true}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"result": false}')
            # Process data dictionary...
        except json.JSONDecodeError:
            # Handle invalid JSON
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

# This creates a mock up server for OPA at port 8181
def run_mock_opa():
    server = HTTPServer(('localhost', 8181), MockOPAHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
