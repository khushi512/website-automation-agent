"""
browser_tools.py
All browser automation primitives the agent can call.
Production-grade with retry logic, structured logging, and comprehensive error handling.

THREADING NOTE (important — read before editing):
Playwright's *sync* API is thread-affine: once `sync_playwright().start()`
runs on a given OS thread, every subsequent Playwright call must happen on
that exact same thread, or its internal greenlet dispatcher raises
`greenlet.error: Cannot switch to a different thread`.

The OpenAI Agents SDK runs our sync `@function_tool` functions through
asyncio's default thread pool, which does NOT guarantee the same worker
thread is reused for every call — so calling Playwright directly from the
public functions crashed intermittently once more than one tool call
happened per task.

The fix: every public function below is a thin wrapper that submits the
*actual* Playwright work to one dedicated, single-worker background thread
(`_EXECUTOR`) that we create once and reuse for the life of the process.
No matter which thread the SDK calls our wrapper from, the real Playwright
call always lands on the same pinned thread.
"""

import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import config

# ---------------------------------------------------------------------------
# Structured Logging Setup
# ---------------------------------------------------------------------------
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger("browser_tools")

# ---------------------------------------------------------------------------
# Module-level singletons (one browser session per agent run)
# ---------------------------------------------------------------------------
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None

# One dedicated worker thread. Every Playwright call in this file, for the
# entire process lifetime, executes on this same thread — see the module
# docstring above for why this is required.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright-worker")


def _run(fn, *args, **kwargs):
    """Submit *fn* to the dedicated Playwright thread and block for the result."""
    return _EXECUTOR.submit(fn, *args, **kwargs).result()


# Ensure the screenshot directory exists
Path(config.SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class BrowserNotOpenError(RuntimeError):
    """Raised when browser is not open but a tool requires it."""
    pass


class ElementNotFoundError(RuntimeError):
    """Raised when an element ref is not found on the page."""
    pass


class NavigationTimeoutError(RuntimeError):
    """Raised when page navigation times out."""
    pass


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------
def _open_browser_impl(headless: bool) -> dict:
    global _playwright, _browser, _context, _page

    if _page is not None:
        # Check if browser is still connected
        if _browser and not _browser.is_connected():
            logger.warning("Browser was disconnected, reinitializing")
            _playwright = _browser = _context = _page = None
        else:
            logger.info("open_browser called but session already open — reusing")
            return {"status": "ok", "message": "Browser already open; reusing existing session."}

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=headless,
        slow_mo=config.SLOW_MO_MS,
    )
    _context = _browser.new_context(viewport=config.VIEWPORT)
    _page = _context.new_page()
    logger.info("Browser opened", headless=headless)
    return {"status": "ok", "message": "Browser launched successfully."}


def open_browser(headless: bool = config.HEADLESS) -> dict:
    """
    Launch a Chromium browser and open a blank page.
    Must be called before any other browser tool.
    Safe to call multiple times: if a browser session is already open
    (e.g. a prior task in the same interactive session left it running),
    this is a no-op that returns the existing session instead of trying to
    launch a second Chromium instance.
    """
    return _run(_open_browser_impl, headless)


def _close_browser_impl() -> dict:
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


def close_browser() -> dict:
    """Shut down the browser and release resources."""
    return _run(_close_browser_impl)


def _require_page() -> Page:
    """Raise a clear error if the browser has not been opened yet.
    Only ever called from inside the dedicated Playwright thread.
    """
    if _page is None:
        raise BrowserNotOpenError("Browser is not open. Call open_browser() first.")
    if _browser and not _browser.is_connected():
        raise BrowserNotOpenError("Browser was closed. Call open_browser() to restart.")
    return _page


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((NavigationTimeoutError, Exception)),
    reraise=True
)
def _navigate_to_url_impl(url: str) -> dict:
    page = _require_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        logger.info("Navigated to URL", url=page.url, title=page.title())
        return {"status": "ok", "url": page.url, "title": page.title()}
    except Exception as exc:
        logger.error("Navigation failed", url=url, error=str(exc))
        raise NavigationTimeoutError(f"Failed to navigate to {url}: {exc}") from exc


