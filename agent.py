"""
agent.py — Generic Website Automation Agent
=============================================
Built on the OpenAI Agents SDK (`openai-agents`), running against a free
Groq model via the SDK's LiteLLM model interface — no OpenAI key required.

Unlike the earlier version, NOTHING about the target site or form is
hardcoded here. The agent receives a plain-English goal on the command line
and figures out the rest itself: which URL to open, which fields exist, and
how to fill/submit them.

Usage:
    python agent.py "Go to https://example.com/contact and fill Name with
    Aisha Khan and Message with Hello, then submit the form"

    python agent.py                      # runs the built-in demo goal

Model backend:
    Groq's qwen/qwen3.6-27b (free tier) is used
    because it supports both tool calling and vision — required for the
    hybrid DOM-first / vision-fallback element-finding strategy described
    in ARCHITECTURE.md.
"""

import asyncio
import json
import logging
import re
import sys
from collections import deque
from typing import Optional

from agents import Agent, Runner, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel
from agents.tool import ToolOutputImage, ToolOutputText
from litellm.exceptions import RateLimitError

import browser_tools as bt
import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("agent")

# The Agents SDK tries to upload traces to OpenAI's dashboard by default,
# which requires an OpenAI API key. We only use free services, so tracing
# is disabled outright.
set_tracing_disabled(True)


def _to_json(result: dict) -> str:
    """Serialize a browser_tools result as real JSON rather than Python's
    str(dict) repr — models parse standard JSON (double-quoted keys,
    true/false/null) far more reliably than Python literals, and it's no
    more expensive token-wise.
    """
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
# Every function below is exposed to the model as a callable tool. The SDK
# builds the JSON schema straight from the type hints + docstring, so the
# schema and the human-readable documentation can never drift apart like the
# old hand-maintained TOOLS list could.

@function_tool
def open_browser(headless: str = "false") -> str:
    """Launch the Chromium browser. Must be called before any other browser tool.

    Args:
        headless: Run without a visible window. Pass "true" or "false".
    """
    headless_bool = str(headless).lower() == "true"
    return _to_json(bt.open_browser(headless=headless_bool))


@function_tool
def navigate_to_url(url: str) -> str:
    """Navigate the browser to a URL and wait for the page to finish loading.

    Args:
        url: Fully-qualified URL to open, e.g. https://example.com/contact
    """
    return _to_json(bt.navigate_to_url(url))


@function_tool
def get_interactive_elements(only_in_viewport: str = "false", max_elements: int = 40) -> str:
    """Scan the current page and return every visible clickable/fillable
    element (inputs, textareas, selects, buttons, links) with a stable
    `ref`, its best-effort label, and its on-screen coordinates.

    Call this FIRST after every navigation, scroll, or action that changes
    the page, before trying to click or fill anything. Use the returned
    `ref` values with fill_by_ref / click_by_ref rather than guessing CSS
    selectors or coordinates.

    Large/complex pages can have hundreds of elements — the result is
    capped at max_elements (prioritizing visible, labeled ones) to avoid
    wasting tokens. Narrow with only_in_viewport=True if you only need
    what's currently on screen, especially after scrolling to a specific spot.

    Args:
        only_in_viewport: If true, only return elements currently scrolled into view. Pass "true" or "false".
        max_elements: Cap on how many elements to return.
    """
    only_in_viewport_bool = str(only_in_viewport).lower() == "true"
    return _to_json(bt.get_interactive_elements(only_in_viewport_bool, max_elements))


@function_tool
def fill_by_ref(ref: str, text: str) -> str:
    """Fill a form field using a `ref` obtained from get_interactive_elements.
    This is the preferred, reliable way to enter text — always try this
    before falling back to coordinate clicking.

    Args:
        ref: The element ref, e.g. "agent-ref-3".
        text: The text value to type into the field.
    """
    return _to_json(bt.fill_by_ref(ref, text))


@function_tool
def click_by_ref(ref: str) -> str:
    """Click an element using a `ref` obtained from get_interactive_elements.
    This is the preferred, reliable way to click — always try this before
    falling back to coordinate clicking.

    Args:
        ref: The element ref, e.g. "agent-ref-7".
    """
    return _to_json(bt.click_by_ref(ref))


