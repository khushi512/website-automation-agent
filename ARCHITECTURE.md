# Architecture & Design Decisions

## 1. Agent framework: OpenAI Agents SDK, with Groq as the model via LiteLLM

The assignment points at the OpenAI Agents SDK as a reference. That SDK is
built around OpenAI's paid API by default, so getting it to run on free
infrastructure only was the first real decision.

**Option A — `openai-agents` + LiteLLM + Groq free tier (chosen)**
- Pros: it's the actual SDK named in the brief, so the architecture story
  ("I used the Agents SDK") holds up in the viva; tool schemas are
  auto-generated from Python type hints + docstrings instead of hand-written
  JSON (the old `agent.py` had ~180 lines of manually maintained tool specs
  that could silently drift from the real function signatures); free
  built-in agent loop, multimodal tool outputs (`ToolOutputImage`), and a
  `Runner.run_sync`/`run` API that's easy to reason about.
- Cons: an extra dependency (`litellm`) sits between the SDK and Groq, which
  is one more place things can break; the SDK's tracing feature tries to
  phone home to OpenAI's dashboard by default (fixed here by
  `set_tracing_disabled(True)`); Groq's free-tier function calling is solid
  but not as thoroughly battle-tested against this SDK as OpenAI's own
  models are, so occasional malformed tool calls are more likely than with
  GPT-4o.

**Option B — hand-rolled Agent/Runner wrapper directly on Groq's OpenAI-compatible client**
- Pros: zero extra dependencies beyond the `groq` client itself (this is
  what the original code did); full control over every message and retry;
  no risk of an SDK version bump changing behavior.
- Cons: doesn't literally use "the Agents SDK," so it's a weaker match to
  the assignment brief; every tool schema, the loop, error handling, and
  message formatting have to be maintained by hand — which is exactly the
  brittleness this rewrite is trying to get away from.

**Decision:** Option A. It satisfies the brief literally, removes the
schema-drift class of bugs, and stays 100% free by routing through Groq.

**Model choice:** `meta-llama/llama-4-scout-17b-16e-instruct` on Groq's free
tier, because it's one of the few free models that supports *both* tool
calling and vision in the same call — required for the hybrid strategy
below. A pure text model would force a second model just for screenshot
reasoning, which adds cost/complexity for a feature (vision fallback) that
should be the exception, not the common path.

## 2. Generalization: no hardcoded task, DOM discovered at runtime

The earlier version told the model, in the system prompt, exactly which CSS
IDs the "Name" and "Description" fields map to. That's a script wearing an
LLM as a costume — it can't handle a different site or even a redesign of
the same page.

This version's system prompt (`agent.py::INSTRUCTIONS`) contains **no site
names, IDs, or selectors**. The goal (e.g. "fill Name with X") is passed
entirely at runtime via CLI argument, and the agent has to:
1. Navigate to whatever URL the goal specifies.
2. Call `get_interactive_elements` to see the page's actual structure.
3. Fuzzy-match the goal's field names against the labels it finds.

This is strictly harder for the model — it has to reason about ambiguous
label matches instead of following a lookup table — which is exactly what
the rubric's "Agent Intelligence" criterion is scoring.

## 3. Element grounding: hybrid DOM-first, vision-fallback

This was the most consequential decision for reliability.

**Vision-only (screenshot + coordinates for every action)**
- Pros: works on literally anything renderable, including canvases and
  custom widgets; closest to how a human uses a browser.
- Cons: brittle — coordinates break under any font/DPI/viewport/layout
  change; needs a vision-capable model for every single step, which is
  slower and eats free-tier rate limits faster; the model has to visually
  estimate a click point, which is imprecise on small targets.

**DOM-only (selectors/refs for every action)**
- Pros: precise and deterministic — no coordinate guessing; fast, no image
  tokens needed most of the time; works even on text-only models.
- Cons: blind to canvas-rendered UI, some custom components, and elements
  whose accessible label genuinely can't be inferred from markup; a model
  asked to write raw CSS selectors from memory (as the old version did via
  `fill_by_selector`) will occasionally hallucinate a selector that doesn't
  exist on the page — the crashes I was actually seeing before this rewrite.

**Hybrid (chosen): DOM-first, vision-fallback**
- `get_interactive_elements` walks the live DOM on every page-changing
  action, tags every visible interactive element with a `data-agent-ref`
  attribute, and returns a compact list of (ref, tag, inferred label,
  centre x/y). The agent acts via `fill_by_ref`/`click_by_ref`, which is
  guaranteed to hit a real element that was just observed — this removes
  selector hallucination entirely, since the model never has to author CSS.
- Only when that scan doesn't surface the needed element (canvas widgets,
  icon-only buttons, oddly built menus) does the agent fall back to
  `take_screenshot` + `click_on_screen`/`double_click`, reasoning over the
  image the way a vision-only agent would.
- The two strategies share one source of truth: the same bounding-box
  centre coordinates computed during the DOM scan are what a human would
  click on in the screenshot too, so there's no mismatch between "what the
  DOM scan found" and "what the screenshot shows."