def navigate_to_url(url: str) -> dict:
    """Navigate the current tab to *url* and wait until the page has loaded."""
    return _run(_navigate_to_url_impl, url)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------
def _take_screenshot_impl(filename: str) -> dict:
    page = _require_page()
    path = os.path.join(config.SCREENSHOT_DIR, filename)
    page.screenshot(path=path, full_page=False, type="jpeg", quality=50)

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    logger.info("Screenshot saved", path=path)
    return {"status": "ok", "path": path, "base64": b64}


def take_screenshot(filename: str = "screenshot.jpg") -> dict:
    """
    Capture the full page and save it to SCREENSHOT_DIR.
    Returns a base64-encoded JPEG so it can be sent to the model as an image.
    """
    return _run(_take_screenshot_impl, filename)


# ---------------------------------------------------------------------------
# Mouse actions
# ---------------------------------------------------------------------------
def _click_on_screen_impl(x: int, y: int) -> dict:
    page = _require_page()
    page.mouse.click(x, y)
    logger.info("Clicked on screen", x=x, y=y)
    return {"status": "ok", "action": "click", "x": x, "y": y}


def click_on_screen(x: int, y: int) -> dict:
    """Left-click at viewport coordinates (x, y)."""
    return _run(_click_on_screen_impl, x, y)


def _double_click_impl(x: int, y: int) -> dict:
    page = _require_page()
    page.mouse.dblclick(x, y)
    logger.info("Double-clicked on screen", x=x, y=y)
    return {"status": "ok", "action": "double_click", "x": x, "y": y}


def double_click(x: int, y: int) -> dict:
    """Double-click at viewport coordinates (x, y)."""
    return _run(_double_click_impl, x, y)


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------
def _send_keys_impl(text: str) -> dict:
    page = _require_page()
    page.keyboard.type(text, delay=40)
    logger.info("Typed text", text_preview=text[:50])
    return {"status": "ok", "action": "send_keys", "text": text}


def send_keys(text: str) -> dict:
    """Type *text* using the keyboard (no element targeting — types at focus)."""
    return _run(_send_keys_impl, text)


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------
def _scroll_impl(direction: str, amount: int) -> dict:
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
    logger.info("Scrolled", direction=direction, amount=amount)
    return {"status": "ok", "action": "scroll", "direction": direction, "amount": amount}


def scroll(direction: str = "down", amount: int = 300) -> dict:
    """
    Scroll the page.
    direction: 'down' | 'up' | 'left' | 'right'
    amount: pixels to scroll
    """
    return _run(_scroll_impl, direction, amount)


# ---------------------------------------------------------------------------
# Debugging helper
# ---------------------------------------------------------------------------
def _get_page_html_impl(max_chars: int) -> dict:
    page = _require_page()
    html = page.content()[:max_chars]
    return {"status": "ok", "html": html}


def get_page_html(max_chars: int = 8000) -> dict:
    """Return a truncated snapshot of the current page HTML for debugging.
    Last-resort fallback when get_interactive_elements and a screenshot both
    fail to clarify the page structure.
    """
    return _run(_get_page_html_impl, max_chars)


