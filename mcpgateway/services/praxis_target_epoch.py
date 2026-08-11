"""Server-derived Praxis target epoch invalidation and stop fencing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import uuid

from sqlalchemy import and_, or_, select, union_all, update
from sqlalchemy.orm import Session

from mcpgateway.db import (
    PraxisReplica,
    PraxisRollout,
    PraxisRolloutReplica,
    PraxisTarget,
    PraxisTargetServer,
    Prompt,
    Resource,
    Server,
    Tool,
    server_prompt_association,
    server_resource_association,
    server_tool_association,
    utc_now,
)
from mcpgateway.services.praxis_config_directives import DirectiveAction, PraxisDirectiveIdentity, build_directive


@dataclass(frozen=True, slots=True)
class PraxisStopRollout:
    """Identity of an atomically issued target stop rollout."""

    target_id: str
    rollout_id: str
    directive_id: str
    cohort_replica_ids: tuple[str, ...]


class PraxisTargetEpochService:
    """Resolve affected targets from persisted ownership and bump their epochs."""

    def __init__(self, db: Session) -> None:
        """Bind the caller-owned mutation transaction."""
        self._db = db

    def bump_for_servers(self, server_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump targets assigned to any persisted server ID."""
        target_ids = self._ids(select(PraxisTargetServer.target_id).where(PraxisTargetServer.server_id.in_(server_ids)))
        return self._bump(target_ids)

    def bump_for_tools(self, tool_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump targets whose assigned servers contain a tool."""
        statement = (
            select(PraxisTargetServer.target_id)
            .join(server_tool_association, server_tool_association.c.server_id == PraxisTargetServer.server_id)
            .where(server_tool_association.c.tool_id.in_(tool_ids))
        )
        return self._bump(self._ids(statement))

    def bump_for_resources(self, resource_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump targets whose assigned servers contain a resource."""
        statement = (
            select(PraxisTargetServer.target_id)
            .join(server_resource_association, server_resource_association.c.server_id == PraxisTargetServer.server_id)
            .where(server_resource_association.c.resource_id.in_(resource_ids))
        )
        return self._bump(self._ids(statement))

    def bump_for_prompts(self, prompt_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump targets whose assigned servers contain a prompt."""
        statement = (
            select(PraxisTargetServer.target_id)
            .join(server_prompt_association, server_prompt_association.c.server_id == PraxisTargetServer.server_id)
            .where(server_prompt_association.c.prompt_id.in_(prompt_ids))
        )
        return self._bump(self._ids(statement))

    def bump_for_gateways(self, gateway_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump targets reached through gateway-owned catalog entities."""
        tool_targets = (
            select(PraxisTargetServer.target_id.label("target_id"))
            .join(server_tool_association, server_tool_association.c.server_id == PraxisTargetServer.server_id)
            .join(Tool, Tool.id == server_tool_association.c.tool_id)
            .where(Tool.gateway_id.in_(gateway_ids))
        )
        resource_targets = (
            select(PraxisTargetServer.target_id.label("target_id"))
            .join(server_resource_association, server_resource_association.c.server_id == PraxisTargetServer.server_id)
            .join(Resource, Resource.id == server_resource_association.c.resource_id)
            .where(Resource.gateway_id.in_(gateway_ids))
        )
        prompt_targets = (
            select(PraxisTargetServer.target_id.label("target_id"))
            .join(server_prompt_association, server_prompt_association.c.server_id == PraxisTargetServer.server_id)
            .join(Prompt, Prompt.id == server_prompt_association.c.prompt_id)
            .where(Prompt.gateway_id.in_(gateway_ids))
        )
        affected = union_all(tool_targets, resource_targets, prompt_targets).subquery()
        return self._bump(self._ids(select(affected.c.target_id)))

    def bump_for_bindings(self, bindings: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
        """Bump targets reached by exact team/tool or wildcard bindings."""
        predicates = tuple(
            and_(Server.team_id == team_id, Tool.id.is_not(None) if tool_name == "*" else Tool.original_name == tool_name)
            for team_id, tool_name in bindings
        )
        if not predicates:
            return ()
        statement = (
            select(PraxisTargetServer.target_id)
            .join(Server, Server.id == PraxisTargetServer.server_id)
            .join(server_tool_association, server_tool_association.c.server_id == Server.id)
            .join(Tool, Tool.id == server_tool_association.c.tool_id)
            .where(Server.visibility == "team", or_(*predicates))
        )
        return self._bump(self._ids(statement))

    def reassign_server(self, server_id: str, target_id: str) -> tuple[str, ...]:
        """Move one assignment and bump both targets' source and policy epochs."""
        query = select(PraxisTargetServer).where(PraxisTargetServer.server_id == server_id)
        if self._db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        assignment = self._db.scalar(query)
        if assignment is None:
            raise KeyError(server_id)
        previous_target_id = assignment.target_id
        assignment.target_id = target_id
        return self.bump_for_assignments((previous_target_id, target_id))

    def bump_for_assignments(self, target_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump source and policy epochs for assignment owners."""
        return self._bump(tuple(sorted(set(target_ids))), policy=True)

    def bump_for_policy(self, target_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Bump source and policy epochs for target policy mutations."""
        return self._bump(tuple(sorted(set(target_ids))), policy=True)

    def disable_target(self, target_id: str) -> PraxisStopRollout:
        """Disable, fence, and issue a fresh frozen-cohort stop rollout."""
        query = select(PraxisTarget).where(PraxisTarget.id == target_id)
        if self._db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        target = self._db.scalar(query)
        if target is None:
            raise KeyError(target_id)
        target.enabled = False
        target.source_epoch += 1
        target.policy_epoch += 1
        target.fence += 1
        rollout_id = uuid.uuid4().hex
        deadline = utc_now() + timedelta(hours=1)
        directive = build_directive(
            PraxisDirectiveIdentity(
                target_id=target.id,
                rollout_id=rollout_id,
                policy_epoch=target.policy_epoch,
                action=DirectiveAction.STOP,
                generation_id=None,
                eligibility_deadline=deadline,
            )
        )
        replica_ids = tuple(
            self._db.scalars(
                select(PraxisReplica.id)
                .where(PraxisReplica.target_id == target.id, PraxisReplica.enabled.is_(True), PraxisReplica.revoked_at.is_(None))
                .order_by(PraxisReplica.id)
            ).all()
        )
        self._db.add(
            PraxisRollout(
                target_id=target.id,
                rollout_id=rollout_id,
                generation_id=None,
                directive_id=directive.directive_id,
                policy_epoch=target.policy_epoch,
                source_epoch=target.source_epoch,
                fence=target.fence,
                action=directive.action.value,
                eligibility_deadline=deadline,
            )
        )
        self._db.add_all(
            PraxisRolloutReplica(target_id=target.id, rollout_id=rollout_id, replica_id=replica_id, directive_id=directive.directive_id, position=position)
            for position, replica_id in enumerate(replica_ids)
        )
        self._db.flush()
        target.desired_rollout_id = rollout_id
        self._db.flush()
        return PraxisStopRollout(target.id, rollout_id, directive.directive_id, replica_ids)

    def _ids(self, statement) -> tuple[str, ...]:
        return tuple(sorted(set(self._db.scalars(statement).all())))

    def _bump(self, target_ids: tuple[str, ...], *, policy: bool = False) -> tuple[str, ...]:
        if not target_ids:
            return ()
        values = {"source_epoch": PraxisTarget.source_epoch + 1}
        if policy:
            values["policy_epoch"] = PraxisTarget.policy_epoch + 1
        self._db.execute(update(PraxisTarget).where(PraxisTarget.id.in_(target_ids)).values(**values))
        return target_ids


__all__ = ("PraxisStopRollout", "PraxisTargetEpochService")
