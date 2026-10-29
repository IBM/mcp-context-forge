# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_card_import.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for A2A Agent Card fetch, normalization and agent-field mapping (#4734).
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException, Request
import pytest

# First-Party
from mcpgateway.schemas import A2AAgentCreate, A2AFetchCardRequest
from mcpgateway.services import a2a_card_import
from mcpgateway.services.a2a_card_import import (
    build_candidate_urls,
    CardPathError,
    CardResponse,
    fetch_agent_card,
    is_agent_card,
    normalize_card,
    suggest_agent_fields,
)
from mcpgateway.services.a2a_service import A2AAgentService

V1_CARD = {
    "name": "weather",
    "description": "Forecasts",
    "version": "2.1.0",
    "supportedInterfaces": [
        {"url": "https://agent.example.com/grpc", "protocolBinding": "GRPC", "protocolVersion": "1.0"},
        {"url": "https://agent.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
    ],
    "capabilities": {"streaming": True, "pushNotifications": False, "extendedAgentCard": True, "extensions": [{"uri": "urn:x"}]},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text", "image/png"],
    "skills": [{"id": "forecast", "name": "Forecast", "description": "d", "tags": ["w"]}],
    "securitySchemes": {"bearerAuth": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
    "securityRequirements": [{"schemes": {"bearerAuth": {}}}],
}

LEGACY_CARD = {
    "name": "legacy",
    "description": "Old agent",
    "url": "https://old.example.com/a2a",
    "version": "1.2.0",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [],
    "supportsAuthenticatedExtendedCard": True,
    "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
    "security": [{"key": []}],
}


@pytest.fixture
def fetch(monkeypatch):
    """Replace the network read; returns the mock keyed by URL."""
    responses = {}
    seen = []

    async def _get_json(url, headers):
        seen.append((url, headers))
        outcome = responses.get(url, (404, None, None))
        return outcome if isinstance(outcome, CardResponse) else CardResponse(*outcome)

    monkeypatch.setattr(a2a_card_import, "_get_json", _get_json)
    return SimpleNamespace(responses=responses, seen=seen)


class TestCandidateUrls:
    """Which card URLs are tried."""

    def test_base_url_tries_both_well_known_paths_in_order(self):
        """The 1.0 path comes first and the pre-1.0 path second."""
        assert build_candidate_urls("https://a.example.com/", None) == ["https://a.example.com/.well-known/agent-card.json", "https://a.example.com/.well-known/agent.json"]

    def test_direct_json_url_is_used_as_given(self):
        """A URL naming a JSON document is not extended."""
        assert build_candidate_urls("https://a.example.com/cards/me.json", None) == ["https://a.example.com/cards/me.json"]

    def test_explicit_path_is_the_only_candidate(self):
        """An explicit path disables the well-known search."""
        assert build_candidate_urls("https://a.example.com", "custom/card.json") == ["https://a.example.com/custom/card.json"]

    @pytest.mark.parametrize("path", ["/../admin", "/a/./b", "/x?y=1", "/x#f", "/a b"])
    def test_unsafe_path_is_rejected(self, path):
        """Traversal, query, fragment and whitespace in the path are refused."""
        with pytest.raises(CardPathError):
            build_candidate_urls("https://a.example.com", path)

    def test_path_cannot_change_the_host(self):
        """A path that starts with slashes stays under the base host."""
        assert build_candidate_urls("https://a.example.com", "//evil.example.com/x") == ["https://a.example.com/evil.example.com/x"]


class TestNormalize:
    """Card detection and 0.3 to 1.0 conversion."""

    def test_v1_card_is_returned_unchanged(self):
        """A 1.0 card passes through as fetched."""
        card, version = normalize_card(V1_CARD)
        assert card is V1_CARD and version == "1.0"

    def test_legacy_card_becomes_1_0_shape(self):
        """A 0.3 card is rewritten with interfaces, extended-card capability and a oneof scheme."""
        card, version = normalize_card(LEGACY_CARD)
        assert version == "0.3"
        assert card["supportedInterfaces"] == [{"url": "https://old.example.com/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "0.3.0"}]
        assert card["capabilities"]["extendedAgentCard"] is True
        assert card["securitySchemes"] == {"key": {"apiKeySecurityScheme": {"location": "header", "name": "X-API-Key"}}}
        assert card["securityRequirements"] == [{"schemes": {"key": {}}}]
        assert "url" not in card

    def test_legacy_schemes_convert_to_oneof_shapes(self):
        """Each 0.3 scheme type maps to its 1.0 variant; unknown types and non-dicts are dropped."""
        raw = {
            "name": "legacy",
            "url": "https://old.example.com/a2a",
            "securitySchemes": {
                "web": {"type": "http", "scheme": "bearer"},
                "oauth": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "https://idp/t"}}},
                "oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://idp/.well-known"},
                "mtls": {"type": "mutualTLS"},
                "other": {"type": "unknown"},
                "bad": "not-a-dict",
            },
            "security": [{"web": ["read"], "oauth": []}],
        }
        card, _ = normalize_card(raw)
        assert card["securitySchemes"] == {
            "web": {"httpAuthSecurityScheme": {"scheme": "bearer"}},
            "oauth": {"oauth2SecurityScheme": {"flows": {"clientCredentials": {"tokenUrl": "https://idp/t"}}}},
            "oidc": {"openIdConnectSecurityScheme": {"openIdConnectUrl": "https://idp/.well-known"}},
            "mtls": {"mtlsSecurityScheme": {}},
        }
        assert card["securityRequirements"] == [{"schemes": {"web": {"list": ["read"]}, "oauth": {}}}]

    def test_legacy_card_keeps_additional_interfaces_and_extensions(self):
        """Extra transports and capability extensions survive the conversion."""
        raw = {
            "name": "legacy",
            "url": "https://old.example.com/a2a",
            "preferredTransport": "HTTP+JSON",
            "additionalInterfaces": [{"url": "https://old.example.com/grpc", "transport": "GRPC"}, {"url": ""}, "junk"],
            "capabilities": {"extensions": [{"uri": "urn:x"}]},
        }
        card, version = normalize_card(raw)
        assert version == "0.3"
        assert [i["protocolBinding"] for i in card["supportedInterfaces"]] == ["HTTP+JSON", "GRPC"]
        assert card["capabilities"]["extensions"] == [{"uri": "urn:x"}]
        assert "securitySchemes" not in card

    @pytest.mark.parametrize("doc", [[], "x", {"name": "a"}, {"url": "https://x"}, {"name": " ", "url": "https://x"}, {"name": "a", "supportedInterfaces": []}])
    def test_non_cards_are_rejected(self, doc):
        """Anything without a name and an endpoint is not a card."""
        assert is_agent_card(doc) is False