# ---------------------------------------------------------------------------
# Hybrid element grounding (DOM-first, vision-fallback)
# ---------------------------------------------------------------------------
_MARK_ELEMENTS_JS = r"""
() => {
    const SELECTOR = [
        'input', 'textarea', 'select', 'button',
        'a[href]', '[role="button"]', '[role="textbox"]',
        '[contenteditable="true"]'
    ].join(',');

    const results = [];
    let idx = 0;

    document.querySelectorAll(SELECTOR).forEach((el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = (
            rect.width > 0 && rect.height > 0 &&
            style.visibility !== 'hidden' && style.display !== 'none'
        );
        if (!visible) return;

        const ref = `agent-ref-${idx}`;
        el.setAttribute('data-agent-ref', ref);

        let label = el.getAttribute('aria-label')
            || el.getAttribute('placeholder')
            || '';
        if (!label && el.id) {
            const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (labelEl) label = labelEl.innerText.trim();
        }
        if (!label) {
            const parentLabel = el.closest('label');
            if (parentLabel) label = parentLabel.innerText.trim();
        }
        if (!label) label = (el.innerText || el.value || '').trim().slice(0, 60);
        if (!label) label = el.getAttribute('name') || '';

        results.push({
            ref,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || null,
            label: label.slice(0, 80),
            name: el.getAttribute('name') || null,
            id: el.id || null,
            x: Math.round(rect.x + rect.width / 2),
            y: Math.round(rect.y + rect.height / 2),
            in_viewport: rect.top >= 0 && rect.top <= window.innerHeight,
        });
        idx += 1;
    });

    return results;
}
"""


def _get_interactive_elements_impl(only_in_viewport: bool, max_elements: int) -> dict:
    page = _require_page()
    elements = page.evaluate(_MARK_ELEMENTS_JS)
    if only_in_viewport:
        elements = [e for e in elements if e["in_viewport"]]
    elements = elements[:max_elements]
    logger.info(
        "Marked interactive elements",
        count=len(elements),
        in_viewport_only=only_in_viewport,
        max_elements=max_elements
    )
    return {"status": "ok", "count": len(elements), "elements": elements}


def get_interactive_elements(only_in_viewport: bool = False, max_elements: int = 40) -> dict:
    """
    Walk the live DOM, tag every visible interactive element with a stable
    `data-agent-ref`, and return a compact list describing each one
    (ref, tag, inferred label, id/name, centre coordinates, viewport visibility).

    This is the primary way the agent should locate elements: it removes the
    need to guess CSS selectors or eyeball pixel coordinates. Call this again
    after any navigation, scroll, or DOM-changing action, since refs are only
    valid for the current DOM snapshot.
    """
    return _run(_get_interactive_elements_impl, only_in_viewport, max_elements)


def _ref_selector(ref: str) -> str:
    return f'[data-agent-ref="{ref}"]'


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(ElementNotFoundError),
    reraise=True
)
def _fill_by_ref_impl(ref: str, text: str) -> dict:
    page = _require_page()
    selector = _ref_selector(ref)
    try:
        page.wait_for_selector(selector, timeout=5_000)
        page.fill(selector, text)
        logger.info("Filled by ref", ref=ref, text_preview=text[:50])
        return {"status": "ok", "ref": ref, "text": text}
    except Exception as exc:
        logger.warning("fill_by_ref failed", ref=ref, error=str(exc))
        return {"status": "error", "ref": ref, "error": str(exc)}


def fill_by_ref(ref: str, text: str) -> dict:
    """
    Fill a form field identified by a `ref` returned from get_interactive_elements.
    Clears any existing value first. Preferred over click_on_screen since
    refs are guaranteed to match an element that was just observed on the
    page.
    """
    return _run(_fill_by_ref_impl, ref, text)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(ElementNotFoundError),
    reraise=True
)
def _click_by_ref_impl(ref: str) -> dict:
    page = _require_page()
    selector = _ref_selector(ref)
    try:
        page.wait_for_selector(selector, timeout=5_000)
        page.click(selector)
        logger.info("Clicked by ref", ref=ref)
        return {"status": "ok", "ref": ref}
    except Exception as exc:
        logger.warning("click_by_ref failed", ref=ref, error=str(exc))
        return {"status": "error", "ref": ref, "error": str(exc)}


def click_by_ref(ref: str) -> dict:
    """
    Click an element identified by a `ref` returned from get_interactive_elements.
    Preferred over click_on_screen since it targets the actual DOM node
    instead of a raw pixel coordinate.
    """
    return _run(_click_by_ref_impl, ref)