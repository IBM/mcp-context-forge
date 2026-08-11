"""Internal typed state used while assembling Praxis source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcpgateway.db import Gateway, Prompt, Resource, Server, Tool
from mcpgateway.services.praxis_config_models import PraxisSourceErrorCode

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ServerGraph:
    """Catalog graph for one assigned virtual server."""

    server: Server
    gateways: dict[str, Gateway]
    tools: list[Tool]
    resources: list[Resource]
    prompts: list[Prompt]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Persisted inputs needed to compile one tool binding."""

    session: Session
    tool: Tool
    scope: str


class SourceRefusal(Exception):
    """Internal fixed-code refusal that retains no source values."""

    __slots__ = ("code",)

    def __init__(self, code: PraxisSourceErrorCode) -> None:
        self.code = code


__all__ = ("ServerGraph", "SourceRefusal", "ToolContext")
