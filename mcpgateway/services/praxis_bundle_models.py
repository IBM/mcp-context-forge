"""Strict models for the linked Praxis and CPEX configuration documents."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, JsonValue, field_validator, model_validator
from pydantic_core import PydanticCustomError

from mcpgateway.services._praxis_config_core import PraxisStrictModel, SafeIdentifier


FAIL_CLOSED_TAGS: Final = frozenset({"security", "auth", "authorization", "access-control", "rbac", "abac", "pdp", "mac"})
AUTHORIZATION_HOOKS: Final = frozenset({"http_auth_resolve_user", "http_auth_check_permission"})
SUPPORTED_PLUGIN_CAPABILITIES: Final = frozenset(
    {
        "read_subject",
        "read_roles",
        "read_teams",
        "read_claims",
        "read_permissions",
        "read_agent",
        "read_headers",
        "write_headers",
        "read_labels",
        "append_labels",
        "read_delegation",
        "append_delegation",
    }
)
SUPPORTED_PLUGIN_KINDS: Final = frozenset({"audit/logger", "delegator/oauth", "elicitation/ciba", "identity/jwt", "validator/pii-scan"})


class PraxisPolicyMapping(PraxisStrictModel):
    """One virtual-server policy loaded by the CPEX dispatcher."""

    server_id: SafeIdentifier
    config_path: str = Field(pattern=r"^cpex/[A-Za-z0-9][A-Za-z0-9._:-]*--[A-Za-z0-9][A-Za-z0-9._:-]*\.yaml$")


class PraxisFilter(PraxisStrictModel):
    """One linked custom filter and its exact flat configuration."""

    filter: Literal["mcp", "cpex"]
    max_body_bytes: int | None = Field(default=None, gt=0)
    policies: tuple[PraxisPolicyMapping, ...] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> PraxisFilter:
        """Keep classifier and dispatcher settings disjoint."""
        valid = (self.filter == "mcp" and self.max_body_bytes is not None and self.policies is None) or (
            self.filter == "cpex" and self.max_body_bytes is None and self.policies is not None and bool(self.policies)
        )
        if not valid:
            raise PydanticCustomError("incompatible_output_model", "invalid Praxis filter configuration")
        return self


class PraxisListener(PraxisStrictModel):
    """One HTTP listener bound to the immutable MCP chain."""

    name: Literal["mcp"] = "mcp"
    address: Literal["0.0.0.0:8080"] = "0.0.0.0:8080"
    filter_chains: tuple[Literal["mcp"], ...] = ("mcp",)


class PraxisFilterChain(PraxisStrictModel):
    """The unconditional classifier and security-dispatch pipeline."""

    name: Literal["mcp"] = "mcp"
    filters: tuple[PraxisFilter, PraxisFilter]

    @model_validator(mode="after")
    def validate_filters(self) -> PraxisFilterChain:
        """Require classifier first and security dispatcher second."""
        if tuple(item.filter for item in self.filters) != ("mcp", "cpex"):
            raise PydanticCustomError("empty_route", "filter chain must contain mcp then cpex")
        return self


class PraxisBundleDocument(PraxisStrictModel):
    """Root configuration accepted by Praxis revision ed46eb5."""

    listeners: tuple[PraxisListener, ...]
    filter_chains: tuple[PraxisFilterChain, ...]

    @model_validator(mode="after")
    def validate_document(self) -> PraxisBundleDocument:
        """Require exactly one listener and one referenced chain."""
        if len(self.listeners) != 1 or len(self.filter_chains) != 1:
            raise PydanticCustomError("incompatible_output_model", "Praxis root must contain one MCP listener and chain")
        return self


class PraxisCpexPluginCondition(PraxisStrictModel):
    """CPEX 0.2.2 legacy condition fields."""

    server_ids: tuple[str, ...] | None = None
    tenant_ids: tuple[str, ...] | None = None
    tools: tuple[str, ...] | None = None
    prompts: tuple[str, ...] | None = None
    resources: tuple[str, ...] | None = None
    agents: tuple[str, ...] | None = None
    user_patterns: tuple[str, ...] | None = None
    content_types: tuple[str, ...] | None = None


class PraxisCpexPlugin(PraxisStrictModel):
    """One plugin declaration loadable by the linked CPEX runtime."""

    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    hooks: tuple[str, ...] = ()
    mode: Literal["fire_and_forget", "concurrent", "sequential", "transform", "audit", "disabled"]
    priority: int = Field(ge=1, le=1000)
    on_error: Literal["fail", "ignore", "disable"]
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    conditions: tuple[PraxisCpexPluginCondition, ...] = ()
    config: dict[str, JsonValue] | None = None

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique supported capabilities in canonical order."""
        if value != tuple(sorted(set(value))) or not set(value).issubset(SUPPORTED_PLUGIN_CAPABILITIES):
            raise PydanticCustomError("unsupported_capability", "plugin capability is unsupported")
        return value

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> PraxisCpexPlugin:
        """Reject unavailable factories and fail-open security plugins."""
        if self.kind not in SUPPORTED_PLUGIN_KINDS:
            raise PydanticCustomError("incompatible_output_model", "plugin kind is unavailable")
        mandatory = not {tag.casefold() for tag in self.tags}.isdisjoint(FAIL_CLOSED_TAGS) or not set(self.hooks).isdisjoint(AUTHORIZATION_HOOKS)
        if mandatory and self.on_error != "fail":
            raise PydanticCustomError("non_fail_security_plugin", "mandatory security plugins must fail closed")
        return self