class TestSuggestedMapping:
    """Card to A2AAgentCreate field mapping."""

    def test_prefers_jsonrpc_interface_and_maps_fields(self):
        """The JSONRPC interface is chosen over an earlier GRPC one."""
        fields, warnings = suggest_agent_fields(V1_CARD)
        assert fields["endpoint_url"] == "https://agent.example.com/rpc"
        assert fields["protocol_version"] == "1.0"
        assert fields["version"] == "2.1.0"
        assert fields["capabilities"]["streaming"] is True
        assert fields["capabilities"]["skills"] == V1_CARD["skills"]
        assert fields["capabilities"]["defaultOutputModes"] == ["text", "image/png"]
        assert fields["auth_type"] == "bearer"
        assert warnings == []

    def test_grpc_only_card_warns(self):
        """A card with no JSONRPC interface still maps but warns."""
        card = {**V1_CARD, "supportedInterfaces": [V1_CARD["supportedInterfaces"][0]]}
        _, warnings = suggest_agent_fields(card)
        assert any("JSONRPC" in warning for warning in warnings)

    def test_multiple_requirements_pick_first_supported_and_report_rest(self):
        """One auth type is chosen; alternatives and unsupported schemes are reported."""
        card = {
            **V1_CARD,
            "securitySchemes": {
                "mtls": {"mtlsSecurityScheme": {}},
                "basicAuth": {"httpAuthSecurityScheme": {"scheme": "basic"}},
                "bearerAuth": {"httpAuthSecurityScheme": {"scheme": "bearer"}},
            },
            "securityRequirements": [{"schemes": {"mtls": {}}}, {"schemes": {"basicAuth": {}}}, {"schemes": {"bearerAuth": {}}}],
        }
        fields, warnings = suggest_agent_fields(card)
        assert fields["auth_type"] == "basic"
        assert any("mtls" in warning for warning in warnings)
        assert any("bearerAuth" in warning for warning in warnings)

    def test_oauth_client_credentials_maps_flow_without_secrets(self):
        """An OAuth2 client-credentials flow maps URLs and scopes, never credentials."""
        card = {
            **V1_CARD,
            "securitySchemes": {"oauth": {"oauth2SecurityScheme": {"flows": {"clientCredentials": {"tokenUrl": "https://idp/token", "scopes": {"read": "r"}}}}}},
            "securityRequirements": [{"schemes": {"oauth": {"list": ["read"]}}}],
        }
        fields, _ = suggest_agent_fields(card)
        assert fields["auth_type"] == "oauth"
        assert fields["oauth_config"] == {"grant_type": "client_credentials", "token_url": "https://idp/token", "scopes": ["read"]}
        assert "client_secret" not in fields["oauth_config"]

    def test_query_param_api_key_maps_param_name(self):
        """A query apiKey scheme maps to query_param auth with the declared name."""
        card = {**V1_CARD, "securitySchemes": {"k": {"apiKeySecurityScheme": {"location": "query", "name": "api_key"}}}, "securityRequirements": [{"schemes": {"k": {}}}]}
        fields, _ = suggest_agent_fields(card)
        assert fields["auth_type"] == "query_param" and fields["auth_query_param_key"] == "api_key"

    def test_suggestion_never_carries_deployment_settings(self):
        """Team, visibility, tags and credential values are not produced from a card."""
        fields, _ = suggest_agent_fields(V1_CARD)
        assert not {"team_id", "visibility", "tags", "owner_email", "auth_token", "auth_password", "auth_value"} & set(fields)

    def test_suggestion_validates_as_agent_create(self):
        """The suggested fields plus the credential the user supplies build a valid A2AAgentCreate."""
        fields, _ = suggest_agent_fields(V1_CARD)
        assert A2AAgentCreate(**fields, auth_token="user-supplied").endpoint_url == "https://agent.example.com/rpc"


