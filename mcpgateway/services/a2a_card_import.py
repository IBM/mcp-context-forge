# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_card_import.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Fetch an A2A Agent Card from an unregistered endpoint and map it onto agent fields.

The fetch applies the outbound URL policy and DNS pinning before any I/O. The result
names one outcome: ``found``, ``no_card``, ``auth_required`` or ``unreachable``. A
blocked address and a network failure both report ``unreachable``, so the response
cannot reveal which hosts the gateway can or cannot reach.
"""

# Standard
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Third-Party
import orjson

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.schemas import A2AFetchCardResponse
from mcpgateway.services.http_client_service import get_isolated_http_client
from mcpgateway.utils.ssrf_pinning import resolve_pinned_target
from mcpgateway.utils.url_auth import sanitize_url_for_logging

logger = logging.getLogger(__name__)

CARD_PATH_V1 = "/.well-known/agent-card.json"
CARD_PATH_LEGACY = "/.well-known/agent.json"
MAX_CARD_BYTES = 1024 * 1024
NOT_FOUND_REASON = "No A2A Agent Card was found at the given location."
AUTH_REQUIRED_REASON = "The agent requires credentials to return its Agent Card."
UNREACHABLE_REASON = "The agent could not be reached."

_AUTH_SCHEME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,32}$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_DEFAULT_PROTOCOL_BINDING = "JSONRPC"

_AUTH_TYPE_BY_HTTP_SCHEME = {"basic": "basic", "bearer": "bearer"}


class CardPathError(ValueError):
    """Raised when a caller-supplied card path is not a plain URL path."""


def build_candidate_urls(base_url: str, path: Optional[str]) -> List[str]:
    """Return the card URLs to try, in order.

    An explicit ``path`` is the only candidate. A base URL that already names a
    ``.json`` document is used as given. Otherwise the 1.0 well-known path is tried
    first and the pre-1.0 path second.

    Args:
        base_url: Endpoint or direct card URL supplied by the caller.
        path: Optional path appended to ``base_url``.

    Returns:
        Ordered candidate URLs.

    Raises:
        CardPathError: If ``path`` contains a query, fragment, traversal or unsafe character.

    Examples:
        >>> build_candidate_urls("https://agent.example.com", None)
        ['https://agent.example.com/.well-known/agent-card.json', 'https://agent.example.com/.well-known/agent.json']
        >>> build_candidate_urls("https://agent.example.com/card.json", None)
        ['https://agent.example.com/card.json']
        >>> build_candidate_urls("https://agent.example.com/", "/x/card.json")
        ['https://agent.example.com/x/card.json']
        >>> build_candidate_urls("https://agent.example.com", "/../etc")
        Traceback (most recent call last):
            ...
        mcpgateway.services.a2a_card_import.CardPathError: Card path is not allowed
    """
    base = base_url.strip()
    parsed = urlparse(base)
    if path:
        if not _SAFE_PATH_RE.match(path) or any(segment in ("..", ".") for segment in path.split("/")):
            raise CardPathError("Card path is not allowed")
        return [f"{base.rstrip('/')}/{path.lstrip('/')}"]
    if parsed.path.lower().endswith(".json"):
        return [base]
    root = base.rstrip("/")
    return [f"{root}{CARD_PATH_V1}", f"{root}{CARD_PATH_LEGACY}"]


def _scheme_key(scheme: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return the 1.0 oneof key and body of a security scheme.

    Args:
        scheme: A 1.0 ``SecurityScheme`` object.

    Returns:
        ``(key, body)`` for the single populated variant, or ``("", {})``.
    """
    for key, body in scheme.items():
        if key.endswith("SecurityScheme") and isinstance(body, dict):
            return key, body
    return "", {}


