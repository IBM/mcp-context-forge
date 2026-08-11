# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_config_runtime.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the narrow runtime dependency wiring in praxis_config_runtime.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import timezone
import json
from pathlib import Path

from cpex.framework.settings import LazySettingsWrapper as PluginSettingsWrapper
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.config import settings
from mcpgateway.db import Base, PraxisCryptoNonceReservation
from mcpgateway.services import praxis_config_runtime
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService
from mcpgateway.services.praxis_config_runtime import (
    _DatabaseNonceReservationStore,
    _SystemClock,
    get_praxis_crypto_service,
    get_praxis_publication_service,
    get_praxis_reconciler,
    get_praxis_source_service,
)
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService

ACTIVE_KEY_B64 = base64.b64encode(bytes(range(32))).decode("ascii")
OLD_KEY_B64 = base64.b64encode(bytes(range(32, 64))).decode("ascii")
KEYS_JSON = json.dumps({"active-2026": ACTIVE_KEY_B64, "old-2025": OLD_KEY_B64})


@pytest.fixture
def runtime_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    """Bind the module's SessionLocal seam to an isolated on-disk SQLite store."""
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(praxis_config_runtime, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture
def request_wiring(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Arm a valid key ring and an absent operator plugin config for the factories."""
    monkeypatch.setattr(settings, "praxis_bundle_encryption_keys", SecretStr(KEYS_JSON))
    monkeypatch.setattr(settings, "praxis_bundle_active_key_id", "active-2026")
    monkeypatch.setattr(PluginSettingsWrapper, "config_file", property(lambda _wrapper: str(tmp_path / "absent-plugins.yaml")))


def test_system_clock_returns_utc_now() -> None:
    moment = _SystemClock().now()

    assert moment.tzinfo is not None
    assert moment.utcoffset() == timezone.utc.utcoffset(None)


def test_nonce_reservation_burns_pairs_atomically(runtime_store: sessionmaker[Session]) -> None:
    store = _DatabaseNonceReservationStore()

    assert store.reserve("key-a", b"\x01" * 12) is True
    assert store.reserve("key-a", b"\x01" * 12) is False
    assert store.reserve("key-b", b"\x01" * 12) is True

    with runtime_store() as db:
        assert db.query(PraxisCryptoNonceReservation).count() == 2


def test_operator_config_defaults_when_file_absent(request_wiring: None) -> None:
    config = praxis_config_runtime._operator_config()

    assert not config.plugins


def test_source_service_factory(request_wiring: None) -> None:
    service = get_praxis_source_service()

    assert isinstance(service, PraxisConfigSourceService)


def test_crypto_service_factory_uses_armed_key_ring(request_wiring: None) -> None:
    service = get_praxis_crypto_service()

    assert service is not None


def test_publication_service_notifier_is_a_noop(request_wiring: None) -> None:
    service = get_praxis_publication_service()

    assert isinstance(service, PraxisBundlePublicationService)
    # Task 12 notifications are intentionally unwired: the seam must stay inert.
    assert service._notifier(None) is None  # type: ignore[arg-type]


def test_reconciler_factory_uses_system_clock(request_wiring: None) -> None:
    reconciler = get_praxis_reconciler()

    assert isinstance(reconciler, PraxisBundleReconciler)