class PraxisCpexPluginSettings(PraxisStrictModel):
    """Required fail-closed CPEX routing settings."""

    routing_enabled: Literal[True] = True
    fail_on_plugin_error: Literal[True] = True


class PraxisCpexRoute(PraxisStrictModel):
    """One exact CPEX entity matcher and its plugin references."""

    tool: str | None = None
    resource: str | None = None
    prompt: str | None = None
    plugins: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_matcher(self) -> PraxisCpexRoute:
        """Require one nonempty entity matcher."""
        values = tuple(value for value in (self.tool, self.resource, self.prompt) if value is not None)
        if len(values) != 1 or not values[0]:
            raise PydanticCustomError("incompatible_output_model", "route must contain one matcher")
        if len(self.plugins) != len(set(self.plugins)):
            raise PydanticCustomError("duplicate_plugin", "route plugin references must be unique")
        return self


class PraxisCpexDocument(PraxisStrictModel):
    """CPEX 0.2.2 policy with exact entities and terminal wildcards."""

    plugin_settings: PraxisCpexPluginSettings
    plugins: tuple[PraxisCpexPlugin, ...] = ()
    routes: tuple[PraxisCpexRoute, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_document(self) -> PraxisCpexDocument:
        """Require canonical routes, references, and terminal wildcards."""
        names = tuple(plugin.name for plugin in self.plugins)
        if names != tuple(sorted(set(names))):
            raise PydanticCustomError("duplicate_plugin", "plugins must be unique and sorted")
        keys = tuple(_route_key(route) for route in self.routes)
        if len(keys) != len(set(keys)):
            raise PydanticCustomError("duplicate_route", "routes must be unique")
        if keys[-3:] != (("tool", "*"), ("resource", "*"), ("prompt", "*")):
            raise PydanticCustomError("missing_terminal_deny", "routes must end with terminal wildcards")
        if keys[:-3] != tuple(sorted(keys[:-3])):
            raise PydanticCustomError("incompatible_output_model", "exact routes must be sorted")
        if any(reference not in names for route in self.routes for reference in route.plugins):
            raise PydanticCustomError("dangling_reference", "route references an unknown plugin")
        return self


def _route_key(route: PraxisCpexRoute) -> tuple[str, str]:
    for kind in ("tool", "resource", "prompt"):
        value = getattr(route, kind)
        if value is not None:
            return kind, value
    raise AssertionError("validated route has no matcher")


__all__ = (
    "PraxisBundleDocument",
    "PraxisCpexDocument",
    "PraxisCpexPlugin",
    "PraxisCpexPluginCondition",
    "PraxisCpexPluginSettings",
    "PraxisCpexRoute",
    "PraxisFilter",
    "PraxisFilterChain",
    "PraxisListener",
    "PraxisPolicyMapping",
)
