# -*- coding: utf-8 -*-
# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import os
from typing import Any, Dict, List, Optional

# Third-Party
import httpx


@dataclass
class ToolDef:
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    # extra fields from /tools to enable direct REST execution
    url: Optional[str] = None
    method: Optional[str] = None           # maps requestType
    headers: Optional[Dict[str, Any]] = None
    integration_type: Optional[str] = None # e.g. "REST"
    jsonpath_filter: Optional[str] = None  # not applied in MVP


class MCPClient:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url
        self.token = token
        self._client = httpx.Client()

    @classmethod
    def from_env(cls, base_url: str | None = None) -> "MCPClient":
        url = base_url or os.getenv("MCP_GATEWAY_URL", "http://localhost:4444")
        token = os.getenv("MCPGATEWAY_BEARER_TOKEN") or os.getenv("GATEWAY_BEARER_TOKEN")  # Support both names
        return cls(url, token)

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def list_tools(self) -> List[ToolDef]:
        """
        Lists all available MCP tools from this server.

        Returns:
            List of ToolDef objects, each representing a callable tool.
            Returns empty list if server unreachable or no tools.
        """
        try:
            for path in ("/tools", "/admin/tools"):
                url = f"{self.base_url}{path}"
                resp = self._client.get(url, headers=self._headers())
                if getattr(self, "debug", False):
                    print(f"[MCPClient] GET {url} -> {resp.status_code}")
                if resp.status_code // 100 != 2:
                    continue
                data = resp.json()
                raw_tools = data if isinstance(data, list) else data.get("tools", [])
                out: List[ToolDef] = []
                for t in raw_tools:
                    out.append(
                        ToolDef(
                            id = t.get("id") or t.get("tool_id") or t.get("name"),
                            name = t.get("name") or t.get("originalName") or t.get("originalNameSlug"),
                            description = t.get("description"),
                            # schemas in either snake_case or camelCase
                            schema = t.get("input_schema") or t.get("inputSchema") or t.get("schema"),
                            # fields for direct REST execution
                            url = t.get("url"),
                            method = (t.get("requestType") or t.get("method") or "GET"),
                            headers = (t.get("headers") or {}) if isinstance(t.get("headers"), dict) else {},
                            integration_type = t.get("integrationType"),
                            jsonpath_filter = t.get("jsonpathFilter"),
                        )
                    )
                return out
            return []
        except Exception:
            return []

    def invoke_tool(self, tool_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Try multiple execution surfaces:
        1) JSON-RPC /rpc with method=<tool name or id>, params=<args>
        2) RESTful invoke/execute variants under /tools and /admin/tools
        3) Batch invoke endpoints
        4) (fallback) Direct REST call to the tool's URL using metadata from /tools

        Includes schema validation based on tool introspection.
        """
        # Best-effort: fetch catalog to find a human name for /rpc and resolve name to ID
        name_for_rpc = None
        actual_tool_id = tool_id
        tool_meta: Optional[ToolDef] = None
        try:
            tools = self.list_tools()
            for t in tools:
                # If user provided a name, find the corresponding ID
                if t.name == tool_id:
                    actual_tool_id = t.id
                    name_for_rpc = t.name
                    tool_meta = t
                    break
                # If user provided an ID, find the corresponding name
                elif t.id == tool_id:
                    name_for_rpc = t.name or t.id
                    tool_meta = t
                    break
        except Exception:
            pass

        # Validate arguments against tool schema if available
        if tool_meta and tool_meta.schema:
            validation_result = self._validate_args_against_schema(args, tool_meta.schema, tool_id)
            if not validation_result["valid"]:
                return {
                    "tool_id": actual_tool_id,
                    "error": f"Schema validation failed: {validation_result['error']}",
                    "schema": tool_meta.schema,
                    "provided_args": args
                }

        candidates = []
        # JSON-RPC first (by name, then id)
        if name_for_rpc:
            candidates.append(("POST", "/rpc", {"jsonrpc":"2.0","id":"1","method":name_for_rpc,"params":args}))
        candidates.append(("POST", "/rpc", {"jsonrpc":"2.0","id":"1","method":actual_tool_id,"params":args}))

        # Tool-specific invoke/execute variants (use actual ID)
        for base in ("/tools", "/admin/tools"):
            candidates.extend([
                ("POST", f"{base}/{actual_tool_id}/invoke", {"args": args}),
                ("POST", f"{base}/{actual_tool_id}/execute", {"args": args}),
            ])

        # Batch invoke with payload carrying the id
        for base in ("/tools", "/admin/tools"):
            candidates.extend([
                ("POST", f"{base}/invoke", {"id": actual_tool_id, "args": args}),
                ("POST", f"{base}/execute", {"id": actual_tool_id, "args": args}),
            ])

        last_err = None
        for method, path, body in candidates:
            try:
                url = f"{self.base_url}{path}"
                if getattr(self, "debug", False):
                    print(f"[MCPClient] {method} {url} body={body}")
                r = self._client.request(method, url, headers=self._headers(), json=body)
                if getattr(self, "debug", False):
                    print(f"[MCPClient] -> {r.status_code}, {r.text[:160]}")

                if r.status_code // 100 == 2:
                    response_data = r.json()
                    # Check if it's a JSON-RPC error response
                    if "error" in response_data and "jsonrpc" in response_data:
                        last_err = f"JSON-RPC error: {response_data['error'].get('message', 'Unknown error')}"
                        continue  # Try next method instead of returning error
                    return response_data

                if r.status_code in (401, 403):
                    return {"error": f"Auth failed at {path} (HTTP {r.status_code})."}
                last_err = f"HTTP {r.status_code}"
            except Exception as e:
                last_err = str(e)

        # --- FINAL FALLBACK: direct REST execution using tool metadata ---
        if tool_meta and tool_meta.integration_type == "REST" and tool_meta.url:
            try:
                # Handle different method types
                method_type = (tool_meta.method or "GET").upper()

                # SSE is typically GET with streaming, treat as GET for direct calls
                if method_type == "SSE":
                    method_type = "GET"

                headers = tool_meta.headers or {}
                # Don't overwrite explicit Content-Type if provided in tool
                if "Content-Type" not in {k.title(): v for k, v in headers.items()}:
                    headers.setdefault("Content-Type", "application/json")

                # Build request
                if method_type in ("GET", "HEAD", "DELETE"):
                    # For GET requests, add args as query parameters
                    resp = self._client.request(method_type, tool_meta.url, params=args, headers=headers)
                else:
                    # For POST/PUT, send args as JSON body
                    payload = args.get("body", args) if isinstance(args, dict) else args
                    resp = self._client.request(method_type, tool_meta.url, json=payload, headers=headers)

                # Parse result
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text

                return {
                    "tool_id": actual_tool_id,
                    "executed_via": "direct_rest_fallback",
                    "request": {"url": tool_meta.url, "method": method_type},
                    "status_code": resp.status_code,
                    "result": data,
                    "schema_validated": tool_meta.schema is not None
                }
            except Exception as e:
                last_err = f"direct_rest_error: {e}"

        return {"tool_id": actual_tool_id, "args": args, "note": "No invoke path worked", "last_error": last_err}

    def _validate_args_against_schema(self, args: Dict[str, Any], schema: Dict[str, Any], tool_id: str) -> Dict[str, Any]:
        """Validate arguments against tool schema"""
        try:
            # Basic schema validation
            if not isinstance(schema, dict):
                return {"valid": True, "note": "Schema not a dict, skipping validation"}

            schema_type = schema.get("type")
            if schema_type != "object":
                return {"valid": True, "note": f"Schema type '{schema_type}' not object, skipping validation"}

            properties = schema.get("properties", {})
            required = schema.get("required", [])

            # Check required fields
            missing_required = []
            for req_field in required:
                if req_field not in args:
                    missing_required.append(req_field)

            if missing_required:
                return {
                    "valid": False,
                    "error": f"Missing required fields: {missing_required}",
                    "required": required,
                    "provided": list(args.keys())
                }

            # Check for unexpected fields (warning only)
            unexpected_fields = []
            for arg_key in args.keys():
                if arg_key not in properties:
                    unexpected_fields.append(arg_key)

            result = {"valid": True}
            if unexpected_fields:
                result["warnings"] = f"Unexpected fields (not in schema): {unexpected_fields}"

            return result

        except Exception as e:
            return {"valid": True, "note": f"Schema validation error: {e}"}
