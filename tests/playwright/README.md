# 🎭 Playwright UI Tests for ContextForge

This directory contains end-to-end UI tests for ContextForge admin interface and web UI components using [Playwright](https://playwright.dev/).

## 📁 Directory Structure

```
tests/playwright/
├── README.md               # This file
├── conftest.py            # Pytest fixtures and configuration
├── test_admin_ui.py       # Admin panel UI tests
├── test_api_endpoints.py  # API integration tests via UI
├── test_api_integration.py # API protocol tests
├── test_auth.py           # Authentication tests
├── test_htmx_interactions.py # HTMX interaction tests
├── test_realtime_features.py # Real-time feature tests
├── entities/              # CRUD tests for admin entities
│   ├── .gitkeep
│   └── test_tools.py      # Tools CRUD operations
├── api/                   # API protocol and REST endpoint tests
│   └── .gitkeep
├── fixtures/              # Shared fixtures, test data factories
│   └── .gitkeep
├── pages/                 # Page Object Model
│   ├── base_page.py       # Base page class
│   └── admin_page.py      # Admin panel page objects
├── screenshots/           # Visual regression baseline images
└── reports/              # Test reports (auto-created)
```

Playwright artifacts (screenshots, videos, traces) are written to `test-results/` at the repo root and are gitignored.

## 🚀 Quick Start

### Installation

Playwright (and `pytest-playwright`, `pytest-html`, `python-owasp-zap-v2.4`)
lives in the `dev` dependency group, so it's installed automatically by
the standard project bootstrap — no extras needed:

```bash
# One-shot project setup (creates .venv, installs runtime + dev deps)
make install-dev

# Install Playwright browsers (only needed once)
make playwright-install      # Installs Chromium only
# OR
make playwright-install-all  # Installs all browsers (Chromium, Firefox, WebKit)
```

### Running Tests

```bash
# Start the testing stack first (docker-compose.yml + nginx on :8080)
make testing-up

# In another terminal, run the tests:
make test-ui              # Run with visible browser
make test-ui-headless     # Run in headless mode (CI/CD)
make test-ui-debug        # Run with Playwright Inspector
make test-ui-smoke        # Run only smoke tests (fast)
make test-ui-screenshots  # Always-on screenshots (headless)
make test-ui-record       # Videos + screenshots (headless)
make test-ui-report       # Generate HTML report
```

## 🧪 Test Categories

Tests are organized by functionality and tagged with pytest markers:

- **`@pytest.mark.smoke`** - Quick validation tests that run in < 30 seconds
- **`@pytest.mark.ui`** - UI interaction tests
- **`@pytest.mark.api`** - API endpoint tests through the UI
- **`@pytest.mark.e2e`** - Full end-to-end workflows
- **`@pytest.mark.slow`** - Tests that take > 1 minute

### Running Specific Test Categories

```bash
# Run only smoke tests
pytest tests/playwright -m smoke

# Run all except slow tests
pytest tests/playwright -m "not slow"

# Run UI and API tests
pytest tests/playwright -m "ui or api"
```

## 📝 Writing Tests

### Basic Test Structure

```python
import pytest
from playwright.sync_api import Page, expect

class TestFeatureName:
    """Test suite for specific feature."""

    @pytest.mark.smoke
    def test_basic_functionality(self, page: Page, base_url: str):
        """Test description."""
        # Navigate
        page.goto(f"{base_url}/admin")

        # Assert page loaded
        expect(page).to_have_title("ContextForge Admin")

        # Interact with elements
        page.click('button:has-text("Add Server")')

        # Verify results
        modal = page.locator('[role="dialog"]')
        expect(modal).to_be_visible()
```

### Using Page Objects

```python
from tests.playwright.pages.admin_page import AdminPage

def test_with_page_object(page: Page, base_url: str):
    """Test using page object pattern."""
    admin = AdminPage(page, base_url)
    admin.navigate()
    admin.add_server("Test Server", "http://localhost:9000")
    assert admin.server_exists("Test Server")
```

## 🔧 Configuration

### Environment Variables

```bash
# Base URL for testing (default: http://localhost:8080 via docker-compose.yml nginx)
export TEST_BASE_URL=http://localhost:8080
# Override for a different endpoint
# TEST_BASE_URL=http://localhost:8000 make test-ui

# Authentication token
export MCP_AUTH=your-test-token

# Admin login credentials for UI tests
export PLATFORM_ADMIN_EMAIL=admin@example.com
export PLATFORM_ADMIN_PASSWORD=changeme

# Optional: password used when the UI forces a password change
# (override if your password policy requires extra complexity)
export PLATFORM_ADMIN_NEW_PASSWORD=changeme123

# Playwright options
export PWDEBUG=1           # Enable Playwright Inspector
export HEADED=1            # Force headed mode
export SLOWMO=100          # Add 100ms delay between actions
```

The Playwright auth fixtures will automatically handle the "change password required" flow when triggered.

### pyproject.toml Configuration

The project's `pyproject.toml` includes Playwright configuration in `[tool.pytest.ini_options]`:

- Default browser: `chromium`
- Screenshots: `only-on-failure`
- Videos: `retain-on-failure`
- Traces: `retain-on-failure`

## 🐛 Debugging Tests

### 1. Playwright Inspector

```bash
make test-ui-debug
# OR
PWDEBUG=1 pytest tests/playwright/test_admin_ui.py -s
```

This opens the Playwright Inspector with:
- Step through each action
- See selector playground
- Record new tests

### 2. Headed Mode

```bash
make test-ui
# OR
pytest tests/playwright --headed
```

### 3. Slow Motion

```bash
pytest tests/playwright --headed --slowmo 1000  # 1 second delay
```

### 4. Screenshots and Videos

Failed tests automatically capture:
- Screenshots, videos, traces in `test-results/` (pytest-playwright artifacts)
- Visual regression baselines in `tests/playwright/screenshots/`

Always-on artifacts:
- `make test-ui-screenshots` captures screenshots for every test (stored in `test-results/`)
- `make test-ui-record` captures videos + screenshots for every test (stored in `test-results/`)

Recording quality controls:
- `PLAYWRIGHT_VIDEO_SIZE=1920x1080` (default) sets the recording resolution
- `PLAYWRIGHT_SLOWMO=750` (default) slows actions for clearer videos
- `PLAYWRIGHT_VIEWPORT_SIZE=1920x1080` (default) sets the browser viewport

### 5. VS Code Debugging

Add to `.vscode/launch.json`:

```json
{
    "name": "Debug Playwright Test",
    "type": "python",
    "request": "launch",
    "module": "pytest",
    "args": [
        "tests/playwright/test_admin_ui.py::TestAdminUI::test_admin_panel_loads",
        "-v",
        "--headed"
    ],
    "env": {
        "PWDEBUG": "console"
    }
}
```

## 📊 Test Reports

### HTML Report

```bash
make test-ui-report
open tests/playwright/reports/report.html
```

### Coverage Report

```bash
make test-ui-coverage
open tests/playwright/reports/coverage/index.html
```

### CI/CD Integration

Tests run automatically on GitHub Actions for:
- Pull requests
- Pushes to main/develop branches
- Changes to UI code or test files

## ⚡ Performance Tips

1. **Use `test-ui-parallel` for faster execution**:
   ```bash
   make test-ui-parallel  # Runs tests in parallel
   ```

2. **Run only affected tests**:
   ```bash
   pytest tests/playwright -k "server"  # Only server-related tests
   ```

3. **Skip slow tests during development**:
   ```bash
   pytest tests/playwright -m "not slow"
   ```

4. **Reuse browser context** for related tests (see conftest.py)

## 🏗️ Best Practices

1. **Use Page Object Model** - Encapsulate page interactions in page classes
2. **Explicit Waits** - Use `page.wait_for_selector()` instead of `time.sleep()`
3. **Meaningful Assertions** - Use Playwright's `expect()` API for auto-waiting
4. **Test Isolation** - Each test should be independent
5. **Descriptive Names** - Test names should explain what they verify
6. **Error Messages** - Include context in assertion messages
7. **Cleanup** - Tests should clean up created resources

## 📂 Adding Tests

- Place CRUD tests in `entities/` directory
- Place protocol/REST/error tests in `api/` directory
- Add shared fixtures/page objects in `fixtures/` directory
- Visual regression baselines go in `screenshots/` directory

## 🔍 Common Issues

### Server Not Running

```bash
# Error: Connection refused to localhost:8080
# Solution: Start the testing stack first
make testing-up
```

### Browser Not Installed

```bash
# Error: Executable doesn't exist at...
# Solution: Install browsers
make playwright-install
```

### Flaky Tests

```python
# Add retries for flaky tests
@pytest.mark.flaky(reruns=3, reruns_delay=1)
def test_sometimes_flaky(page):
    # test code
```

### Timeout Issues

```python
# Increase timeout for slow operations
page.set_default_timeout(30000)  # 30 seconds
# OR
page.click("button", timeout=10000)  # 10 seconds for this action
```

## 📚 Resources

- [Playwright Python Documentation](https://playwright.dev/python/)
- [Playwright Best Practices](https://playwright.dev/docs/best-practices)
- [pytest-playwright Plugin](https://github.com/microsoft/playwright-pytest)
- [ContextForge Documentation](https://ibm.github.io/mcp-context-forge/)

## 🤝 Contributing

1. Follow the existing test patterns
2. Add appropriate test markers
3. Update page objects for new UI elements
4. Include docstrings explaining test purpose
5. Run `make test-ui` locally before submitting PR
6. Ensure all smoke tests pass

See the main project README for more details.
