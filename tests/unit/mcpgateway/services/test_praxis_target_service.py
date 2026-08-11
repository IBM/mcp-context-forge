# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_target_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for Praxis target CRUD conflict and absence paths.
"""

from __future__ import annotations

from collections.abc import Generator

from cpex.framework.models import Config
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from mcpgateway.db import Base, PraxisTarget, PraxisTargetServer, Server
from mcpgateway.services.praxis_config_api_models import TargetUpdate
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_service import PraxisTargetConflictError, PraxisTargetNotFoundError, PraxisTargetService


@pytest.fixture
def target_db() -> Generator[tuple[Session, PraxisTargetService], None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    db = factory()
    db.add_all(
        [
            PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test"),
            PraxisTarget(id="target-disabled", name="Target Disabled", created_by="admin@example.test", enabled=False),
            Server(id="server-public", name="Public", visibility="public"),
            Server(id="server-public-b", name="Public B", visibility="public"),
            Server(id="server-private", name="Private", visibility="private", owner_email="owner@example.test"),
            Server(id="server-disabled", name="Offline", visibility="public", enabled=False),
        ]
    )
    db.commit()
    yield db, PraxisTargetService(db, PraxisConfigSourceService(factory, Config()))
    db.close()
    engine.dispose()


def test_get_missing_target_raises_sanitized_absence(target_db: tuple[Session, PraxisTargetService]) -> None:
    _, service = target_db

    with pytest.raises(PraxisTargetNotFoundError):
        service.get("target-missing")


def test_update_applies_metadata_and_bumps_policy_epoch(target_db: tuple[Session, PraxisTargetService]) -> None:
    db, service = target_db
    before = service.get("target-a").policy_epoch

    view = service.update("target-a", TargetUpdate(name="Renamed", description="operator note"), "editor@example.test")

    target = service.get("target-a")
    assert view.name == "Renamed"
    assert view.description == "operator note"
    assert target.updated_by == "editor@example.test"
    assert target.policy_epoch == before + 1


def test_delete_requires_disabled_target(target_db: tuple[Session, PraxisTargetService]) -> None:
    db, service = target_db

    with pytest.raises(PraxisTargetConflictError):
        service.delete("target-a")

    service.delete("target-disabled")
    db.flush()

    assert db.get(PraxisTarget, "target-disabled") is None

    assert db.get(PraxisTarget, "target-disabled") is None
    with pytest.raises(PraxisTargetNotFoundError):
        service.get("target-disabled")


def test_replace_assignments_rejects_duplicate_server_ids(target_db: tuple[Session, PraxisTargetService]) -> None:
    _, service = target_db

    with pytest.raises(PraxisTargetConflictError):
        service.replace_assignments("target-a", ("server-public", "server-public"), "admin@example.test", reassign=False)


def test_replace_assignments_rejects_unknown_or_disabled_servers(target_db: tuple[Session, PraxisTargetService]) -> None:
    _, service = target_db

    with pytest.raises(PraxisTargetNotFoundError):
        service.replace_assignments("target-a", ("server-missing",), "admin@example.test", reassign=False)
    with pytest.raises(PraxisTargetNotFoundError):
        service.replace_assignments("target-a", ("server-disabled",), "admin@example.test", reassign=False)


def test_replace_assignments_removes_stale_rows(target_db: tuple[Session, PraxisTargetService]) -> None:
    db, service = target_db
    service.replace_assignments("target-a", ("server-public-b", "server-public"), "admin@example.test", reassign=False)

    view = service.replace_assignments("target-a", ("server-public",), "admin@example.test", reassign=False)

    assert view.server_ids == ("server-public",)
    remaining = db.scalars(select(PraxisTargetServer.server_id).where(PraxisTargetServer.target_id == "target-a")).all()
    assert remaining == ["server-public"]