@function_tool
def take_screenshot(filename: str = "screenshot.jpg") -> list[ToolOutputText | ToolOutputImage]:
    """Capture the current browser viewport and return it as an image so you
    can visually inspect the page. Saved as a compressed JPEG (token-cheaper
    than PNG) — fine for locating elements, not for pixel-perfect inspection.

    Use this as a FALLBACK when get_interactive_elements does not surface
    the element you need (e.g. canvas-based widgets, custom sliders, oddly
    structured markup) or to visually verify that a fill/click actually
    worked. Follow up a screenshot with click_on_screen coordinates if you
    need to act on something only vision revealed.

    Args:
        filename: Filename to save under the screenshots/ folder.
    """
    result = bt.take_screenshot(filename)
    b64 = result.get("base64")
    path = result.get("path", filename)
    if not b64:
        return [ToolOutputText(text=f"Screenshot failed: {result}")]
    return [
        ToolOutputText(text=f"Screenshot saved to {path}. Image follows:"),
        ToolOutputImage(image_url=f"data:image/jpeg;base64,{b64}"),
    ]


@function_tool
def click_on_screen(x: int, y: int) -> str:
    """Left-click at raw pixel coordinates (x, y) in the viewport.
    VISION FALLBACK ONLY — prefer click_by_ref whenever an element ref is
    available. Use this only for elements you identified from a screenshot
    that get_interactive_elements did not surface.

    Args:
        x: X coordinate in pixels.
        y: Y coordinate in pixels.
    """
    return _to_json(bt.click_on_screen(x, y))


@function_tool
def double_click(x: int, y: int) -> str:
    """Double-click at raw pixel coordinates (x, y). Vision fallback only.

    Args:
        x: X coordinate in pixels.
        y: Y coordinate in pixels.
    """
    return _to_json(bt.double_click(x, y))


@function_tool
def send_keys(text: str) -> str:
    """Type text into whichever element currently has keyboard focus.
    Prefer fill_by_ref, which targets a specific field explicitly; use this
    only after deliberately focusing an element (e.g. via click_by_ref) when
    fill_by_ref isn't applicable (rich text editors, custom widgets).

    Args:
        text: Text to type.
    """
    return _to_json(bt.send_keys(text))


@function_tool
def scroll(direction: str = "down", amount: int = 300) -> str:
    """Scroll the page to reveal elements outside the current viewport.

    Args:
        direction: One of "down", "up", "left", "right".
        amount: Pixels to scroll.
    """
    return _to_json(bt.scroll(direction, amount))


@function_tool
def get_page_html(max_chars: int = 8000) -> str:
    """Return a truncated snapshot of the raw page HTML. Use only for
    debugging when get_interactive_elements and a screenshot both fail to
    clarify the page structure — it is verbose and easy to misread.

    Args:
        max_chars: Maximum characters of HTML to return.
    """
    return _to_json(bt.get_page_html(max_chars))


@function_tool
def close_browser(reason: str = "task complete") -> str:
    """Close the browser. Call this once the task is fully complete.

    Args:
        reason: Why you're closing the browser (e.g. "task complete", "unrecoverable error").
    """
    logger.info("Closing browser: %s", reason)
    return _to_json(bt.close_browser())


TOOLS = [
    open_browser,
    navigate_to_url,
    get_interactive_elements,
    fill_by_ref,
    click_by_ref,
    take_screenshot,
    click_on_screen,
    double_click,
    send_keys,
    scroll,
    get_page_html,
    close_browser,
]


