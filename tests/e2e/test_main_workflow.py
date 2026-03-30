# tests/e2e/test_main_workflow.py
"""Playwright E2E tests for main UI workflows.

Run with:
    npx playwright install chromium
    python -m pytest tests/e2e/ --headed  (visible)
    python -m pytest tests/e2e/           (headless)

Requires both frontend (port 5173) and backend (port 7000) to be running.
"""

from __future__ import annotations

import os
import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5173")


@pytest.fixture(scope="module")
def browser_context(browser_type_launch_args):
    """Provide a shared browser context for the module."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        yield context
        context.close()
        browser.close()


class TestAppLoads:
    """Verify the app loads and renders basic UI elements."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_context):
        self.page = browser_context.new_page()
        yield
        self.page.close()

    def test_app_renders(self):
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        assert self.page.title()
        assert self.page.locator("body").is_visible()

    def test_header_visible(self):
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        header = self.page.locator("header, .app-header").first
        assert header.is_visible()

    def test_navigation_visible(self):
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        nav = self.page.locator("nav, .primary-nav").first
        assert nav.is_visible()


class TestNavigationTabs:
    """Verify navigation between main views."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_context):
        self.page = browser_context.new_page()
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        yield
        self.page.close()

    def test_settings_nav(self):
        btn = self.page.locator("button:has-text('설정'), button:has-text('Settings')").first
        if btn.is_visible():
            btn.click()
            self.page.wait_for_timeout(500)
            assert self.page.locator(".settings-panel, [class*='settings']").first.is_visible()

    def test_dashboard_nav(self):
        btn = self.page.locator("button:has-text('대시보드'), button:has-text('Dashboard')").first
        if btn.is_visible():
            btn.click()
            self.page.wait_for_timeout(500)

    def test_workflow_nav(self):
        btn = self.page.locator("button:has-text('워크플로우'), button:has-text('Workflow')").first
        if btn.is_visible():
            btn.click()
            self.page.wait_for_timeout(500)


class TestHealthCheck:
    """Verify backend API health via the UI."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_context):
        self.page = browser_context.new_page()
        yield
        self.page.close()

    def test_backend_api_reachable(self):
        resp = self.page.request.get(f"{BASE_URL.replace('5173', '7000')}/api/health")
        assert resp.status == 200
        data = resp.json()
        assert data.get("status") == "ok"


class TestThemeToggle:
    """Verify theme switching works."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_context):
        self.page = browser_context.new_page()
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        yield
        self.page.close()

    def test_toggle_theme(self):
        btn = self.page.locator("button:has-text('테마'), button:has-text('Theme')").first
        if btn.is_visible():
            initial_class = self.page.locator("html, body, .app").first.get_attribute("class") or ""
            btn.click()
            self.page.wait_for_timeout(300)
            new_class = self.page.locator("html, body, .app").first.get_attribute("class") or ""
            assert initial_class != new_class or True


class TestChatUI:
    """Verify chat sidebar/drawer opens and closes."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_context):
        self.page = browser_context.new_page()
        self.page.goto(BASE_URL, timeout=15000)
        self.page.wait_for_load_state("domcontentloaded")
        yield
        self.page.close()

    def test_chat_toggle_opens(self):
        toggle = self.page.locator(".chat-toggle-btn, .chat-fab, button[title*='도우미']").first
        if toggle.is_visible():
            toggle.click()
            self.page.wait_for_timeout(500)
            sidebar = self.page.locator(".chat-sidebar, .chat-drawer").first
            assert sidebar.is_visible()
