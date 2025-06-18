#!/usr/bin/env python3
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Simple MCP Server for testing the translate bridge.
Implements basic MCP protocol with tools and resources.

"""

import asyncio
import json
import sys
from typing import Any, Dict, List

class SimpleMCPServer:
    def __init__(self):
        self.tools = [
            {
                "name": "echo",
                "description": "Echo back the input message",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "multiply",
                "description": "Multiply two numbers",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    },
                    "required": ["a", "b"]
                }
            }
        ]
        
        self.resources = [
            {
                "uri": "test://example",
                "name": "Test Resource",
                "description": "A test resource",
                "mimeType": "text/plain"
            }
        ]

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {}
                    },
                    "serverInfo": {
                        "name": "simple-test-server",
                        "version": "1.0.0"
                    }
                }
            }
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0", 
                "id": request_id,
                "result": {"tools": self.tools}
            }
            
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "echo":
                result = f"Echo: {arguments.get('message', 'No message')}"
            elif tool_name == "multiply":
                a = arguments.get("a", 0)
                b = arguments.get("b", 0)
                result = f"Result: {a} × {b} = {a * b}"
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                }
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": result
                    }]
                }
            }
            
        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id, 
                "result": {"resources": self.resources}
            }
            
        elif method == "resources/read":
            uri = params.get("uri")
            if uri == "test://example":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "contents": [{
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": "This is test resource content!"
                        }]
                    }
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": f"Resource not found: {uri}"}
                }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }

def main():
    """Main server loop."""
    server = SimpleMCPServer()
    
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                request = json.loads(line)
                response = server.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"}
                }
                print(json.dumps(error_response), flush=True)
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0", 
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
                }
                print(json.dumps(error_response), flush=True)
                
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
