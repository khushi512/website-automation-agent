"""
agent.py  —  Website Automation Agent (Groq edition)
=====================================================
An AI-driven loop powered by Groq (free tier) that autonomously navigates a
web page, locates form fields via screenshots and DOM inspection, and fills them.

Model used: meta-llama/llama-4-scout-17b-16e-instruct
  - Free on Groq  (https://console.groq.com)
  - Supports vision AND tool/function calling
"""

import json
import logging
import sys
from typing import Any

from groq import Groq

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

# ---------------------------------------------------------------------------
# Groq client  (OpenAI-compatible API)
# ---------------------------------------------------------------------------
client = Groq(api_key=config.GROQ_API_KEY)

# Production-ready text model (extremely reliable function calling)
MODEL = "llama-3.3-70b-versatile"

# Vision-capable models list for conditional screenshot embedding
VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3.6-27b"
]

# ---------------------------------------------------------------------------
# Tool definitions  (OpenAI function-calling format)
# ---------------------------------------------------------------------------
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "open_browser",
            "description": "Launch the Chromium browser. Must be called before any other tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "headless": {
                        "type": "boolean",
                        "description": "Run without a visible window. Default false.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_to_url",
            "description": "Navigate the browser to the given URL and wait for the page to load.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully-qualified URL to open."}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": (
                "Capture the current browser viewport as a PNG and return it as an image "
                "so you can see the current page state. Call this frequently to observe progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename to save (stored in screenshots/ folder).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the page to reveal hidden content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up", "left", "right"],
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Pixels to scroll. Default 300.",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_on_screen",
            "description": "Left-click at pixel coordinates (x, y) in the viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "double_click",
            "description": "Double-click at pixel coordinates (x, y) in the viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_keys",
            "description": "Type text into whichever element currently has keyboard focus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_by_selector",
            "description": (
                "Fill a form field using a CSS selector — more reliable than clicking by "
                "coordinate. Clears any existing value first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for the input."},
                    "text": {"type": "string", "description": "Value to enter."},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_by_selector",
            "description": "Click an element identified by a CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"}
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": (
                "Signal that the automation task is fully done. "
                "Call this once the form has been filled and submitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief description of what was accomplished.",
                    }
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_html",
            "description": "Get a truncated snapshot of the current page HTML to identify exact input element selectors, name attributes, and IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters of HTML to return. Default 8000.",
                    }
                },
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def dispatch_tool(name: str, inputs: dict[str, Any]) -> Any:
    """Route a model tool call to the matching browser_tools function."""
    logger.info("Tool call → %s(%s)", name, json.dumps(inputs, ensure_ascii=False))

    if name == "open_browser":
        return bt.open_browser(headless=inputs.get("headless", config.HEADLESS))
    if name == "navigate_to_url":
        return bt.navigate_to_url(inputs["url"])
    if name == "take_screenshot":
        return bt.take_screenshot(inputs.get("filename", "screenshot.png"))
    if name == "scroll":
        return bt.scroll(inputs["direction"], inputs.get("amount", 300))
    if name == "click_on_screen":
        return bt.click_on_screen(inputs["x"], inputs["y"])
    if name == "double_click":
        return bt.double_click(inputs["x"], inputs["y"])
    if name == "send_keys":
        return bt.send_keys(inputs["text"])
    if name == "fill_by_selector":
        return bt.fill_by_selector(inputs["selector"], inputs["text"])
    if name == "click_by_selector":
        return bt.click_by_selector(inputs["selector"])
    if name == "get_page_html":
        return bt.get_page_html(inputs.get("max_chars", 8000))
    if name == "task_complete":
        return {"status": "done", "summary": inputs.get("summary", "")}

    raise ValueError(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _tool_result_msg(tool_call_id: str, content: str) -> dict:
    """Build an OpenAI-format tool result message."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _image_user_msg(b64: str, caption: str = "Current browser screenshot:") -> dict:
    """
    Build a user message that embeds a base64 PNG for the vision model.
    Groq Llama 4 expects image_url with a data URI.
    """
    return {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            },
            {"type": "text", "text": caption},
        ],
    }


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert browser automation agent with vision capabilities.
Your job is to control a real Chromium browser to complete the web task given by the user.

Guidelines:
- Start by calling open_browser, then navigate_to_url.
- Use take_screenshot to observe the page state — you will see the image immediately after.
- Use get_page_html to inspect the DOM to find the exact element IDs/selectors before typing or clicking.
- Prefer fill_by_selector and click_by_selector when you know valid CSS selectors.
- Scroll down if the form is not visible in the viewport.
- Note that the requested "Name" field maps to the "Bug Title" input field (ID: #form-rhf-demo-title), and the "Description" field maps to the "Description" textarea field (ID: #form-rhf-demo-description) in the Bug Report form demo (form-rhf-demo).
- After filling each field, take another screenshot to verify the value was entered.
- When the task is fully complete, call task_complete with a clear summary.
- Act one step at a time: observe → decide → act → observe again.
"""


def run_agent(goal: str) -> None:
    """Main agent loop."""
    logger.info("=== Agent starting ===")
    logger.info("Goal: %s", goal)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ]

    for step in range(1, config.MAX_AGENT_STEPS + 1):
        logger.info("--- Step %d/%d ---", step, config.MAX_AGENT_STEPS)

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        logger.info("Model finish_reason: %s", finish_reason)

        # Log any text the model produced
        if msg.content:
            logger.info("Model: %s", msg.content)
            print(f"\n[Agent] {msg.content}")

        # Append the assistant message to history
        messages.append(msg)

        # No tool calls → model is done
        if not msg.tool_calls:
            logger.info("No tool calls — agent finished.")
            break

        task_done = False

        for tc in msg.tool_calls:
            tool_name: str = tc.function.name
            tool_inputs: dict = json.loads(tc.function.arguments)
            tool_call_id: str = tc.id

            try:
                result = dispatch_tool(tool_name, tool_inputs)
            except Exception as exc:
                logger.exception("Tool %r raised an error", tool_name)
                result = {"status": "error", "error": str(exc)}

            # --- Handle screenshot specially: embed image for vision ---
            if tool_name == "take_screenshot" and isinstance(result, dict) and "base64" in result:
                b64 = result["base64"]
                path = result.get("path", "screenshot.png")
                # Tool result (text only — Groq tool messages must be plain strings)
                messages.append(_tool_result_msg(tool_call_id, f"Screenshot saved to {path}"))
                # Only follow-up with vision message if using a vision-enabled model
                if MODEL in VISION_MODELS:
                    messages.append(_image_user_msg(b64, "Here is the current browser screenshot:"))
                else:
                    messages.append({"role": "user", "content": f"Screenshot successfully taken and saved to {path}."})
            else:
                # All other tools: serialise result as JSON string
                messages.append(_tool_result_msg(tool_call_id, json.dumps(result, ensure_ascii=False)))

            # Check for completion signal
            if tool_name == "task_complete":
                summary = tool_inputs.get("summary", "")
                print(f"\nTask complete: {summary}")
                logger.info("Task complete: %s", summary)
                task_done = True
                break

        if task_done:
            break

    else:
        logger.warning("Max steps (%d) reached without completion.", config.MAX_AGENT_STEPS)
        print(f"\nReached max steps ({config.MAX_AGENT_STEPS}) — agent stopped.")

    # Always close the browser cleanly
    try:
        bt.close_browser()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    goal = f"""
    Please automate the following web task:

    1. Open a browser window.
    2. Navigate to: {config.TARGET_URL}
    3. Scroll down until you can see the first form (the "Bug Report" form).
    4. Call get_page_html to inspect the HTML structure of the page and find the exact element IDs or selectors.
    5. Automatically fill the Bug Title field (Name) with: {config.FORM_VALUES['title']}
    6. Automatically fill the Description field with: {config.FORM_VALUES['description']}
    7. Click the "Submit" button of the Bug Report form.
    8. Take a final screenshot to confirm success.
    9. Call task_complete with a summary of what you did.
    """

    run_agent(goal)
