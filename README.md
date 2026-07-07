# Website Automation Agent

A generic browser automation agent: give it a plain-English instruction and
a real Chromium browser, and it navigates, reads the page, and fills/clicks
whatever it finds — no site-specific code, no hardcoded selectors.

Built on the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
running against **free** Groq models (via LiteLLM), controlling the browser
through [Playwright](https://playwright.dev/).

## How it's different from a scripted bot

The old version of this project had the target URL, field IDs, and even the
exact CSS selectors (`#form-rhf-demo-title`) written into the prompt. This
version knows nothing about any specific site. At runtime it:

1. Scans the live page and asks the browser itself "what's on this page?"
2. Matches your instruction's field names against what it finds using
   judgement, not a lookup table.
3. Falls back to reading a screenshot if the DOM scan doesn't surface what
   it needs (canvases, icon buttons, oddly-built widgets).

See `ARCHITECTURE.md` for the full reasoning behind these choices.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# then edit .env and paste in a free key from https://console.groq.com
```

## Run (CLI)

```bash
python agent.py
```

This starts an interactive session — no task, URL, or selector needs to be
given up front. The agent opens, then waits at a prompt:

```
Enter a task (or 'quit' to exit): open youtube
Enter a task (or 'quit' to exit): search for lofi music and play the first result
Enter a task (or 'quit' to exit): quit
```

The browser stays open across tasks in the same session, so later tasks can
build on where earlier ones left off. Type `quit` (or `exit`) to close the
browser and end the session.

You can also pass a task directly as a one-shot command for scripted
use (this runs the task once and exits, no prompt):

```bash
python agent.py "Go to https://example.com/contact and fill Name with Aisha Khan and Message with hello, then submit"
```

## Run (API Server - Production)

```bash
# Start the API server
uvicorn api:app --host 0.0.0.0 --port 8000

# Or with Docker
docker-compose up -d
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check for load balancers |
| `/metrics` | GET | Prometheus metrics |
| `/tasks` | POST | Run a task (JSON body: `{"goal": "..."}`) |
| `/browser/open` | POST | Open browser explicitly |
| `/browser/close` | POST | Close browser explicitly |

### Example API Request

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"goal": "open youtube and search for lofi music"}'
```

## Multi-Provider Support

The agent supports multiple LLM providers. Set `LLM_PROVIDER` in your `.env`:

```bash
# For Groq (default)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...

# For OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# For Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...
```

## Project Layout

| File | Purpose |
|---|---|
| `agent.py` | Agent definition, tool wiring, CLI entry point |
| `browser_tools.py` | All Playwright primitives (navigate, click, fill, screenshot, DOM scan) |
| `config.py` | Environment-driven settings with Pydantic validation |
| `api.py` | FastAPI REST API layer for production deployment |
| `tests/` | Comprehensive test suite |
| `Dockerfile` | Container image for production |
| `docker-compose.yml` | Multi-service deployment with monitoring |
| `pyproject.toml` | Package configuration and tooling |

## Testing

```bash
# Smoke test (no LLM required)
python test_browser_tools.py

# Full test suite
pytest tests/ -v --cov=website_automation_agent
```

## Production Deployment

```bash
# Build and run with Docker
docker build -t website-automation-agent .
docker run -d -p 8000:8000 --env-file .env website-automation-agent

# Or use docker-compose (includes Prometheus + Grafana)
docker-compose up -d
```

## Monitoring

Access Grafana at http://localhost:3000 (admin/admin) to view:
- Task success/failure rates
- Task duration histograms
- Browser operation metrics

## Known Limitations

- Free-tier Groq rate limits can interrupt long-running tasks — automatic retry
  logic is implemented with exponential backoff.
- Vision fallback quality depends on the underlying model's vision accuracy.
- Sites behind logins, CAPTCHAs, or heavy bot-detection aren't handled.
- Iframe and shadow DOM support is not yet implemented.