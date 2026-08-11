"""Administrative orchestration for Praxis targets and assignments."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration, PraxisReplica, PraxisRollout, PraxisTarget, PraxisTargetServer, Server, utc_now
from mcpgateway.services._praxis_reconciliation import normalized_utc, REPLICA_STALE_AFTER
from mcpgateway.services.praxis_bundle_observability import PraxisConvergenceSnapshot, record_praxis_convergence
from mcpgateway.services.praxis_config_api_models import AssignmentView, ConvergenceStatus, ReplicaView, RolloutView, TargetCreate, TargetStatus, TargetUpdate, TargetView
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_epoch import PraxisTargetEpochService


class PraxisTargetConflictError(Exception):
    """The requested target mutation conflicts with authoritative state."""


class PraxisTargetNotFoundError(Exception):
    """The requested target-owned resource does not exist."""


class PraxisTargetService:
    """Apply target CRUD while preserving assignment and epoch invariants."""

    def __init__(self, db: Session, source: PraxisConfigSourceService) -> None:
        """Bind caller-owned persistence and exact source validation."""
        self._db = db
        self._source = source

    def create(self, payload: TargetCreate, actor: str) -> TargetView:
        """Create one enabled target."""
        target = PraxisTarget(name=payload.name, description=payload.description, created_by=actor)
        self._db.add(target)
        self._db.flush()
        return self.view(target)

    def list(self) -> tuple[TargetView, ...]:
        """List all targets without generation history."""
        return tuple(self.view(target) for target in self._db.scalars(select(PraxisTarget).order_by(PraxisTarget.name)).all())

    def get(self, target_id: str) -> PraxisTarget:
        """Load one target or raise a sanitized absence."""
        target = self._db.get(PraxisTarget, target_id)
        if target is None:
            raise PraxisTargetNotFoundError
        return target

    def update(self, target_id: str, payload: TargetUpdate, actor: str) -> TargetView:
        """Update metadata and bump policy/source identity."""
        target = self.get(target_id)
        if payload.name is not None:
            target.name = payload.name
        if "description" in payload.model_fields_set:
            target.description = payload.description
        target.updated_by = actor
        PraxisTargetEpochService(self._db).bump_for_policy((target_id,))
        self._db.flush()
        return self.view(target)

    def delete(self, target_id: str) -> None:
        """Delete only an already disabled target."""
        target = self.get(target_id)
        if target.enabled:
            raise PraxisTargetConflictError
        self._db.delete(target)

    def replace_assignments(self, target_id: str, server_ids: tuple[str, ...], actor: str, *, reassign: bool) -> AssignmentView:
        """Replace assignments and validate representability before commit."""
        self.get(target_id)
        if len(server_ids) != len(set(server_ids)):
            raise PraxisTargetConflictError
        servers = {server.id: server for server in self._db.scalars(select(Server).where(Server.id.in_(server_ids))).all()}
        if len(servers) != len(server_ids) or any(not server.enabled for server in servers.values()):
            raise PraxisTargetNotFoundError
        epoch_service = PraxisTargetEpochService(self._db)
        existing = {row.server_id: row for row in self._db.scalars(select(PraxisTargetServer).where(PraxisTargetServer.server_id.in_(server_ids))).all()}
        for server_id in server_ids:
            assignment = existing.get(server_id)
            if assignment is None:
                self._db.add(PraxisTargetServer(target_id=target_id, server_id=server_id, assigned_by=actor))
            elif assignment.target_id != target_id:
                owner = self.get(assignment.target_id)
                if owner.enabled and not reassign:
                    raise PraxisTargetConflictError
                epoch_service.reassign_server(server_id, target_id)
        stale = self._db.scalars(select(PraxisTargetServer).where(PraxisTargetServer.target_id == target_id, PraxisTargetServer.server_id.not_in(server_ids))).all()
        for assignment in stale:
            self._db.delete(assignment)
        epoch_service.bump_for_assignments((target_id,))
        self._db.flush()
        self._source.snapshot_in_session(self._db, target_id)
        return AssignmentView(target_id=target_id, server_ids=tuple(sorted(server_ids)))

    def create_replica(self, target_id: str, name: str) -> ReplicaView:
        """Register one server-issued replica identity."""
        target = self.get(target_id)
        if not target.enabled:
            raise PraxisTargetConflictError
        replica = PraxisReplica(target_id=target_id, name=name)
        self._db.add(replica)
        PraxisTargetEpochService(self._db).bump_for_policy((target_id,))
        self._db.flush()
        return self.replica_view(replica)

    def remove_replica(self, target_id: str, replica_id: str) -> None:
        """Revoke one target-bound replica while preserving rollout history."""
        query = select(PraxisReplica).where(PraxisReplica.target_id == target_id, PraxisReplica.id == replica_id)
        if self._db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        replica = self._db.scalar(query)
        if replica is None or not replica.enabled or replica.revoked_at is not None:
            raise PraxisTargetNotFoundError
        revoked_at = utc_now()
        replica.enabled = False
        replica.revoked_at = revoked_at
        replica.credential_epoch += 1
        for credential in replica.credentials:
            if credential.revoked_at is None:
                credential.revoked_at = revoked_at
        PraxisTargetEpochService(self._db).bump_for_policy((target_id,))
        self._db.flush()

    def status(self, target_id: str) -> TargetStatus:
        """Return current target, desired rollout, assignments, and replicas."""
        target = self.get(target_id)
        assignments = tuple(self._db.scalars(select(PraxisTargetServer.server_id).where(PraxisTargetServer.target_id == target_id).order_by(PraxisTargetServer.server_id)).all())
        replicas = tuple(self.replica_view(replica) for replica in self._db.scalars(select(PraxisReplica).where(PraxisReplica.target_id == target_id).order_by(PraxisReplica.id)).all())
        desired = None if target.desired_rollout_id is None else self._db.scalar(select(PraxisRollout).where(PraxisRollout.target_id == target_id, PraxisRollout.rollout_id == target.desired_rollout_id))
        convergence = self._convergence(target_id, desired)
        return TargetStatus(target=self.view(target), assignments=assignments, replicas=replicas, desired=self.rollout_view(desired) if desired is not None else None, convergence=convergence)

    def _convergence(self, target_id: str, desired: PraxisRollout | None) -> ConvergenceStatus:
        now = utc_now()
        cohort = () if desired is None else tuple(desired.cohort)
        state = "idle" if desired is None else desired.status
        stale_cutoff = now - REPLICA_STALE_AFTER
        stale_count = len(
            self._db.scalars(
                select(PraxisReplica).where(
                    PraxisReplica.target_id == target_id,
                    PraxisReplica.enabled.is_(True),
                    PraxisReplica.revoked_at.is_(None),
                    (PraxisReplica.last_heartbeat_at.is_(None) | (PraxisReplica.last_heartbeat_at < stale_cutoff)),
                )
            ).all()
        )
        generation = None if desired is None or desired.generation_id is None else self._db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.target_id == target_id, PraxisBundleGeneration.generation_id == desired.generation_id))
        age = 0.0 if generation is None else max((now - normalized_utc(generation.created_at)).total_seconds(), 0.0)
        active = sum(member.state == "active" for member in cohort)
        ratio = active / len(cohort) if cohort else 0.0
        schema, renderer = ("unknown", "unknown") if generation is None else (generation.bundle_schema, generation.renderer_version)
        snapshot = PraxisConvergenceSnapshot(state, stale_count, age, ratio, schema, renderer)
        record_praxis_convergence(snapshot)
        return ConvergenceStatus(
            state=state,
            cohort_size=len(cohort),
            prepared_replicas=sum(member.state in {"prepared", "canary_passed", "active"} for member in cohort),
            canary_passed_replicas=sum(member.state in {"canary_passed", "active"} for member in cohort),
            active_replicas=active,
            stale_replica_count=stale_count,
            generation_age_seconds=age,
            convergence_ratio=ratio,
            schema_version=schema,
            renderer_version=renderer,
        )

    @staticmethod
    def view(target: PraxisTarget) -> TargetView:
        """Map one target ORM row to its API contract."""
        return TargetView(id=target.id, name=target.name, description=target.description, enabled=target.enabled, source_epoch=target.source_epoch, policy_epoch=target.policy_epoch, fence=target.fence, desired_rollout_id=target.desired_rollout_id)

    @staticmethod
    def replica_view(replica: PraxisReplica) -> ReplicaView:
        """Map one replica ORM row to its API contract."""
        return ReplicaView(id=replica.id, target_id=replica.target_id, name=replica.name, enabled=replica.enabled, credential_epoch=replica.credential_epoch, last_heartbeat_at=replica.last_heartbeat_at)

    @staticmethod
    def rollout_view(rollout: PraxisRollout) -> RolloutView:
        """Map one desired rollout without exposing ciphertext."""
        return RolloutView(rollout_id=rollout.rollout_id, directive_id=rollout.directive_id, generation_id=rollout.generation_id, action=rollout.action, status=rollout.status, rollback_eligible=rollout.rollback_eligible, eligibility_reason=rollout.eligibility_reason, eligibility_deadline=rollout.eligibility_deadline)


__all__ = ("PraxisTargetConflictError", "PraxisTargetNotFoundError", "PraxisTargetService")