class TestAuthFields:
    """Mapping of 1.0 security schemes to agent auth fields."""

    @pytest.mark.parametrize(
        ("scheme", "expected"),
        [
            ({"httpAuthSecurityScheme": {"scheme": "bearer"}}, {"auth_type": "bearer"}),
            ({"httpAuthSecurityScheme": {"scheme": "digest"}}, {}),
            ({"apiKeySecurityScheme": {"location": "header", "name": "X-Key"}}, {"auth_type": "authheaders", "auth_header_key": "X-Key"}),
            ({"apiKeySecurityScheme": {"location": "cookie", "name": "sid"}}, {}),
            ({"oauth2SecurityScheme": {"flows": {"implicit": {}}}}, {}),
            ({"mtlsSecurityScheme": {}}, {}),
        ],
    )
    def test_scheme_mapping(self, scheme, expected):
        """Supported schemes map to auth fields; the rest suggest nothing."""
        card = {
            "name": "a",
            "supportedInterfaces": [{"url": "https://a.example.com", "protocolBinding": "JSONRPC"}],
            "securitySchemes": {"s": scheme},
            "securityRequirements": [{"schemes": {"s": {}}}],
        }
        fields, _ = suggest_agent_fields(card)
        assert {k: v for k, v in fields.items() if k.startswith("auth_")} == expected

    def test_oauth_authorization_code_maps_flow(self):
        """An authorization-code flow keeps its URLs and requested scopes."""
        flow = {"authorizationUrl": "https://idp/a", "tokenUrl": "https://idp/t", "scopes": {"read": "r"}}
        card = {
            "name": "a",
            "supportedInterfaces": [{"url": "https://a.example.com", "protocolBinding": "JSONRPC"}],
            "securitySchemes": {"s": {"oauth2SecurityScheme": {"flows": {"authorizationCode": flow}}}},
            "securityRequirements": [{"schemes": {"s": {"list": ["write"]}}}],
        }
        fields, _ = suggest_agent_fields(card)
        assert fields["oauth_config"] == {"grant_type": "authorization_code", "authorization_url": "https://idp/a", "token_url": "https://idp/t", "scopes": ["write"]}


