# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/oauth_resource.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

RFC 8707 Resource Indicator utilities.

Single home for everything ``resource``-shaped in the OAuth flows:

* :func:`derive_resource_origin` — the auto-derived audience heuristic
  (``scheme://netloc`` of the upstream MCP server URL), used identically by
  the authorization request, the callback token exchange, the refresh
  request, and the inbound validator fallback so the IdP always sees one
  consistent ``resource`` value for a given gateway.
* :func:`normalize_resource` — RFC 8707 canonicalization for outbound
  ``resource`` parameters (fragment stripped; query policy by caller).
* :func:`parse_oauth_resource_form` — Admin UI form input → single URI or
  list of URIs, preserving the string/list shapes IdPs use for ``aud``
  (RFC 7519 §4.1.3).

Note on standards status: RFC 8707 §2.1 does not specify deriving a default
``resource`` from the target URL when the client omits one — the origin
derivation here is a deliberate implementation heuristic that matches the
MCP spec's canonical-URI convention and the origin-level audiences issued
by major IdPs (Salesforce, Azure AD, Okta).  It is not an RFC-mandated
behavior; configured or learned ``resource`` values always take precedence.

Examples:
    >>> derive_resource_origin("https://api.salesforce.com/platform/mcp/v1/x")
    'https://api.salesforce.com'
    >>> derive_resource_origin("urn:example:app") is None
    True
    >>> normalize_resource("https://api.example.com/mcp?x=1#frag")
    'https://api.example.com/mcp'
    >>> normalize_resource("https://api.example.com/mcp?x=1", preserve_query=True)
    'https://api.example.com/mcp?x=1'
    >>> normalize_resource("opaque-client-id")
    'opaque-client-id'
    >>> parse_oauth_resource_form("https://a.example.com, https://b.example.com")
    ['https://a.example.com', 'https://b.example.com']
    >>> parse_oauth_resource_form("https://api.example.com/path?x=1,y=2")
    'https://api.example.com/path?x=1,y=2'
"""

# Standard
import logging
import re
from typing import Any, List, Optional, Union
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


def derive_resource_origin(url: Optional[str]) -> Optional[str]:
    """Derive the origin (scheme + netloc) from a gateway URL for use as a fallback resource.

    Real-world OAuth providers (Salesforce, Azure AD, Okta) issue access tokens
    with origin-level audiences (``https://api.salesforce.com``) rather than the
    full URL of the protected MCP endpoint
    (``https://api.salesforce.com/platform/mcp/v1/...``).  Using the full
    gateway URL as the auto-derived resource therefore reliably mismatches the
    token's actual aud and produces validation failures.

    This helper is the single source of truth for that derivation.  It is used
    by three call sites that must agree on the auto-derived audience:

    * ``mcpgateway.routers.oauth_router`` — outbound ``resource`` param on the
      initial authorization request and the callback token exchange.
    * ``mcpgateway.services.token_storage_service`` — outbound ``resource``
      param on token refresh (must match the initial request so the IdP mints
      a token for the same audience).
    * ``mcpgateway.services.token_validation_service`` — inbound ``aud``
      comparison fallback when no admin-configured or per-user-learned
      resource exists.

    Args:
        url: Gateway URL to extract the origin from.

    Returns:
        ``scheme://netloc`` for hierarchical URLs, or ``None`` for URNs / empty
        / scheme-less inputs (caller should treat as "no auto-fallback
        possible" and rely on admin config or the per-user learned value).

    Examples:
        >>> derive_resource_origin("https://api.example.com/mcp/v1?x=1#f")
        'https://api.example.com'
        >>> derive_resource_origin("http://localhost:9000/sse")
        'http://localhost:9000'
        >>> derive_resource_origin("") is None
        True
        >>> derive_resource_origin(None) is None
        True
        >>> derive_resource_origin("urn:example:app") is None
        True
        >>> derive_resource_origin("/relative/path") is None
        True
    """
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_resource(url: Optional[str], *, preserve_query: bool = False) -> Optional[str]:
    """Normalize a resource value per RFC 8707, or pass through opaque identifiers.

    URL-shaped inputs are canonicalized (fragment stripped — RFC 8707 §2
    MUST NOT; query stripped unless ``preserve_query`` — §2 SHOULD NOT).
    Non-URL inputs (no scheme) are returned verbatim so that opaque audience
    identifiers learned from IdPs that do not honor RFC 8707 (e.g. ServiceNow
    / Authentik returning ``aud=client_id``) round-trip correctly.  RFC 8707
    §2 explicitly permits the AS to map ``resource`` to an abstract
    identifier; the resource server therefore must accept either form.

    Args:
        url: Resource URL or opaque audience identifier to normalize.
        preserve_query: If True, preserve query (for explicitly configured
            resources, where the query may be significant).  If False, strip
            it (RFC 8707 SHOULD NOT for auto-derived values).

    Returns:
        Normalized URL string, the original opaque value, or ``None`` if the
        input is empty.

    Examples:
        >>> normalize_resource("https://api.example.com/mcp#section")
        'https://api.example.com/mcp'
        >>> normalize_resource("https://api.example.com/mcp?x=1")
        'https://api.example.com/mcp'
        >>> normalize_resource("https://api.example.com/mcp?x=1", preserve_query=True)
        'https://api.example.com/mcp?x=1'
        >>> normalize_resource("test-servicenow-opaque-client-id")
        'test-servicenow-opaque-client-id'
        >>> normalize_resource("") is None
        True
    """
    if not url:
        return None
    parsed = urlparse(url)
    # If the value lacks a scheme it is not a URL; treat as an opaque
    # audience identifier and pass through verbatim so a learned
    # client_id-style audience survives refresh.
    if not parsed.scheme:
        return url
    # Remove fragment (MUST NOT); query: preserve for explicit, strip for auto-derived
    query = parsed.query if preserve_query else ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def parse_oauth_resource_form(raw: Any) -> Union[str, List[str], None]:
    """Parse the ``oauth_resource`` Admin UI form field into a single URI or list of URIs.

    Splits on whitespace, newlines, or commas, but only accepts the multi-value
    interpretation when every resulting piece is a well-formed absolute URI (has
    a scheme).  This preserves single resource URIs that legitimately contain
    commas in their path or query component (RFC 3986 pchar) rather than
    silently corrupting them into two bogus entries.

    Storage convention: single value is stored as ``str``, multiple as
    ``list[str]``, matching the shapes that IdPs use for the ``aud`` claim
    (RFC 7519 §4.1.3) and that :func:`mcpgateway.services.token_validation_service`
    accepts for ``oauth_config["resource"]``.

    Args:
        raw: Value pulled from a form field (typically ``form.get("oauth_resource")``).
            Non-string values, empty strings, and whitespace-only strings all
            yield ``None``.

    Returns:
        ``None`` for empty input, a ``str`` for a single resource, or a
        ``list[str]`` for multiple.

    Examples:
        >>> parse_oauth_resource_form(None) is None
        True
        >>> parse_oauth_resource_form("") is None
        True
        >>> parse_oauth_resource_form("   ") is None
        True
        >>> parse_oauth_resource_form("https://api.example.com")
        'https://api.example.com'
        >>> parse_oauth_resource_form("https://a.example.com, https://b.example.com")
        ['https://a.example.com', 'https://b.example.com']
        >>> parse_oauth_resource_form("https://a.example.com\\nhttps://b.example.com")
        ['https://a.example.com', 'https://b.example.com']
        >>> parse_oauth_resource_form("https://api.example.com/path?x=1,y=2")
        'https://api.example.com/path?x=1,y=2'
    """
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    pieces = [p.strip() for p in re.split(r"[,\s]+", stripped) if p.strip()]
    if not pieces:
        return None
    if len(pieces) == 1:
        return pieces[0]
    # Multi-value only accepted when every piece parses as an absolute URI.
    # Falling back to single-value protects URIs containing unencoded commas
    # (RFC 3986 pchar allows ',' in path and query components).
    if all(urlparse(p).scheme for p in pieces):
        return pieces
    return stripped
