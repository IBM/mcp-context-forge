#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Call a ContextForge management API or inspect its live OpenAPI schema.
Location: ./.agents/skills/contextforge-admin/scripts/cf_api.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

import argparse
from collections.abc import Iterator, Mapping, Sequence
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
from typing import Any, NoReturn, cast
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import BaseHandler, HTTPRedirectHandler, OpenerDirector, ProxyHandler, Request, build_opener


READ_METHODS = {"GET", "HEAD", "OPTIONS"}
METHODS = sorted(READ_METHODS | {"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
NO_BODY = object()
REDACTED = "[REDACTED]"
SENSITIVE = re.compile(
    r"password|secret|credential|(?:^|_)(?:token|api_key|client_key|private_key|authorization|auth_value|"
    r"headers|cookie|code|code_verifier|client_assertion|invite_url|invitation_url|invite_link|invitation_link)(?:$|_)",
    re.IGNORECASE,
)
AUTH_TEXT = re.compile(r'\b(Bearer|Basic)\s+[^\s"<>]+', re.IGNORECASE)
JWT_TEXT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
SECRET_QUERY = re.compile(r"([?&](?:code|code_verifier|(?:access_|refresh_|id_|invite_|invitation_)?token|client_secret|api_key|password)=)[^&\s]+", re.IGNORECASE)


class InputError(ValueError):
    """Report an input value that the caller can correct."""


class ArgumentParser(argparse.ArgumentParser):
    """Parse CLI arguments without exposing their values in errors."""

    def error(self, message: str) -> NoReturn:
        """Raise the same error for all invalid arguments."""
        raise InputError("Invalid arguments. See --help for usage.")


class NoRedirect(HTTPRedirectHandler):
    """Keep the request on the gateway that the caller specified."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        """Refuse to follow a redirect."""
        return None


def unsafe_characters(value: str) -> bool:
    """Detect characters that a URL parser can normalize or reject."""
    return "\\" in value or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def clean_path(path: str) -> bool:
    """Check for path traversal, separators, and control characters after decoding."""
    decoded = path
    while "%" in decoded:
        next_path = unquote(decoded)
        if next_path == decoded:
            break
        decoded = next_path
    return "\\" not in decoded and not any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded) and decoded.count("/") == path.count("/") and not {".", ".."}.intersection(decoded.split("/"))


def checked_url(base: str, path: str) -> str:
    """Join an API path to a validated gateway URL and preserve its path prefix."""
    if unsafe_characters(base) or "?" in base or "#" in base:
        raise InputError("Provide an HTTP(S) base URL without credentials, query, or fragment.")
    try:
        host = urlsplit(base)
        port = host.port
    except ValueError:
        raise InputError("Invalid gateway base URL.") from None
    if host.scheme not in {"http", "https"} or not host.hostname or host.username is not None or "%" in host.netloc or port == 0 or host.path.startswith("//") or not clean_path(host.path):
        raise InputError("Provide an HTTP(S) base URL with a clean optional path prefix.")
    if host.scheme == "http" and host.hostname not in LOOPBACK:
        raise InputError("Use HTTPS for gateways outside loopback.")
    if not path.startswith("/") or path.startswith("//") or "#" in path or unsafe_characters(path) or not clean_path(path.partition("?")[0]):
        raise InputError("Use an absolute API path on the selected gateway, for example /v1/teams/.")
    return base.rstrip("/") + path


def sensitive_key(key: str) -> bool:
    """Recognize fields that can contain authentication data."""
    key = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return bool(SENSITIVE.search(key.replace("-", "_")))


def secret_strings(value: Any, sensitive: bool = False) -> Iterator[str]:
    """Find string values to mask if they occur elsewhere in the response."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from secret_strings(item, sensitive or sensitive_key(key) or (key == "input" and "loc" in value))
    elif isinstance(value, list):
        for item in value:
            yield from secret_strings(item, sensitive)
    elif sensitive and isinstance(value, str) and value:
        yield value


def redact(value: Any, secrets: Sequence[str | None] = (), *, mask_fields: bool = True) -> Any:
    """Mask secret values and optionally mask fields that can contain them."""
    known = sorted({secret for secret in secrets if secret}, key=len, reverse=True)

    def safe_text(text: str) -> str:
        for secret in known:
            text = text.replace(secret, REDACTED)
        text = AUTH_TEXT.sub(r"\1 " + REDACTED, text)
        text = JWT_TEXT.sub(REDACTED, text)
        return SECRET_QUERY.sub(r"\1" + REDACTED, text)

    def visit(item: Any) -> Any:
        if isinstance(item, dict):
            return {safe_text(key): REDACTED if mask_fields and (sensitive_key(key) or (key == "input" and "loc" in item)) else visit(value) for key, value in item.items()}
        if isinstance(item, list):
            return [visit(value) for value in item]
        return safe_text(item) if isinstance(item, str) else item

    return visit(value)


def http_json(opener: OpenerDirector, url: str, method: str = "GET", body: Any = NO_BODY, token: str | None = None) -> tuple[int, Any]:
    """Send an HTTP request and return its status and JSON response."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not NO_BODY:
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        response = opener.open(request, timeout=30)
    except HTTPError as error:
        response = error
    if response is None:
        raise OSError("The gateway did not return an HTTP response.")
    with response:
        status = response.status
        if not isinstance(status, int):
            raise OSError("The gateway response did not include an HTTP status.")
        raw = response.read()
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, {"non_json_bytes": len(raw)}


def schema_only(value: Any, property_map: bool = False) -> Any:
    """Remove example and default values while preserving property names."""
    if isinstance(value, dict):
        return {key: schema_only(item, key == "properties") for key, item in value.items() if property_map or key not in {"default", "example", "examples"}}
    if isinstance(value, list):
        return [schema_only(item) for item in value]
    return value


def describe(document: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    """Return the OpenAPI operation and the local components it uses."""
    item = document["paths"].get(path, {})
    operation = item.get(method.lower())
    if not isinstance(operation, dict):
        raise InputError("Method and path are absent from the live OpenAPI. Use the path template.")
    path_parameters = item.get("parameters", [])
    components: dict[str, dict[str, Any]] = {}
    pending = [operation, path_parameters]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/"):
                segments = reference.removeprefix("#/components/").split("/")
                if len(segments) >= 2:
                    section, name = (part.replace("~1", "/").replace("~0", "~") for part in segments[:2])
                    target = document.get("components", {}).get(section, {}).get(name)
                    if target is not None and name not in components.setdefault(section, {}):
                        components[section][name] = target
                        pending.append(target)
            pending.extend(node.values())
    return cast(dict[str, Any], schema_only({"method": method, "path": path, "operation": operation, "path_parameters": path_parameters, "components": components}))


def error_result(status: int, message: str) -> dict[str, Any]:
    """Return a CLI error with the related HTTP status, if available."""
    return {"status": status, "data": {"error": message}}


def run(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Authenticate to the selected gateway and execute one CLI command."""
    path = args.path if args.operation == "request" else "/openapi.json"
    url = checked_url(args.base_url, path)
    body = NO_BODY
    if args.operation == "request":
        if args.method not in READ_METHODS and not args.write:
            raise InputError("This method requires --write. Use it for an authorized change.")
        if args.body_file:
            try:
                body = json.loads(args.body_file.read_text(encoding="utf-8-sig"))
                json.dumps(body, allow_nan=False)
            except (OSError, ValueError, RecursionError):
                raise InputError("The body file must contain readable JSON.") from None

    handlers: list[BaseHandler] = [NoRedirect()]
    if urlsplit(url).hostname in LOOPBACK:
        handlers.append(ProxyHandler({}))
    opener = build_opener(*handlers)
    token = environ.get("CONTEXTFORGE_TOKEN", "").strip()
    password = environ.get("CONTEXTFORGE_PASSWORD")
    if not token:
        email = environ.get("CONTEXTFORGE_EMAIL")
        if not email or not password:
            raise InputError("Set CONTEXTFORGE_TOKEN or both CONTEXTFORGE_EMAIL and CONTEXTFORGE_PASSWORD.")
        login_url = checked_url(args.base_url, "/v1/auth/email/login")
        status, reply = http_json(opener, login_url, "POST", {"email": email, "password": password})
        if not 200 <= status < 300:
            return error_result(status, "ContextForge login failed.")
        login_token = reply.get("access_token") if isinstance(reply, dict) else None
        if not isinstance(login_token, str) or not login_token:
            return error_result(0, "ContextForge login did not return an access token.")
        token = login_token
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token):
        raise InputError("The bearer token has an invalid format.")

    secrets = (token, password, *secret_strings(body))
    if args.operation == "request":
        status, result = http_json(opener, url, args.method, body, token)
        return {"status": status, "data": redact(result, (*secrets, *secret_strings(result)))}

    status, document = http_json(opener, url, token=token)
    if status != 200:
        return error_result(status, "ContextForge OpenAPI is unavailable.")
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        return error_result(0, "ContextForge did not return a usable OpenAPI document.")
    if args.operation == "describe":
        result = describe(document, args.method, args.path)
    else:
        result = [
            {"method": method.upper(), "path": path, "summary": operation.get("summary")}
            for path, item in sorted(document["paths"].items())
            for method, operation in item.items()
            if method.upper() in METHODS and isinstance(operation, dict)
        ]
    return {"status": status, "data": redact(result, secrets, mask_fields=False)}


def main(argv: list[str] | None = None) -> int:
    """Print a JSON result and return a process exit code."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="ContextForge HTTPS base URL")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("catalog", help="List methods and paths in the live OpenAPI")
    describe_command = commands.add_parser("describe", help="Show an operation and its local schema references")
    request_command = commands.add_parser("request", help="Call a ContextForge API")
    for command in (describe_command, request_command):
        command.add_argument("method", choices=METHODS, type=str.upper)
        command.add_argument("path")
    request_command.add_argument("--body-file", type=Path, help="Read the JSON request body from a file")
    request_command.add_argument("--write", action="store_true", help="Permit an authorized non-read HTTP method")
    try:
        result = run(parser.parse_args(argv), os.environ)
    except InputError as error:
        result = error_result(0, str(error))
    except (OSError, HTTPException, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        result = error_result(0, "The gateway or its response could not be read.")
    print(json.dumps(result))
    return 0 if 200 <= result["status"] < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
