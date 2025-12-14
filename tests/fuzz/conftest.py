# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Fuzzing test configuration.
"""

# Standard
import os
import tempfile

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
from hypothesis import HealthCheck, settings, Verbosity
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Mark all tests in this directory as fuzz tests
pytestmark = pytest.mark.fuzz


@pytest.fixture(autouse=True)
def mock_logging_services(monkeypatch):
    """Mock logging services to prevent database access during fuzz tests.

    This fixture patches SessionLocal in the db module and all modules that
    import it, ensuring they use a test database with all tables created.
    """
    # Create a temp database for the fuzz tests
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # First-Party
    import mcpgateway.db as db_mod
    from mcpgateway.db import Base
    import mcpgateway.main as main_mod
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod

    # Patch the core db module
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSessionLocal)

    # Patch main module's SessionLocal (it imports SessionLocal from db)
    monkeypatch.setattr(main_mod, "SessionLocal", TestSessionLocal)

    # Patch auth_middleware's SessionLocal
    monkeypatch.setattr(auth_middleware_mod, "SessionLocal", TestSessionLocal)

    # Patch security_logger and structured_logger SessionLocal
    monkeypatch.setattr(sec_logger_mod, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(struct_logger_mod, "SessionLocal", TestSessionLocal)

    # Create all tables
    Base.metadata.create_all(bind=engine)

    yield

    # Cleanup
    engine.dispose()
    os.close(fd)
    os.unlink(path)

# Configure Hypothesis profiles for different environments
settings.register_profile("dev", max_examples=100, verbosity=Verbosity.normal, suppress_health_check=[HealthCheck.too_slow])

settings.register_profile("ci", max_examples=50, verbosity=Verbosity.quiet, suppress_health_check=[HealthCheck.too_slow])

settings.register_profile("thorough", max_examples=1000, verbosity=Verbosity.verbose, suppress_health_check=[HealthCheck.too_slow])


@pytest.fixture(scope="session")
def fuzz_settings():
    """Configure fuzzing settings based on environment."""
    # Standard
    import os

    profile = os.getenv("HYPOTHESIS_PROFILE", "dev")
    settings.load_profile(profile)
    return profile
