"""Shared deterministic persistence helpers for Praxis reconciler tests."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration, PraxisReplicaReport, PraxisRollout, PraxisRolloutReplica


class FakeClock:
    """Mutable deterministic clock used to cross freshness boundaries."""

    __slots__ = ("current",)

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class TerminalHistorySpec:
    """Describe terminal rollout history for retention tests."""

    target_id: str
    replica_id: str
    now: datetime
    count: int = 15


def add_generation(db: Session, target_id: str, generation_id: str, created_at: datetime, nonce: bytes) -> None:
    """Persist one valid encrypted-generation fixture."""
    db.add(
        PraxisBundleGeneration(
            target_id=target_id,
            generation_id=generation_id,
            source_fingerprint=generation_id,
            payload_hash="2" * 64,
            content_hash="3" * 64,
            ciphertext_hash="4" * 64,
            ciphertext=b"ciphertext",
            envelope_version=1,
            key_id=f"key-{generation_id[0]}",
            nonce=nonce,
            source_ciphertext_hash="5" * 64,
            source_ciphertext=b"source-ciphertext",
            source_envelope_version=1,
            source_key_id=f"key-{generation_id[0]}",
            source_nonce=bytes((nonce[0] ^ 1,)) + nonce[1:],
            source_schema="praxis-source/v1",
            bundle_schema="praxis-bundle/v1",
            renderer_version="1",
            praxis_revision="ed46eb5",
            cpex_contract_version="1",
            mcp_protocol_version="2025-11-25",
            minimum_launcher_version="1",
            created_at=created_at,
        )
    )


def add_rollout(
    db: Session,
    target_id: str,
    rollout_id: str,
    generation_id: str | None,
    directive_seed: str,
    now: datetime,
    *,
    action: str = "activate",
    status: str = "rendered",
    replicas: tuple[str, ...] = (),
) -> PraxisRollout:
    """Persist one rollout and its immutable fixture cohort."""
    directive_id = directive_seed * 64
    rollout = PraxisRollout(
        target_id=target_id,
        rollout_id=rollout_id,
        generation_id=generation_id,
        directive_id=directive_id,
        policy_epoch=1,
        action=action,
        status=status,
        eligibility_deadline=now + timedelta(hours=1),
        created_at=now,
    )
    db.add(rollout)
    db.flush()
    db.add_all(
        PraxisRolloutReplica(target_id=target_id, rollout_id=rollout_id, replica_id=replica_id, directive_id=directive_id, position=position)
        for position, replica_id in enumerate(replicas)
    )
    db.flush()
    return rollout


def add_terminal_history(db: Session, spec: TerminalHistorySpec) -> tuple[str, ...]:
    """Persist alternating verified and failed-rollback terminal history."""
    generation_ids: list[str] = []
    for index in range(spec.count):
        generation_id = f"{100 + index:064x}"
        generation_ids.append(generation_id)
        add_generation(db, spec.target_id, generation_id, spec.now - timedelta(days=index + 1), (index + 10).to_bytes(12, "big"))
        is_verified = index % 2 == 0
        history = add_rollout(
            db,
            spec.target_id,
            f"history-{index:02d}",
            generation_id,
            chr(68 + index),
            spec.now - timedelta(days=index + 1),
            action="activate" if is_verified else "rollback",
            status="verified" if is_verified else "failed",
            replicas=(spec.replica_id,),
        )
        history.cohort[0].state = "active" if is_verified else "failed"
        history.cohort[0].last_report_sequence = 1
        db.add(
            PraxisReplicaReport(
                target_id=spec.target_id,
                rollout_id=history.rollout_id,
                replica_id=spec.replica_id,
                directive_id=history.directive_id,
                sequence=1,
                state="active" if is_verified else "failed",
                failure_category=None if is_verified else "timeout",
            )
        )
    return tuple(generation_ids)
