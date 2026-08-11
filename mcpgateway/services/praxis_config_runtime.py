"""Narrow runtime dependency wiring for Praxis API orchestration."""

from datetime import datetime
from pathlib import Path

from cpex.framework import ConfigLoader
from cpex.framework.models import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mcpgateway.config import settings
from mcpgateway.db import PraxisCryptoNonceReservation, SessionLocal, utc_now
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService, PraxisPublication
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_legacy_telemetry import PraxisLegacyTelemetryService


class _SystemClock:
    def now(self) -> datetime:
        return utc_now()


class _DatabaseNonceReservationStore:
    """Atomically burn AES-GCM key/nonce pairs in the database."""

    def reserve(self, key_id: str, nonce: bytes) -> bool:
        with SessionLocal() as db:
            try:
                if db.get_bind().dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                db.add(PraxisCryptoNonceReservation(cryptographic_key_id=key_id, nonce=nonce))
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
        return True


def _operator_config() -> Config:
    path = Path(settings.plugins.config_file)
    return ConfigLoader.load_config(str(path)) if path.is_file() else Config()


def get_praxis_crypto_service() -> PraxisBundleCryptoService:
    """Build the control-plane key-ring service for this request."""
    return PraxisBundleCryptoService.from_json_keys(
        settings.praxis_bundle_encryption_keys.get_secret_value(),
        settings.praxis_bundle_active_key_id,
        _DatabaseNonceReservationStore(),
    )


def get_praxis_source_service() -> PraxisConfigSourceService:
    """Build the authoritative source snapshot service."""
    return PraxisConfigSourceService(SessionLocal, _operator_config())


def get_praxis_publication_service() -> PraxisBundlePublicationService:
    """Build the fenced publication service without Task 12 notifications."""
    def notify(_publication: PraxisPublication) -> None:
        return None

    return PraxisBundlePublicationService(SessionLocal, get_praxis_source_service(), get_praxis_crypto_service(), notify)


def get_praxis_reconciler() -> PraxisBundleReconciler:
    """Build the database-authoritative reconciler with the system clock."""
    return PraxisBundleReconciler(SessionLocal, _SystemClock())


def start_praxis_legacy_coverage() -> datetime:
    """Persist the authoritative legacy instrumentation start once."""
    with SessionLocal() as db:
        return PraxisLegacyTelemetryService(db, _SystemClock()).start_coverage()


__all__ = ("get_praxis_crypto_service", "get_praxis_publication_service", "get_praxis_reconciler", "get_praxis_source_service", "start_praxis_legacy_coverage")
