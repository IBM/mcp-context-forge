# -*- coding: utf-8 -*-
# Standard
import os

# Third-Party
from playwright.sync_api import Playwright


def pytest_configure(config):
    """Configure Playwright for pytest runs."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))


def pytest_playwright_setup(playwright: Playwright):
    """Setup Playwright browsers and configuration for pytest runs."""
    return {
        "base_url": os.getenv("TEST_BASE_URL", "http://localhost:8000"),
        "screenshot": "only-on-failure",
        "video": "retain-on-failure",
        "trace": "retain-on-failure",
    }