- Cons of the hybrid itself: it's more code than either pure strategy, and
  the model has to be prompted to *know when* to fall back rather than
  defaulting to one mode — handled here by explicit ordering in the system
  prompt ("try get_interactive_elements first; only use screenshots when
  that fails").

## 4. Tool-result image handling

The Agents SDK supports returning `ToolOutputImage` directly from a
function tool (as a list alongside `ToolOutputText`), so `take_screenshot`
hands the model the actual image inline with the tool result instead of a
separate synthetic "here's an image" user turn, which is what the previous
Groq-native implementation had to do manually to work around the chat
completions API's lack of native tool-result image support.

## 5. Error handling & logging

- Every `browser_tools` function returns a `{"status": "ok"/"error", ...}`
  dict rather than raising into the agent loop, so a failed click/fill
  becomes information the model can react to (e.g. re-scan and retry)
  instead of crashing the run.
- `fill_by_ref`/`click_by_ref` wait up to 5s for the ref to exist before
  acting, since DOM refs from a prior scan can go stale if the page
  re-rendered in between.
- All actions are logged to both stdout and `agent.log` with the exact tool
  name and arguments, so a failed viva run can be replayed from the log.
- `agent.py`'s `main()` wraps the run in a `try/finally` that force-closes
  the browser even if the agent errors out or hits `max_turns`, so a bad
  run doesn't leave orphaned Chromium processes behind.

## 6. Code cleanliness, token efficiency, and session memory (later pass)

A follow-up review caught four things worth fixing:

**Redundancy removed:** every function in `browser_tools.py` used to exist
twice — a private `_xxx_impl` plus a public wrapper whose only job was
`return _run(_xxx_impl, ...)`. A `@_pinned` decorator now collapses that
into one function per action (same thread-pinning guarantee, ~90 fewer
lines). Also replaced `str(dict)` tool returns in `agent.py` with real
`json.dumps` — Python's dict-repr isn't valid JSON (`True`/`None`,
single-quoted keys), which is more fragile for a model to parse back out
than standard JSON, at no extra token cost.

**Token efficiency:**
- `take_screenshot` now saves JPEG at quality 50 instead of PNG. For
  locating a button or field, near-lossless PNG fidelity is wasted
  precision — JPEG at this quality is dramatically smaller in base64 form
  for the same viewport, and visually indistinguishable for this purpose.
- `get_page_html` strips `<script>`/`<style>` contents and HTML comments
  and collapses whitespace before truncating. It's a last-resort debugging
  fallback; script/style bodies were pure noise tokens with zero value for
  structure inspection.
- `get_interactive_elements`'s `max_elements` cap (added earlier) already
  addressed the biggest single source of token blowup (150+ elements on
  complex pages).

**Fixed-size session memory:** the agent previously had zero memory across
tasks in a session — each typed command started a brand-new conversation,
so it couldn't resolve something like "click **that** result" from a
previous task. Full conversation memory was rejected earlier specifically
because it would resend every past task's raw tool-call transcript
(get_interactive_elements payloads, screenshots) on every future task —
exactly the mechanism that caused the earlier rate-limit failure.

The middle ground implemented: `SessionMemory` keeps a `deque(maxlen=5)` of
`(goal, outcome_summary)` pairs, each summary hard-capped at 160 characters
regardless of how verbose the model's response was. This is rendered as a
short "Recent tasks in this session" block prepended to each new goal.
Memory cost is provably bounded — at most 5 × 160 characters of overhead —
no matter how long the session runs, while still giving the model enough
context to resolve cross-task references. The system prompt explicitly
tells the model to treat this as context only and re-verify current state
with `get_interactive_elements` rather than trusting it blindly, since the
page can change completely between tasks.

**Manual browser-close detection:** if the user closes the Chromium window
by hand mid-session, the next tool call used to surface a raw Playwright
`TargetClosedError`. `_session_alive()` now checks `page.is_closed()` and
`browser.is_connected()` before every action; on detecting a dead session
it clears the stale globals and raises a clear, agent-readable message
("the browser window was closed... call open_browser again"). The system
prompt tells the model explicitly to call `open_browser` and retry the task
from the beginning when it sees this, rather than giving up. `open_browser`
itself was updated to relaunch cleanly from this stale state instead of
just checking "is `_page` not None," which would have incorrectly reused a
dead reference.



- ~~No automatic retry/backoff on Groq rate-limit errors~~ — **resolved**:
  `run_task` in `agent.py` now catches `litellm.exceptions.RateLimitError`
  specifically, parses Groq's own suggested wait time out of the error
  message when present, and retries automatically (up to 3 times) before
  giving up. Note this retries the *whole task* from scratch rather than
  resuming mid-task, since the SDK doesn't expose a way to resume a
  partially-completed run — acceptable for now, but a smarter version would
  persist progress and only replay the remaining steps.
- ~~get_interactive_elements could return huge payloads on complex pages~~
  — **resolved**: capped at `max_elements` (default 40), prioritizing
  visible + labeled elements, since a page like YouTube can otherwise
  return 150+ elements in one call and burn through free-tier token limits
  in a single task.
- The DOM scan doesn't currently pierce `<iframe>` boundaries or open
  shadow roots, which would need `frameLocator`/shadow-DOM-aware
  querying to extend to.
- No persistent memory/session across runs — every invocation starts fresh,
  each goal is one shot.