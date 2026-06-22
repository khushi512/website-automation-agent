# Website Automation Agent — Assignment 04

An AI-driven browser automation agent powered by **Groq (free tier)** with
**Llama 4 Scout** (vision + tool use) and **Playwright**. The agent autonomously navigates to a URL, identifies form elements by
taking and inspecting screenshots, and fills them in — no hard-coded selectors required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        agent.py                             │
│                                                             │
│  ┌──────────┐   goal / tool results   ┌─────────────────┐  │
│  │  Llama 4 │ ◄────────────────────── │  Agent Loop     │  │
│  │  (Groq)  │ ──── tool call ───────► │  (run_agent)    │  │
│  └──────────┘                         └────────┬────────┘  │
│                                                │            │
│                                   dispatch_tool()           │
│                                                │            │
└────────────────────────────────────────────────┼────────────┘
                                                 │
                              ┌──────────────────▼───────────────────┐
                              │           browser_tools.py           │
                              │                                       │
                              │  open_browser   navigate_to_url      │
                              │  take_screenshot  scroll             │
                              │  click_on_screen  double_click       │
                              │  send_keys  fill_by_selector         │
                              │  click_by_selector                   │
                              └───────────────────────────────────────┘
                                          │ Playwright API │
                                    ┌─────▼──────────────┐
                                    │  Chromium Browser  │
                                    └────────────────────┘
```

### How the loop works

1. The user's goal is injected as the first message.
2. The LLM receives the tool list and decides which tool to call next.
3. The agent dispatches the call to `browser_tools.py`.
4. For `take_screenshot`, the base64 PNG is sent back to the LLM as a **vision** block — the LLM literally *sees* the page.
5. The LLM decides the next action. This repeats until the LLM calls `task_complete` or `MAX_AGENT_STEPS` is hit.

---

## Tools

| Tool | Description |
|---|---|
| `open_browser` | Launch Chromium |
| `navigate_to_url` | Go to a URL |
| `take_screenshot` | Capture viewport → LLM inspects it |
| `scroll` | Scroll up/down/left/right |
| `click_on_screen(x, y)` | Click at pixel coordinates |
| `double_click(x, y)` | Double-click at coordinates |
| `send_keys` | Type text at current focus |
| `fill_by_selector` | Fill a field via CSS selector |
| `click_by_selector` | Click via CSS selector |
| `get_page_html` | Get truncated page HTML to identify selectors |
| `task_complete` | Signal success & stop the loop |

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

### 3. Add your Groq API key (free)

Get a free key at https://console.groq.com/keys

```bash
copy .env.example .env
# Edit .env and paste your GROQ_API_KEY
```

### 4. Run the agent

```bash
python agent.py
```

The agent will open a visible Chromium window, navigate to the shadcn form page,
scroll to the example form, fill in the Username and Bio fields, and submit the form.
All steps are logged to `agent.log` and screenshots are saved to `screenshots/`.

---

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `TARGET_URL` | shadcn form page | URL to automate |
| `FORM_VALUES` | `{username, bio}` | Values to enter |
| `HEADLESS` | `False` | Hide the browser window |
| `SLOW_MO_MS` | `50` | Delay between actions (ms) |
| `MAX_AGENT_STEPS` | `20` | Hard cap on agent iterations |

---

## Project Structure

```
website_automation_agent/
├── agent.py          # AI agent loop (LLM + tool use)
├── browser_tools.py  # Playwright-backed browser primitives
├── config.py         # Settings & environment variables
├── requirements.txt  # Python dependencies
├── .env.example      # API key template
├── screenshots/      # Auto-created; stores captured PNGs
└── agent.log         # Auto-created; full action log
```

---

## Design Decisions

- **LLM Vision for element detection** — instead of brittle XPath selectors, the agent takes a screenshot and lets the vision-capable LLM visually locate elements, just like a human would.
- **Hybrid strategy** — The LLM can choose between coordinate-based clicks (pixel perfect for custom UI) and CSS-selector-based fills (faster and reliable when selectors are known).
- **Hard step cap** — `MAX_AGENT_STEPS` prevents infinite loops if the page structure surprises the agent.
- **Separation of concerns** — `browser_tools.py` has zero AI logic; `agent.py` has zero Playwright calls. Easy to swap either layer.