def _sanitize_tool_schemas(agent: Agent) -> None:
    """
    Defensive sanitization of tool JSON schemas for Groq/LiteLLM compatibility.

    1. If a tool has no arguments (empty 'properties'), injects a placeholder
       parameter to prevent Groq from rejecting the schema.
    2. Groq's API requires that the `required` list is present and contains
       every key defined in `properties`. We enforce this for all tools.
    """
    for tool in agent.tools:
        schema = getattr(tool, "params_json_schema", None)
        if not schema:
            continue

        # 1. Handle tools with no parameters
        if not schema.get("properties"):
            schema["properties"] = {
                "_unused": {"type": "string", "description": "Unused placeholder parameter."}
            }
            schema["required"] = ["_unused"]
            continue

        # 2. For all other tools, ensure required contains every property
        props = schema.get("properties", {})
        schema["required"] = list(props.keys())


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
# NOTE: this prompt is intentionally generic. It contains no site names, no
# element IDs, no field-to-selector mappings — that mapping is exactly what
# the agent has to work out at runtime from get_interactive_elements /
# take_screenshot, for whatever goal it is given.
INSTRUCTIONS = """You are a website automation agent. You control a real Chromium
browser through tools and must complete whatever task the user describes —
you are not limited to any specific site or form.

You are running in an interactive session: the user may give you several
tasks one after another (e.g. first "open YouTube", then later "search for
lofi music and play the first result"). Keep this in mind:
- If the user names a site/service without a URL ("open YouTube", "open
  Netflix"), infer the correct official URL yourself
  (e.g. https://www.youtube.com, https://www.netflix.com) — don't ask for
  it unless the name is genuinely ambiguous.
- Only call close_browser when the user's task explicitly asks you to close
  the browser, end the session, or similar. Otherwise leave the browser
  open when you finish a task, since the next task will likely continue in
  the same browser/tab.
- If ANY tool reports that the browser window was closed (manually by the
  user, or unexpectedly), call open_browser again to start a fresh session,
  then continue the task from the beginning — don't just give up.
- You may be shown a short "Recent tasks in this session" summary above the
  current task for context (e.g. what site you were last on). Use it to
  resolve references like "that page" or "it," but always re-verify the
  actual current state with get_interactive_elements rather than assuming
  the summary is still accurate — a lot can change between tasks.

Strategy (DOM-first, vision as fallback):
1. Call open_browser (safe to call even if already open — it will just
   reuse the existing session), then navigate_to_url for the target site.
2. Call get_interactive_elements to see what's on the page as structured
   data (refs, labels, coordinates). Match the user's field/button/link
   names to the closest label/placeholder/name you see — they will rarely
   match exactly, use judgement.
3. Act using fill_by_ref / click_by_ref whenever a suitable ref exists.
4. If the element you need isn't in the list (custom widgets, canvases,
   icon-only buttons, elements below the fold), scroll and re-run
   get_interactive_elements first. Only if it's still missing, take a
   screenshot, visually locate it, and act with click_on_screen /
   double_click / send_keys using the coordinates you see in the image.
5. Re-run get_interactive_elements after any action that might change the
   DOM (typing can trigger validation UI, clicking can open menus, playing
   a video changes the whole page, etc.).
6. Take a screenshot to visually confirm the final state before finishing.
7. When the task is fully done, say so in a final text reply (no more tool
   calls) summarizing what you did.

Be methodical: observe -> decide -> act -> observe again. If a selector or
ref action fails, don't repeat it blindly — re-scan the page and reconsider.
If a task is genuinely impossible (e.g. requires a login you don't have
credentials for), say so plainly instead of guessing at credentials.
"""


def build_agent() -> Agent:
    model = LitellmModel(model=config.MODEL_NAME, api_key=config.GROQ_API_KEY)
    agent = Agent(
        name="WebsiteAutomationAgent",
        instructions=INSTRUCTIONS,
        model=model,
        tools=TOOLS,
    )
    _sanitize_tool_schemas(agent)
    return agent


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

BANNER = """\
=== Website Automation Agent ===
Type a task in plain English and press Enter, e.g.:
  - open YouTube
  - go to netflix.com and search for The Office
  - open example.com and fill the contact form with my name John Doe
Type 'quit' or 'exit' to close the browser and stop.
"""


# ---------------------------------------------------------------------------
# Fixed-size session memory
# ---------------------------------------------------------------------------
# Deliberately NOT full conversation memory (see ARCHITECTURE.md): carrying
# the raw tool-call transcript of every past task forward would resend every
# old get_interactive_elements/screenshot payload on every future task,
# which is exactly what blew through the free-tier token budget earlier.
#
# Instead we keep a fixed-size window of short (goal -> outcome) summaries.
# Memory cost is bounded no matter how long the session runs: at most
# MAX_MEMORY_ITEMS entries, each capped at SUMMARY_MAX_CHARS, full stop.
MAX_MEMORY_ITEMS = 5
SUMMARY_MAX_CHARS = 160