class TestRoundTrip:
    """A card ContextForge publishes imports back into the same agent (#4734 acceptance)."""

    @pytest.mark.parametrize(
        "auth",
        [
            {"auth_type": None},
            {"auth_type": "bearer"},
            {"auth_type": "basic"},
            {"auth_type": "query_param", "auth_query_params": {"api_key": "enc"}},  # pragma: allowlist secret
            {"auth_type": "oauth", "oauth_config": {"grant_type": "client_credentials", "token_url": "https://idp/token", "scopes": ["read"]}},
        ],
    )
    def test_generated_card_imports_back_to_matching_agent(self, auth):
        """Publish an agent's card, import it, and the mapped fields match the agent."""
        agent = SimpleNamespace(
            id="a1",
            name="roundtrip",
            description="desc",
            endpoint_url="https://agent.example.com/rpc",
            version=3,
            protocol_version="1.0",
            capabilities={
                "streaming": True,
                "pushNotifications": True,
                "skills": [{"id": "s", "name": "S", "description": "d", "tags": []}],
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"],
            },
            tenant=None,
            icon_url=None,
            auth_type=None,
            oauth_config=None,
            auth_query_params=None,
        )
        for key, value in auth.items():
            setattr(agent, key, value)

        published = A2AAgentService()._build_v1_agent_card(agent)  # pylint: disable=protected-access
        assert is_agent_card(published)
        fields, warnings = suggest_agent_fields(normalize_card(published)[0])

        assert warnings == []
        assert fields["name"] == agent.name
        assert fields["description"] == agent.description
        assert fields["endpoint_url"] == agent.endpoint_url
        assert fields["protocol_version"] == agent.protocol_version
        assert fields["version"] == str(agent.version)
        assert fields["capabilities"]["streaming"] is True
        assert fields["capabilities"]["pushNotifications"] is True
        assert fields["capabilities"]["skills"] == agent.capabilities["skills"]
        assert fields.get("auth_type") == (agent.auth_type or None)
        if agent.auth_type == "query_param":
            assert fields["auth_query_param_key"] == "api_key"
        if agent.auth_type == "oauth":
            assert fields["oauth_config"]["token_url"] == "https://idp/token"
            assert fields["oauth_config"]["scopes"] == ["read"]