def _convert_legacy_scheme(scheme: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a pre-1.0 flat security scheme to the 1.0 oneof shape.

    Args:
        scheme: A 0.3 ``SecurityScheme`` object keyed by ``type``.

    Returns:
        The 1.0 equivalent, or ``None`` for an unrecognised type.
    """
    scheme_type = str(scheme.get("type", "")).lower()
    if scheme_type == "http":
        return {"httpAuthSecurityScheme": {"scheme": scheme.get("scheme", "")}}
    if scheme_type == "apikey":
        return {"apiKeySecurityScheme": {"location": scheme.get("in", "header"), "name": scheme.get("name", "")}}
    if scheme_type == "oauth2":
        return {"oauth2SecurityScheme": {"flows": scheme.get("flows", {})}}
    if scheme_type == "openidconnect":
        return {"openIdConnectSecurityScheme": {"openIdConnectUrl": scheme.get("openIdConnectUrl", "")}}
    if scheme_type == "mutualtls":
        return {"mtlsSecurityScheme": {}}
    return None


def _convert_legacy_requirements(security: List[Dict[str, List[str]]]) -> List[Dict[str, Any]]:
    """Convert pre-1.0 ``security`` requirements to 1.0 ``securityRequirements``.

    Args:
        security: List of ``{scheme_name: [scopes]}`` objects.

    Returns:
        List of ``{"schemes": {scheme_name: StringList}}`` objects.
    """
    requirements = []
    for entry in security:
        schemes = {name: ({"list": scopes} if scopes else {}) for name, scopes in entry.items()}
        requirements.append({"schemes": schemes})
    return requirements


def _normalize_legacy_card(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a pre-1.0 card to the 1.0 shape.

    Args:
        raw: Card as published by a 0.3 agent.

    Returns:
        The card in the 1.0 shape. Fields 1.0 does not define are dropped.
    """
    protocol_version = raw.get("protocolVersion") or "0.3"
    interfaces: List[Dict[str, Any]] = []
    if raw.get("url"):
        interfaces.append({"url": raw["url"], "protocolBinding": raw.get("preferredTransport") or _DEFAULT_PROTOCOL_BINDING, "protocolVersion": protocol_version})
    for extra in raw.get("additionalInterfaces") or []:
        if isinstance(extra, dict) and extra.get("url"):
            interfaces.append({"url": extra["url"], "protocolBinding": extra.get("transport") or _DEFAULT_PROTOCOL_BINDING, "protocolVersion": protocol_version})

    legacy_caps = raw.get("capabilities") or {}
    capabilities: Dict[str, Any] = {
        "streaming": bool(legacy_caps.get("streaming", False)),
        "pushNotifications": bool(legacy_caps.get("pushNotifications", False)),
        "extendedAgentCard": bool(raw.get("supportsAuthenticatedExtendedCard", False)),
    }
    if legacy_caps.get("extensions"):
        capabilities["extensions"] = legacy_caps["extensions"]

    card: Dict[str, Any] = {
        key: raw[key] for key in ("name", "description", "version", "provider", "documentationUrl", "iconUrl", "defaultInputModes", "defaultOutputModes", "skills", "signatures") if key in raw
    }
    card["supportedInterfaces"] = interfaces
    card["capabilities"] = capabilities

    schemes = {}
    for name, scheme in (raw.get("securitySchemes") or {}).items():
        converted = _convert_legacy_scheme(scheme) if isinstance(scheme, dict) else None
        if converted:
            schemes[name] = converted
    if schemes:
        card["securitySchemes"] = schemes
        card["securityRequirements"] = _convert_legacy_requirements(raw.get("security") or [])
    return card


def is_agent_card(raw: Any) -> bool:
    """Report whether a parsed document looks like an A2A Agent Card.

    Args:
        raw: Parsed JSON document.

    Returns:
        True when the document is an object with a name and at least one endpoint.

    Examples:
        >>> is_agent_card({"name": "a", "supportedInterfaces": [{"url": "https://x"}]})
        True
        >>> is_agent_card({"name": "a", "url": "https://x"})
        True
        >>> is_agent_card({"name": "a"})
        False
        >>> is_agent_card([])
        False
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
        return False
    interfaces = raw.get("supportedInterfaces")
    if isinstance(interfaces, list):
        return any(isinstance(item, dict) and item.get("url") for item in interfaces)
    return isinstance(raw.get("url"), str) and bool(raw["url"])


def normalize_card(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Return the card in the 1.0 shape and the detected card version.

    Args:
        raw: Card as fetched.

    Returns:
        ``(card, version)`` where version is ``"1.0"`` or ``"0.3"``.

    Examples:
        >>> card, version = normalize_card({"name": "a", "url": "https://x", "protocolVersion": "0.3.0", "supportsAuthenticatedExtendedCard": True})
        >>> version, card["supportedInterfaces"][0]["protocolVersion"], card["capabilities"]["extendedAgentCard"]
        ('0.3', '0.3.0', True)
        >>> normalize_card({"name": "a", "supportedInterfaces": [{"url": "https://x"}]})[1]
        '1.0'
    """
    if isinstance(raw.get("supportedInterfaces"), list):
        return raw, "1.0"
    return _normalize_legacy_card(raw), "0.3"


def _select_interface(card: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the interface ContextForge will call, preferring JSONRPC.

    Args:
        card: Card in the 1.0 shape with at least one interface.

    Returns:
        The selected interface object.
    """
    interfaces = [item for item in card.get("supportedInterfaces", []) if isinstance(item, dict) and item.get("url")]
    for item in interfaces:
        if str(item.get("protocolBinding", _DEFAULT_PROTOCOL_BINDING)).upper() == _DEFAULT_PROTOCOL_BINDING:
            return item
    return interfaces[0]


def _suggest_auth(card: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Choose one ``A2AAgentCreate`` auth configuration from the declared security.

    ContextForge stores one ``auth_type``. When the card offers several alternatives,
    the first requirement that maps to a supported type wins and the rest are reported.

    Args:
        card: Card in the 1.0 shape.

    Returns:
        ``(fields, warnings)``: auth fields for the suggestion, and notes on what was skipped.
    """
    schemes = card.get("securitySchemes") or {}
    warnings: List[str] = []
    chosen: Dict[str, Any] = {}
    for requirement in card.get("securityRequirements") or []:
        for name, scopes in (requirement.get("schemes") or {}).items():
            key, body = _scheme_key(schemes.get(name) or {})
            fields = _auth_fields(key, body, scopes)
            if fields and not chosen:
                chosen = fields
            elif fields:
                warnings.append(f"Security scheme '{name}' is an alternative that was not selected.")
            else:
                warnings.append(f"Security scheme '{name}' is not supported and was ignored.")
    return chosen, warnings


def _auth_fields(key: str, body: Dict[str, Any], scopes: Any) -> Dict[str, Any]:
    """Map one 1.0 security scheme to ``A2AAgentCreate`` auth fields.

    Args:
        key: Oneof key such as ``httpAuthSecurityScheme``.
        body: The scheme body.
        scopes: The ``StringList`` required by the requirement.

    Returns:
        Auth fields without credential values, or an empty dict when unsupported.
    """
    if key == "httpAuthSecurityScheme":
        auth_type = _AUTH_TYPE_BY_HTTP_SCHEME.get(str(body.get("scheme", "")).lower())
        return {"auth_type": auth_type} if auth_type else {}
    if key == "apiKeySecurityScheme" and body.get("name"):
        location = str(body.get("location", "header")).lower()
        if location == "query":
            return {"auth_type": "query_param", "auth_query_param_key": body["name"]}
        if location == "header":
            return {"auth_type": "authheaders", "auth_header_key": body["name"]}
        return {}
    if key == "oauth2SecurityScheme":
        flows = body.get("flows") or {}
        wanted = scopes.get("list", []) if isinstance(scopes, dict) else []
        if "clientCredentials" in flows:
            flow = flows["clientCredentials"]
            return {"auth_type": "oauth", "oauth_config": {"grant_type": "client_credentials", "token_url": flow.get("tokenUrl"), "scopes": wanted or list((flow.get("scopes") or {}).keys())}}
        if "authorizationCode" in flows:
            flow = flows["authorizationCode"]
            return {
                "auth_type": "oauth",
                "oauth_config": {
                    "grant_type": "authorization_code",
                    "authorization_url": flow.get("authorizationUrl"),
                    "token_url": flow.get("tokenUrl"),
                    "scopes": wanted or list((flow.get("scopes") or {}).keys()),
                },
            }
    return {}


def suggest_agent_fields(card: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Map a 1.0 card onto ``A2AAgentCreate`` fields.

    This is the import counterpart of ``A2AAgentService._build_v1_agent_card``. The
    round-trip test in ``tests/unit/mcpgateway/services/test_a2a_card_import.py`` pins
    the two together. Credential values, team, visibility and tags are never produced.

    Args:
        card: Card in the 1.0 shape with at least one interface.

    Returns:
        ``(fields, warnings)``.

    Examples:
        >>> fields, _ = suggest_agent_fields({"name": "a", "version": "2", "supportedInterfaces": [{"url": "https://x/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]})
        >>> fields["endpoint_url"], fields["protocol_version"], fields["version"]
        ('https://x/rpc', '1.0', '2')
    """
    interface = _select_interface(card)
    warnings: List[str] = []
    if str(interface.get("protocolBinding", _DEFAULT_PROTOCOL_BINDING)).upper() != _DEFAULT_PROTOCOL_BINDING:
        warnings.append(f"No JSONRPC interface is declared. ContextForge calls agents over JSONRPC, but the selected interface uses {interface.get('protocolBinding')}.")

    card_caps = card.get("capabilities") or {}
    capabilities: Dict[str, Any] = {
        "streaming": bool(card_caps.get("streaming", False)),
        "pushNotifications": bool(card_caps.get("pushNotifications", False)),
        "skills": card.get("skills") or [],
    }
    if card_caps.get("extensions"):
        capabilities["extensions"] = card_caps["extensions"]
    for key in ("defaultInputModes", "defaultOutputModes"):
        if card.get(key):
            capabilities[key] = card[key]

    fields: Dict[str, Any] = {
        "name": card["name"],
        "description": card.get("description") or None,
        "endpoint_url": interface["url"],
        "protocol_version": str(interface.get("protocolVersion") or "1.0"),
        "version": str(card["version"]) if card.get("version") else None,
        "capabilities": capabilities,
    }
    auth_fields, auth_warnings = _suggest_auth(card)
    fields.update(auth_fields)
    warnings.extend(auth_warnings)
    return {key: value for key, value in fields.items() if value is not None}, warnings


def not_found() -> A2AFetchCardResponse:
    """Build the response for a reachable host that serves no Agent Card.

    Returns:
        A response with outcome ``no_card`` and a fixed reason.
    """
    return A2AFetchCardResponse(found=False, outcome="no_card", reason=NOT_FOUND_REASON)


def unreachable() -> A2AFetchCardResponse:
    """Build the response for a blocked address or a failed connection.

    Both causes share this response, so the route cannot probe which hosts the gateway reaches.

    Returns:
        A response with outcome ``unreachable`` and a fixed reason.
    """
    return A2AFetchCardResponse(found=False, outcome="unreachable", reason=UNREACHABLE_REASON)


def auth_required(challenge: Optional[str]) -> A2AFetchCardResponse:
    """Build the response for a card endpoint that answered 401 or 403.

    Args:
        challenge: Value of the ``WWW-Authenticate`` header, if any.

    Returns:
        A response with outcome ``auth_required`` and the challenge scheme name.
    """
    return A2AFetchCardResponse(found=False, outcome="auth_required", reason=AUTH_REQUIRED_REASON, auth_scheme=_challenge_scheme(challenge))


def _challenge_scheme(challenge: Optional[str]) -> Optional[str]:
    """Extract the scheme name from a ``WWW-Authenticate`` value.

    Args:
        challenge: Raw header value.

    Returns:
        The scheme token, or ``None`` when the header is absent or malformed.
    """
    parts = (challenge or "").split(None, 1)
    return parts[0] if parts and _AUTH_SCHEME_RE.match(parts[0]) else None


async def _get_json(url: str, headers: Optional[Dict[str, str]]) -> Tuple[Optional[int], Any, Optional[str]]:
    """GET one URL under the outbound policy and parse a size-capped JSON body.

    Args:
        url: Candidate card URL.
        headers: Optional caller headers, sent only to this URL's pinned host.

    Returns:
        ``(status, document, challenge)``. ``status`` is ``None`` when the request was blocked or failed;
        ``document`` is ``None`` unless the response was a 200 JSON body; ``challenge`` is the
        ``WWW-Authenticate`` value of a non-200 response.
    """
    try:
        target = await resolve_pinned_target(url, "A2A card URL")
    except ValueError as exc:
        logger.warning("A2A card URL rejected by outbound policy: %s (%s)", sanitize_url_for_logging(url), SecurityValidator.sanitize_log_message(str(exc)))
        return None, None, None

    request_headers = target.apply_headers({"Accept": "application/json", **(headers or {})})
    try:
        async with get_isolated_http_client(follow_redirects=False, timeout=float(settings.federation_timeout)) as client:
            async with client.stream("GET", target.pin(target.validated_url), headers=request_headers, extensions=target.extensions) as response:
                if response.status_code != 200:
                    return response.status_code, None, response.headers.get("www-authenticate")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_CARD_BYTES:
                        logger.warning("A2A card from %s exceeds %d bytes", sanitize_url_for_logging(url), MAX_CARD_BYTES)
                        return 200, None, None
        return 200, orjson.loads(bytes(body)), None
    except orjson.JSONDecodeError:
        return 200, None, None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("A2A card fetch failed for %s: %s", sanitize_url_for_logging(url), SecurityValidator.sanitize_log_message(type(exc).__name__))
        return None, None, None


async def fetch_agent_card(base_url: str, path: Optional[str], headers: Optional[Dict[str, str]]) -> A2AFetchCardResponse:
    """Fetch, validate and normalize an Agent Card from an unregistered endpoint.

    Falls back to the pre-1.0 well-known path only on a 404 from the 1.0 path. A 401 or 403
    stops the search with ``auth_required`` so the caller can retry with credentials.

    Args:
        base_url: Endpoint or direct card URL.
        path: Optional explicit card path.
        headers: Optional headers, for example credentials for an authenticated card.

    Returns:
        The normalized card with a suggested agent mapping, or a response naming why no card was returned.
    """
    try:
        candidates = build_candidate_urls(base_url, path)
    except CardPathError:
        return not_found()

    for url in candidates:
        status, document, challenge = await _get_json(url, headers)
        if status is None:
            return unreachable()
        if status in (401, 403):
            return auth_required(challenge)
        if status == 404:
            continue
        if document is None or not is_agent_card(document):
            return not_found()
        card, version = normalize_card(document)
        fields, warnings = suggest_agent_fields(card)
        return A2AFetchCardResponse(found=True, outcome="found", source_url=url, detected_version=version, card=card, raw_card=document, suggested_agent=fields, warnings=warnings)
    return not_found()
