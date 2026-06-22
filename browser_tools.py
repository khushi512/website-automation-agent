"""
browser_tools.py
All browser automation primitives the agent can call.
Each function wraps a Playwright action and returns a plain dict so the
results can be serialised directly into Claude tool-result messages.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (one browser session per agent run)
# ---------------------------------------------------------------------------
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None

# Ensure the screenshot directory exists
Path(config.SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

def open_browser(headless: bool = config.HEADLESS) -> dict:
    """
    Launch a Chromium browser and open a blank page.
    Must be called before any other browser tool.
    """
    global _playwright, _browser, _context, _page

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=headless,
        slow_mo=config.SLOW_MO_MS,
    )
    _context = _browser.new_context(viewport=config.VIEWPORT)
    _page = _context.new_page()
    logger.info("Browser opened (headless=%s)", headless)
    return {"status": "ok", "message": "Browser launched successfully."}


def close_browser() -> dict:
    """Shut down the browser and release resources."""
    global _playwright, _browser, _context, _page

    if _page:
        _page.close()
    if _context:
        _context.close()
    if _browser:
        _browser.close()
    if _playwright:
        _playwright.stop()

    _playwright = _browser = _context = _page = None
    logger.info("Browser closed")
    return {"status": "ok", "message": "Browser closed."}


def _require_page() -> Page:
    """Raise a clear error if the browser has not been opened yet."""
    if _page is None:
        raise RuntimeError("Browser is not open. Call open_browser() first.")
    return _page


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def navigate_to_url(url: str) -> dict:
    """Navigate the current tab to *url* and wait until the page has loaded."""
    page = _require_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    logger.info("Navigated to %s", url)
    return {"status": "ok", "url": page.url, "title": page.title()}


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def take_screenshot(filename: str = "screenshot.png") -> dict:
    """
    Capture the full page and save it to SCREENSHOT_DIR.
    Returns a base64-encoded PNG so it can be sent to Claude Vision.
    """
    page = _require_page()
    path = os.path.join(config.SCREENSHOT_DIR, filename)
    page.screenshot(path=path, full_page=False)

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    logger.info("Screenshot saved → %s", path)
    return {"status": "ok", "path": path, "base64": b64}


# ---------------------------------------------------------------------------
# Mouse actions
# ---------------------------------------------------------------------------

def click_on_screen(x: int, y: int) -> dict:
    """Left-click at viewport coordinates (x, y)."""
    page = _require_page()
    page.mouse.click(x, y)
    logger.info("Clicked at (%d, %d)", x, y)
    return {"status": "ok", "action": "click", "x": x, "y": y}


def double_click(x: int, y: int) -> dict:
    """Double-click at viewport coordinates (x, y)."""
    page = _require_page()
    page.mouse.dblclick(x, y)
    logger.info("Double-clicked at (%d, %d)", x, y)
    return {"status": "ok", "action": "double_click", "x": x, "y": y}


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------

def send_keys(text: str) -> dict:
    """Type *text* using the keyboard (no element targeting — types at focus)."""
    page = _require_page()
    page.keyboard.type(text, delay=40)
    logger.info("Typed: %r", text)
    return {"status": "ok", "action": "send_keys", "text": text}


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

def scroll(direction: str = "down", amount: int = 300) -> dict:
    """
    Scroll the page.
    direction: 'down' | 'up' | 'left' | 'right'
    amount: pixels to scroll
    """
    page = _require_page()
    delta_x = 0
    delta_y = 0
    if direction == "down":
        delta_y = amount
    elif direction == "up":
        delta_y = -amount
    elif direction == "right":
        delta_x = amount
    elif direction == "left":
        delta_x = -amount

    page.mouse.wheel(delta_x, delta_y)
    logger.info("Scrolled %s by %d px", direction, amount)
    return {"status": "ok", "action": "scroll", "direction": direction, "amount": amount}


# ---------------------------------------------------------------------------
# Higher-level helpers (used by the agent, not exposed as Claude tools)
# ---------------------------------------------------------------------------

def fill_by_selector(selector: str, text: str) -> dict:
    """
    Fill a form field identified by a CSS selector.
    Uses Playwright's .fill() which clears existing content first.
    """
    page = _require_page()
    page.wait_for_selector(selector, timeout=5_000)
    page.fill(selector, text)
    logger.info("Filled selector %r with %r", selector, text)
    return {"status": "ok", "selector": selector, "text": text}


def click_by_selector(selector: str) -> dict:
    """Click an element identified by a CSS selector."""
    page = _require_page()
    page.wait_for_selector(selector, timeout=5_000)
    page.click(selector)
    logger.info("Clicked selector %r", selector)
    return {"status": "ok", "selector": selector}


def get_page_html(max_chars: int = 8000) -> dict:
    """Return a truncated snapshot of the current page HTML for debugging."""
    page = _require_page()
    html = page.content()[:max_chars]
    return {"status": "ok", "html": html}


def wait_for_selector(selector: str, timeout_ms: int = 5000) -> dict:
    """Wait until an element matching *selector* appears in the DOM."""
    page = _require_page()
    try:
        page.wait_for_selector(selector, timeout=timeout_ms)
        logger.info("Selector %r found", selector)
        return {"status": "ok", "found": True, "selector": selector}
    except Exception as exc:
        logger.warning("Selector %r not found: %s", selector, exc)
        return {"status": "error", "found": False, "selector": selector, "error": str(exc)}