class SessionMemory:
    """A fixed-size window of recent (goal, outcome) pairs for this session.
    Gives the agent enough context to resolve references like "that page"
    or "it" across tasks, without the unbounded cost of full transcripts.
    """

    def __init__(self, max_items: int = MAX_MEMORY_ITEMS):
        self._items: deque[tuple[str, str]] = deque(maxlen=max_items)

    def record(self, goal: str, outcome: str) -> None:
        summary = " ".join(outcome.split())[:SUMMARY_MAX_CHARS]
        self._items.append((goal, summary))

    def as_prefix(self) -> str:
        """Render the current window as a short block to prepend to the next
        goal. Empty string once there's no history yet (first task).
        """
        if not self._items:
            return ""
        lines = [f'- Task: "{g}" -> {o}' for g, o in self._items]
        return "Recent tasks in this session (context only, re-verify current state):\n" + "\n".join(lines) + "\n\n"


MAX_RATE_LIMIT_RETRIES = 6
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 25.0

_WAIT_TIME_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def _extract_wait_seconds(exc: Exception) -> float:
    """Groq's error message includes the exact wait time ('try again in
    14.19s') — parse it if present, otherwise fall back to a fixed backoff.
    A little padding is added since the message reflects the state at the
    moment the request was rejected, not when we'll actually retry.
    """
    match = _WAIT_TIME_RE.search(str(exc))
    if match:
        return float(match.group(1)) + 1.0
    return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS


async def run_task(agent: Agent, goal: str, memory: Optional["SessionMemory"] = None) -> None:
    """Run a single task against the shared agent/browser session.

    If *memory* is given, a short fixed-size summary of recent tasks is
    prepended to the goal for context, and the outcome of this task is
    recorded into it afterwards (bounded size — see SessionMemory).

    Automatically retries on Groq/LiteLLM rate-limit errors (free-tier TPM
    limits are easy to hit on pages with large DOMs), with a backoff derived
    from the provider's own suggested wait time when available.
    """
    logger.info("Task: %s", goal)
    effective_goal = (memory.as_prefix() if memory else "") + f"Current task: {goal}"

    for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
        try:
            result = await Runner.run(agent, effective_goal, max_turns=config.MAX_AGENT_STEPS)
            print("\n=== Agent output ===")
            print(result.final_output)
            if memory is not None:
                memory.record(goal, result.final_output or "(no summary)")
            return
        except RateLimitError as exc:
            if attempt > MAX_RATE_LIMIT_RETRIES:
                logger.exception("Task failed after %d rate-limit retries", MAX_RATE_LIMIT_RETRIES)
                print(
                    f"\n[!] Still rate-limited after {MAX_RATE_LIMIT_RETRIES} retries. "
                    "This is Groq's free-tier tokens-per-minute limit, not a bug — "
                    "wait a bit and try a smaller task, or try again shortly."
                )
                return
            wait_s = _extract_wait_seconds(exc)
            logger.warning(
                "Rate limited (attempt %d/%d) — waiting %.1fs before retrying",
                attempt, MAX_RATE_LIMIT_RETRIES, wait_s,
            )
            print(f"\n[i] Hit Groq's free-tier rate limit — waiting {wait_s:.0f}s and retrying automatically...")
            await asyncio.sleep(wait_s)
        except Exception:
            logger.exception("Task failed")
            print("\n[!] This task hit an error — see agent.log for details. "
                  "The browser is left open so you can try another task.")
            return


async def main() -> None:
    logger.info("=== Agent starting ===")
    agent = build_agent()

    # Tools are already sanitized in build_agent()

    
    memory = SessionMemory()

    # A CLI argument still works for one-shot / scripted use
    # (e.g. `python agent.py "open youtube"`), but with no argument the
    # agent drops into an interactive loop and waits for tasks at the prompt.
    one_shot_goal = " ".join(sys.argv[1:]).strip()

    try:
        if one_shot_goal:
            await run_task(agent, one_shot_goal, memory)
        else:
            print(BANNER)
            loop = asyncio.get_event_loop()
            while True:
                task = await loop.run_in_executor(
                    None, input, "\nEnter a task (or 'quit' to exit): "
                )
                task = task.strip()
                if task.lower() in ("quit", "exit", "q"):
                    break
                if not task:
                    continue
                await run_task(agent, task, memory)
    finally:
        # Safety net: make sure the browser doesn't linger after the
        # session ends, whether that's a clean 'quit' or an error.
        try:
            bt.close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())