@pytest.mark.asyncio
class TestFetch:
    """End-to-end fetch behaviour with the network read replaced."""

    async def test_fetches_v1_card(self, fetch):
        """A 1.0 card at the first well-known path is normalized and mapped."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (200, V1_CARD, None)
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.found and result.detected_version == "1.0"
        assert result.source_url == "https://agent.example.com/.well-known/agent-card.json"
        assert result.raw_card == V1_CARD
        assert result.suggested_agent["endpoint_url"] == "https://agent.example.com/rpc"

    async def test_falls_back_to_legacy_path_on_404(self, fetch):
        """A 404 on the 1.0 path retries the pre-1.0 path."""
        fetch.responses["https://old.example.com/.well-known/agent.json"] = (200, LEGACY_CARD, None)
        result = await fetch_agent_card("https://old.example.com", None, None)
        assert result.found and result.detected_version == "0.3"
        assert [url for url, _ in fetch.seen] == ["https://old.example.com/.well-known/agent-card.json", "https://old.example.com/.well-known/agent.json"]

    async def test_no_fallback_when_1_0_path_returns_non_card(self, fetch):
        """Only a 404 triggers fallback; a non-card 200 stops the search."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (200, {"hello": "world"}, None)
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.found is False and len(fetch.seen) == 1

    async def test_forwards_headers(self, fetch):
        """Caller headers reach the fetch for authenticated cards."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (200, V1_CARD, None)
        await fetch_agent_card("https://agent.example.com", None, {"Authorization": "Bearer t"})
        assert fetch.seen[0][1] == {"Authorization": "Bearer t"}

    @pytest.mark.parametrize(
        "result_tuple, outcome",
        [
            ((None, None, None), "unreachable"),
            ((500, None, None), "no_card"),
            ((404, None, None), "no_card"),
            ((200, None, None), "no_card"),
            ((200, {"x": 1}, None), "no_card"),
            ((401, None, "Bearer realm=x"), "auth_required"),
            ((403, None, None), "auth_required"),
        ],
    )
    async def test_failure_names_its_outcome(self, fetch, result_tuple, outcome):
        """Each failure maps to one outcome code the client can branch on."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = result_tuple
        fetch.responses["https://agent.example.com/.well-known/agent.json"] = result_tuple
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.found is False and result.outcome == outcome
        assert result.card is None and result.suggested_agent is None

    async def test_auth_required_carries_scheme_name(self, fetch):
        """The WWW-Authenticate scheme is returned without its parameters."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (401, None, 'Bearer realm="a2a", scope="x"')
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.outcome == "auth_required" and result.auth_scheme == "Bearer"
        assert "realm" not in result.model_dump_json()

    @pytest.mark.parametrize("challenge", [None, "", "b@d scheme", "x" * 40])
    async def test_auth_required_drops_malformed_scheme(self, fetch, challenge):
        """A missing or malformed challenge yields no scheme name."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (403, None, challenge)
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.outcome == "auth_required" and result.auth_scheme is None

    async def test_auth_required_stops_search(self, fetch):
        """A 401 on the 1.0 path does not try the legacy path."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (401, None, "Basic")
        await fetch_agent_card("https://agent.example.com", None, None)
        assert len(fetch.seen) == 1

    async def test_blocked_and_failed_hosts_are_indistinguishable(self, fetch):
        """A blocked address and a network failure return the same body, hiding reachability."""
        fetch.responses["https://agent.example.com/.well-known/agent-card.json"] = (None, None, None)
        first = await fetch_agent_card("https://agent.example.com", None, None)
        second = await fetch_agent_card("https://agent.example.com", None, None)
        assert first.model_dump() == second.model_dump() == a2a_card_import.unreachable().model_dump()

    async def test_unreachable_on_legacy_path_after_404(self, fetch):
        """A 404 on the 1.0 path followed by a failure on the legacy path reports unreachable."""
        fetch.responses["https://agent.example.com/.well-known/agent.json"] = (None, None, None)
        result = await fetch_agent_card("https://agent.example.com", None, None)
        assert result.outcome == "unreachable"

    async def test_unsafe_path_returns_no_card(self, fetch):
        """A rejected path never reaches the network."""
        result = await fetch_agent_card("https://agent.example.com", "/../x", None)
        assert result.found is False and fetch.seen == []


@pytest.mark.asyncio
class TestGetJson:
    """The guarded network read."""

    async def test_policy_rejection_returns_no_status(self, monkeypatch):
        """A URL refused by the outbound policy never opens a connection."""
        monkeypatch.setattr(a2a_card_import, "resolve_pinned_target", AsyncMock(side_effect=ValueError("blocked")))
        client = MagicMock()
        monkeypatch.setattr(a2a_card_import, "get_isolated_http_client", client)
        assert await a2a_card_import._get_json("http://169.254.169.254/x.json", None) == CardResponse(None)  # pylint: disable=protected-access
        client.assert_not_called()

    async def test_oversized_body_is_discarded(self, monkeypatch):
        """A body larger than the cap yields no document."""
        target = MagicMock()
        target.apply_headers.side_effect = lambda h: dict(h)
        target.pin.return_value = "https://1.2.3.4/card.json"
        target.validated_url = "https://a.example.com/card.json"
        target.extensions = {}
        monkeypatch.setattr(a2a_card_import, "resolve_pinned_target", AsyncMock(return_value=target))

        class _Resp:
            status_code = 200
            headers = {"etag": '"v1"', "cache-control": "max-age=60"}

            async def aiter_bytes(self):
                yield b"x" * (a2a_card_import.MAX_CARD_BYTES + 1)

        class _Stream:
            async def __aenter__(self):
                return _Resp()

            async def __aexit__(self, *exc):
                return False

        class _Client:
            def stream(self, *args, **kwargs):
                assert kwargs["extensions"] == {}
                return _Stream()

        class _Ctx:
            async def __aenter__(self):
                return _Client()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(a2a_card_import, "get_isolated_http_client", lambda **kwargs: _Ctx())
        assert await a2a_card_import._get_json("https://a.example.com/card.json", None) == CardResponse(200)  # pylint: disable=protected-access


def _stub_stream(monkeypatch, response=None, error=None):
    """Patch the outbound client so ``stream`` yields ``response`` or raises ``error``."""
    target = MagicMock()
    target.apply_headers.side_effect = lambda h: dict(h)
    target.pin.return_value = "https://1.2.3.4/card.json"
    target.validated_url = "https://a.example.com/card.json"
    target.extensions = {}
    monkeypatch.setattr(a2a_card_import, "resolve_pinned_target", AsyncMock(return_value=target))

    class _Stream:
        async def __aenter__(self):
            if error:
                raise error
            return response

        async def __aexit__(self, *exc):
            return False

    class _Client:
        def stream(self, *args, **kwargs):
            return _Stream()

    class _Ctx:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(a2a_card_import, "get_isolated_http_client", lambda **kwargs: _Ctx())


class _Resp:
    def __init__(self, status_code, body=b"", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    async def aiter_bytes(self):
        yield self._body


@pytest.mark.asyncio
class TestGetJsonOutcomes:
    """Remaining outcomes of the guarded network read."""

    async def test_valid_json_is_returned(self, monkeypatch):
        """A 200 response with a JSON body yields the parsed document."""
        _stub_stream(monkeypatch, _Resp(200, b'{"name": "a"}'))
        assert await a2a_card_import._get_json("https://a.example.com/card.json", {"X-K": "v"}) == CardResponse(200, {"name": "a"})  # pylint: disable=protected-access

    async def test_non_200_returns_status_only(self, monkeypatch):
        """A non-200 status is reported without reading the body."""
        _stub_stream(monkeypatch, _Resp(404))
        assert await a2a_card_import._get_json("https://a.example.com/card.json", None) == CardResponse(404)  # pylint: disable=protected-access

    async def test_challenge_header_is_returned_on_401(self, monkeypatch):
        """A 401 reports its WWW-Authenticate value."""
        _stub_stream(monkeypatch, _Resp(401, headers={"www-authenticate": "Bearer realm=x"}))
        assert await a2a_card_import._get_json("https://a.example.com/card.json", None) == CardResponse(401, challenge="Bearer realm=x")  # pylint: disable=protected-access

    async def test_invalid_json_yields_no_document(self, monkeypatch):
        """A 200 response that is not JSON yields no document."""
        _stub_stream(monkeypatch, _Resp(200, b"<html>"))
        assert await a2a_card_import._get_json("https://a.example.com/card.json", None) == CardResponse(200)  # pylint: disable=protected-access

    async def test_transport_error_returns_no_status(self, monkeypatch):
        """A transport failure is logged and reported as no status."""
        _stub_stream(monkeypatch, error=RuntimeError("boom"))
        assert await a2a_card_import._get_json("https://a.example.com/card.json", None) == CardResponse(None)  # pylint: disable=protected-access

    async def test_captures_etag_and_max_age(self, monkeypatch):
        """ETag and Cache-Control max-age travel with a successful card read."""
        _stub_stream(monkeypatch, _Resp(200, b'{"name": "a"}', headers={"etag": '"v1"', "cache-control": "public, max-age=60"}))
        result = await a2a_card_import._get_json("https://a.example.com/card.json", None)  # pylint: disable=protected-access
        assert result == CardResponse(200, {"name": "a"}, etag='"v1"', max_age=60)


class TestRequestSchema:
    """Request validation."""

    @pytest.mark.parametrize("headers", [{"Bad Name": "v"}, {"Host": "evil"}, {"X-A": "a\r\nX-B: b"}])
    def test_unsafe_headers_rejected(self, headers):
        """Malformed names, Host overrides and CRLF values fail validation."""
        with pytest.raises(ValueError):
            A2AFetchCardRequest(baseUrl="https://a.example.com", headers=headers)

    def test_accepts_camel_case_body(self):
        """The documented camelCase body parses."""
        req = A2AFetchCardRequest(**{"baseUrl": "https://a.example.com", "path": "/c.json", "headers": {"Authorization": "Bearer t"}})
        assert str(req.base_url).startswith("https://a.example.com") and req.path == "/c.json"


class TestRouteAuthorization:
    """Deny paths for POST /a2a/fetch-card."""

    @pytest.mark.asyncio
    async def test_handler_denies_without_a2a_create(self, monkeypatch):
        """A caller lacking a2a.create gets 403 and no outbound fetch happens."""
        # First-Party
        from mcpgateway import main

        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        fetch_mock = AsyncMock()
        monkeypatch.setattr(main, "fetch_agent_card", fetch_mock)
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await main.fetch_a2a_agent_card(A2AFetchCardRequest(baseUrl="https://a.example.com"), user={"email": "u@example.com", "db": db})

        assert exc_info.value.status_code == 403
        fetch_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handler_requires_authentication(self):
        """A call with no authenticated user is rejected before any fetch."""
        # First-Party
        from mcpgateway import main

        request = MagicMock(spec=Request)
        with pytest.raises(HTTPException) as exc_info:
            await main.fetch_a2a_agent_card(A2AFetchCardRequest(baseUrl="https://a.example.com"), user=None)
        assert exc_info.value.status_code in (401, 403)
        del request

    @pytest.mark.asyncio
    async def test_handler_returns_fetched_card_for_authorized_caller(self, monkeypatch):
        """An authorized caller gets the fetched card, and the request fields reach the fetch."""
        # First-Party
        from mcpgateway import main

        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        expected = a2a_card_import.not_found()
        fetch_mock = AsyncMock(return_value=expected)
        monkeypatch.setattr(main, "fetch_agent_card", fetch_mock)

        result = await main.fetch_a2a_agent_card(A2AFetchCardRequest(baseUrl="https://a.example.com", path="/card.json", headers={"X-K": "v"}), user={"email": "u@example.com", "db": MagicMock()})

        assert result is expected
        fetch_mock.assert_awaited_once_with("https://a.example.com/", "/card.json", {"X-K": "v"})
