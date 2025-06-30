# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""

# Standard
import asyncio
import os
from unittest.mock import AsyncMock, patch

# First-Party
from mcpgateway.config import Settings
from mcpgateway.db import Base

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from mcpgateway import translate


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_db_url():
    """Return the URL for the test database."""
    return "sqlite:///./test.db"


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    """Create a SQLAlchemy engine for testing."""
    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture
def test_db(test_engine):
    """Create a fresh database session for a test."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_settings():
    """Create test settings with in-memory database."""
    return Settings(
        database_url="sqlite:///:memory:",
        basic_auth_user="testuser",
        basic_auth_password="testpass",
        auth_required=False,
    )


@pytest.fixture
def app(test_settings):
    """Create a FastAPI test application."""
    with patch("mcpgateway.config.get_settings", return_value=test_settings):
        # First-Party
        from mcpgateway.main import app

        yield app


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client."""
    mock = AsyncMock()
    mock.aclose = AsyncMock()
    return mock


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    mock = AsyncMock()
    mock.accept = AsyncMock()
    mock.send_json = AsyncMock()
    mock.receive_json = AsyncMock()
    mock.close = AsyncMock()
    return mock

# @pytest.fixture(scope="session", autouse=True)
# def _patch_stdio_first():
#     """
#     Runs once, *before* the test session collects other modules,
#     so no rogue coroutine can be created.
#     """
#     import mcpgateway.translate as translate
#     translate._run_stdio_to_sse = AsyncMock(return_value=None)
#     translate._run_sse_to_stdio = AsyncMock(return_value=None)