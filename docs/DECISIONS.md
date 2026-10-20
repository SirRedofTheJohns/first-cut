# Technical Decisions

Short records of the decisions that shape this project: what was chosen, why, and what was considered instead.

---

## D001 — Zero-cost constraint drives every external dependency
**Decision:** Every service must work on a free tier with no credit card on file.
**Why:** It's a portfolio project. Anyone should be able to clone it and run it.
**Consequences:** Local LLM via Ollama for development; Gemini free tier (primary) and Groq free tier (fallback) for the hosted demo; a Hugging Face model on a ZeroGPU Space. Hugging Face Inference Providers is supported in config but not used by default, because free accounts no longer receive inference credits.

## D002 — `uv` for dependency management
**Decision:** `uv` with `pyproject.toml` + `uv.lock`, and dependency groups for dev tools.
**Alternatives:** Poetry or pip-tools.
**Why:** It resolves and installs much faster, gives a single lockfile for reproducible CI (`uv sync --locked`), and manages Python versions too.

## D003 — `src/` layout plus a separate `mcp_server` package
**Decision:** Application code lives in `src/firstcut`. The MCP server is its own top-level package, `mcp_server`, and both ship in the same wheel.
**Why:** The `src/` layout stops tests from importing the working tree by accident. Keeping the MCP server separate makes its boundary obvious: it depends on the WordPress client, and the agent depends on it only through the MCP protocol.

## D004 — Local WordPress bootstrapped by a one-shot WP-CLI container
**Decision:** Docker Compose runs MariaDB, WordPress, and a `wpcli` container that installs WordPress, sets pretty permalinks, and creates an Application Password.
**Alternatives:** Manual setup through the browser, or a custom image.
**Why:** `docker compose up` alone gives a ready-to-use API with no manual steps. The script is idempotent, so restarts are safe.
**Gotchas:**
- WordPress only allows Application Passwords over HTTPS, unless `WP_ENVIRONMENT_TYPE` is `local`. Compose sets it through `WORDPRESS_CONFIG_EXTRA`.
- The `wordpress:cli` image is Alpine-based (`www-data` = uid 82), while the Apache image is Debian (`www-data` = uid 33). The CLI container runs as `33:33` so it can write to the shared volume.
- MariaDB is used instead of MySQL: it's wire-compatible, and its official image ships a ready-made healthcheck script.

## D005 — Secrets hygiene
**Decision:** Secrets come only from environment variables (`.env` locally, Space secrets in the cloud) and are typed as `SecretStr`, so they never show up in logs or reprs. `.gitignore` excludes `.env`, `secrets/` and credential JSON files. CI runs gitleaks over the full git history.
**Why:** Leaking a token in a public portfolio repo is the fastest way to fail a security-minded review.
**False positives:** gitleaks flagged Figma *style keys* and the Figma *file key* in a test fixture (8 findings). Both are public identifiers; reading the file still needs `FIGMA_TOKEN`. `.gitleaks.toml` keeps the default rules and allow-lists only that fixture path and that file key. A control scan of the local `.env` still reports its real secrets, so the scanner isn't blinded.

## D006 — Ruff for linting and formatting; integration tests opt-in
**Decision:** Ruff handles both linting and formatting. Pytest skips tests marked `integration` by default (`-m 'not integration'`).
**Why:** One fast tool instead of flake8 + isort + black. CI has no WordPress or LLM, so unit tests use fakes, and the integration tests run locally against Docker.

## D007 — Graph shape: plan → parallel writers (map) → reviewer (reduce) → bounded rewrite loop
**Decision:** `plan_sitemap` fans out one `write_page` task per page with LangGraph's `Send` API. A reducer (`merge_pages`) merges each writer's page into `state["pages"]`, and `review` runs once all writers in the superstep are done. When the reviewer flags issues, only the flagged pages are re-sent to `write_page`, together with the previous draft and the feedback. The loop is capped at `MAX_REVISIONS` (default 2).
**Alternatives:** One LLM call that writes the whole site (bigger output, so worse quality on small models and a single point of failure), or a sequential loop over pages (slower).
**Why:** Pages are independent, so writing them in parallel cuts latency, and each call gets a small, focused prompt, which matters for 8B models. The cap keeps the cost of a strict reviewer predictable; anything still open goes to the human approval step.
**Guardrail:** Issues the reviewer reports for slugs that don't exist get dropped. Small models sometimes invent pages.

## D008 — Dependencies injected through LangGraph's runtime context
**Decision:** The LLM (and later, the tools) reach nodes through `context_schema=Deps` / `Runtime[Deps]`, not through module globals.
**Why:** Tests pass a fake LLM to `graph.invoke(..., context=Deps(llm=fake))` without monkeypatching, and the API can choose a model per request. The context is not checkpointed, so a non-serializable client object is fine there.

## D009 — Structured output with a validate-and-retry loop and a prompt-based fallback
**Decision:** `structured_call()` uses the provider's native structured output (`with_structured_output(..., include_raw=True)`) when it exists, and otherwise injects the JSON schema into the prompt and parses the reply. Either way, a Pydantic validation error goes back to the model as a new message, for up to 3 attempts.
**Why:** It is the same code path for Ollama, Groq, Gemini, and for raw `transformers` models on the ZeroGPU Space, which have no native tool calling. `include_raw=True` returns parsing errors instead of raising them, so they can be fed back. The unit-test fakes have no native support, so the fallback path is covered by tests too.

## D010 — Semantic limits in validators, not in JSON-schema constraints
**Decision:** Content rules (button label ≤ 40 chars, meta description length, no HTML, no `[placeholders]`) are `field_validator`s, not `Field(max_length=...)`.
**Why (found by testing):** Ollama compiles the JSON schema into a decoding grammar. With `maxLength: 40` the model didn't write a shorter CTA; the grammar cut it mid-sentence ("Complete the form below to start the off"). A validator is not part of the schema, so the model writes freely, and if the result is too long it gets the error message and rewrites the CTA properly.

## D011 — Default local model: Qwen3-8B (Q8_0 GGUF) pulled from the Hugging Face Hub
**Decision:** `LLM_MODEL=hf.co/Qwen/Qwen3-8B-GGUF:Q8_0`, with thinking disabled (`reasoning=False`).
**Evidence:** `scripts/smoke_models.py`, 3 reps per check, RTX 4080 Super 16 GB:

| Model | Structured SiteMap (1st try) | 1 tool call | 3 parallel tool calls |
|---|---|---|---|
| `qwen3.5:9b` | 3/3 · 16.3s | 3/3 · 1.1s | 3/3 · 2.5s |
| `hf.co/Qwen/Qwen3-8B-GGUF:Q8_0` | 3/3 · 7.2s | 3/3 · 3.9s | 3/3 · 7.5s |
| `gemma4:12b` | 3/3 · 9.2s | 3/3 · 0.9s | **0/3** (one call per turn) |

**Why Qwen3-8B over qwen3.5:9b (both pass everything):** It is the same model the Hugging Face ZeroGPU demo runs with `transformers`, so development and the public demo behave alike, and it comes straight from the HF Hub. `qwen3.5:9b` is a drop-in alternative (`LLM_MODEL=qwen3.5:9b`) with faster tool calls.
**End-to-end:** All 3 sample briefs produce a complete, approved site in ~95–140 s locally. Hallucination checks pass: Ledgerly's copy says SOC 2 is "in progress" (the brief forbids claiming certification), and Northline lists all four insurers and the $140 cash price.

**Also learned:** For small models, field *names* steer output more than descriptions do. `call_to_action` kept getting full sentences; renaming it to `button_label` (same description) took first-try validity of the writer's output from 0/12 to 9/12. The remaining 3 failures were real catches (an invented `[insert date]`, a fake testimonial from `[Café Name]`), and the retry loop fixed them before they reached WordPress.

## D012 — Publishing: a tool-calling agent for orchestration, code for invariants
**Decision:** `publish_drafts` runs a small `create_agent` loop with two tools, `list_pages` and `save_draft(slug, page_id?)`. The LLM never handles page HTML: `save_draft` renders the draft to Gutenberg blocks itself. Afterwards, a deterministic check saves any draft the agent skipped, and each page is tagged `saved_by: agent | verification` for observability.
**Alternatives:** (a) A plain loop with no LLM: simpler, but it wouldn't exercise tool calling, which is a core requirement of this project. (b) A generic `create_page(title, content)` tool: the model would have to copy kilobytes of HTML into tool arguments, which is slow, expensive and error-prone for 8B models.
**Invariants enforced in code, not in the prompt:**
- No duplicates: if a page with the slug exists (or was saved earlier in this run), it gets updated, even when the model forgets `page_id`.
- A wrong `page_id` returns an explanatory error to the model instead of overwriting another page.
- Live (published) pages are never modified; they only change through the human approval step.
**Result:** Two consecutive live runs: every page saved by the agent, and the second run updated the same page ids instead of creating copies.

## D013 — WordPress client: async httpx, Gutenberg blocks, JSON-text tool results
- **Async**: MCP tools (phase 3) are async-only, so the WordPress path is async end-to-end, and the CLI runs the graph with `astream`. The LLM nodes stay sync; LangGraph runs them in a thread pool.
- **Gutenberg block markup** (`<!-- wp:paragraph -->…`) rather than raw HTML, so editors can keep working on the pages in the block editor. All model text is HTML-escaped (defense in depth on top of the no-HTML validator).
- **Tools return JSON strings**, like MCP tool results. A tool that returned a Python list put a list into the `ToolMessage`, which chat providers expect to be text. Matching MCP's contract means the backend swap in phase 3 doesn't change what the LLM sees.
- **`status=any&context=edit`** when listing, so drafts (and raw titles) are visible to the agent.

## D014 — Own MCP server; the agent reaches WordPress only through MCP
**Decision:** `mcp_server` (official MCP Python SDK, `FastMCP`) exposes `list_pages`, `get_page`, `create_page` and `update_page`. The agent loads those tools with `langchain-mcp-adapters` and never calls the REST API itself. The direct-REST LangChain tools from phase 2 were deleted, so there is a single path.
**Why:** It shows both sides of MCP. The same server works with the agent, Claude Desktop and MCP Inspector, and WordPress credentials live only in the server process.
**Details worth knowing:**
- **Transports:** stdio by default (the agent spawns `python -m mcp_server`; this is also what Claude Desktop and Inspector use), and streamable HTTP when `MCP_WORDPRESS_URL` is set (the `mcp` Docker service; the API in phase 5 uses this). HTTP also avoids a Windows issue: uvicorn's `--reload` uses a selector event loop that cannot spawn asyncio subprocesses.
- **One session per run** (`client.session(...)` + `load_mcp_tools`). `client.get_tools()` opens a new session for every tool call, which over stdio means spawning a new server process each time.
- **The stdio child gets a minimal environment.** The MCP SDK does not forward your environment variables, so the WordPress settings are passed explicitly. For Claude Desktop, `uv --directory <repo> run` makes the server read the repo's `.env`, so no password goes into the Claude config.
- **Lifespan-managed HTTP client:** one `httpx` connection pool for the server's lifetime, reached from tools via `ctx.request_context.lifespan_context`. `create_server(client_factory=...)` makes it injectable for tests.
- **Tool annotations:** `readOnlyHint` on reads and `destructiveHint` on `update_page` (it can make a page live), so clients like Claude Desktop can ask for confirmation.
- **Results are JSON text** (`structured_output=False`). FastMCP turns a returned *list* into one content block per item, which would break JSON parsing of `list_pages`.

## D015 — Tool errors: text for the LLM, exceptions for code
**Decision:** MCP tool errors reach the LLM as an error `ToolMessage` (the adapter's default, `handle_tool_errors=True`), so the agent can react. When *code* calls a tool (`call_tool()`), it invokes it with a `ToolCall` and turns `status == "error"` into a `ToolException`.
**Why (found by testing):** With the default settings, `tool.ainvoke(args)` doesn't raise on a WordPress 404; it returns `"Error executing tool …"` as content, which would otherwise surface as a confusing `JSONDecodeError`. Checking `ToolMessage.status` avoids parsing error strings.

## D016 — Tests exercise the real MCP protocol, in memory
**Decision:** The graph tests build the real MCP server around an in-memory fake WordPress, connect over `mcp.shared.memory.create_connected_server_and_client_session`, and load tools with `load_mcp_tools`, exactly as in production but with no network or subprocess.
**Why:** The tests caught two real contract details that unit tests with plain fake tools would have missed: adapter results are lists of content blocks, and errors are returned instead of raised.
**Verified live:** the agent over stdio and over HTTP (Docker → WordPress), container-to-container access by service name (`http://mcp:8765/mcp`, so FastMCP's DNS-rebinding protection doesn't block it), and MCP Inspector CLI (`tools/list` shows the 4 tools with annotations; `tools/call` hits real WordPress).

## D017 — Webhook security: HMAC over `timestamp.body`, replay window, idempotent deliveries
**Decision:** `POST /webhooks/brief` requires `X-FirstCut-Timestamp` and `X-FirstCut-Signature: sha256=HMAC(secret, "{timestamp}.{raw body}")`, accepts timestamps within ±5 minutes, and compares signatures with `hmac.compare_digest`. An optional `X-FirstCut-Delivery` id is used as the run id, so a retried delivery returns the existing run (200) instead of starting a second one.
**Why:**
- The signature is checked against the **raw bytes** before any JSON parsing; re-serialized JSON may not be byte-identical to what was signed.
- Signing the timestamp stops replays: an attacker can't reuse an old signature with a new timestamp.
- Constant-time comparison avoids timing side channels.
- Webhook senders retry on timeouts, so deliveries must be idempotent.
- **Fail closed:** without `WEBHOOK_SECRET` the endpoint returns 503; it never runs unsigned.
**Alternatives:** API keys in a header (no body integrity, no replay protection), or mTLS (overkill here).

## D018 — Human in the loop: `interrupt` + `Command`, and feedback becomes part of the brief
**Decision:** After the drafts are saved, `human_approval` calls `interrupt(payload)`. The run is checkpointed and the API reports `awaiting_approval`. `POST /runs/{id}/approval` resumes it with `Command(resume=decision)`. The node routes with `Command(goto=...)`:
- approve → `finalize` (drafts → `publish`)
- feedback per page → rewrite only those pages, then back to approval
- reject with no feedback → end, drafts stay drafts
**Details:** Resuming re-executes the node from the top, so nothing before `interrupt()` has side effects.
**Found by live testing (twice):**
1. The writer ignored "pre-orders close Thursday at 6pm" because its anti-hallucination rule only trusts facts in the brief. Fix: human feedback is appended to the brief as an authoritative "Editor feedback" section, so the writer *and* the reviewer accept the new facts without loosening the rule. The reviewer's revision budget is reset and it checks that each point is visible.
2. Even then, the 8B model returned the previous draft unchanged when that draft was in the prompt as JSON: **0/4** requests applied (and 2/4 with the draft as plain text). Rewriting from brief + plan + request, without the previous draft: **4/4**. Revisions therefore don't include the previous draft. Nothing is lost, because every fact lives in the brief.

## D019 — Persistence: async SQLite checkpointer with an explicit type allowlist
**Decision:** `AsyncSqliteSaver` (file in `data/`, a Docker volume) via `firstcut.checkpoints.sqlite_checkpointer`, with a `JsonPlusSerializer` whose `allowed_msgpack_modules` lists our Pydantic state types.
**Why:** Runs can wait for approval for days, across deploys. Verified live: a run paused, the API restarted twice, then feedback and approval completed it.
**Security:** LangGraph warns (and will soon refuse) when it deserializes classes that aren't allowlisted, because loading arbitrary types from a tampered DB is a code-execution risk. The approval tests run with `LANGGRAPH_STRICT_MSGPACK=true`. Removing one type from the list makes them fail, which proves the check works.
**Alternatives:** Postgres (`langgraph-checkpoint-postgres`) for multiple replicas; SQLite is enough for a single process and needs no extra service.

## D020 — Streaming: SSE from `astream(["updates", "messages"])`
**Decision:** Each run's graph executes in a background task. `updates` become `node` events with compact summaries; `messages` become `token` events (live LLM output, opt-in with `?tokens=true`). An interrupt becomes `awaiting_approval`, and each segment ends with a `status` event. Events have incremental ids, so a reconnecting `EventSource` sends `Last-Event-ID` and only gets what it missed.
**Why SSE over WebSockets:** the traffic is one-way (server → client), SSE works over plain HTTP and through proxies, and browsers reconnect automatically.
**Bug caught by tests:** `sse-starlette` sends `str(data)`, so a dict arrived as a Python repr (`{'type': ...}`), not JSON. Events are now `json.dumps`-ed explicitly.
**Limitation:** The event log lives in memory and in one process; it feeds live progress only. Run state comes from the checkpointer, so `GET /runs/{id}` and approval keep working after a restart. Multiple replicas would need Redis pub/sub or similar.

## D021 — Structured JSON logs with run context
**Decision:** `structlog` with JSON output. `run_id` is bound with `structlog.contextvars` inside each run task, so every line from that run, including library calls, carries it. Log events: `run_started`, `webhook_rejected` (with reason), `approval_received`, `run_segment_started/finished`, `run_failed` (with traceback).
**Tracing:** LangSmith is opt-in through its standard env vars (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`); LangChain picks them up with no code changes.

## D022 — Figma brand styles: one cached file read, values resolved through layers
**Decision:** `FigmaClient` reads `GET /v1/files/:key` with a personal access token that has only the `file_content:read` scope. `extract_style_guide()` maps each local **style** (not Variables) to its value by walking the document, because the file's `styles` map holds only names and types.
**Constraints found:**
- **Rate limit:** on the free (Starter) plan, file reads are a Tier 1 endpoint, capped at **~20 per month**. Responses are cached on disk for 24 h (`FIGMA_CACHE_HOURS`, `--refresh` available in code). On HTTP 429 a stale cached copy is used instead of failing. The cheaper `/meta` endpoint (to check the version first) needs the `file_metadata:read` scope, which the token deliberately doesn't have.
- **Variables API:** Enterprise only, so the integration uses Styles.
- **Styles can't be created through the REST API**; only the Plugin API can. `scripts/figma_brand_plugin/` is a small development plugin that creates the sample brand (4 color + 2 text styles, applied to layers) in one click. It is idempotent. The ChatGPT Figma app only creates FigJam and Slides, so it couldn't do this.
**Test fixture:** a trimmed copy of the real API response (`tests/fixtures/figma_masa_brand.json`). `thumbnailUrl` is removed because it contains a presigned AWS URL that secret scanners flag.

## D023 — Applying the brand in WordPress without breaking the block editor
**Decision:** Brand styling is one Custom HTML block (Google Fonts `<link>` plus a `<style>` scoped to `.firstcut-brand`) and a Group block with that class around the page content. Colors and fonts are assigned to roles by name (primary/accent, text, heading, body), falling back to order and size. The button label color is the palette color with the highest **WCAG contrast** against the button background.
**Why not inline styles on each block:** Gutenberg validates each block by re-serializing its attributes. Hand-written inline styles that don't match byte for byte show up as "This block contains unexpected or invalid content". A scoped stylesheet keeps every content block standard and editable.
**Security:** Figma values are third-party input. Hex colors are normalized by our own code, and font family names must match `[A-Za-z0-9 -]+` before they reach CSS or a URL (a test feeds `X}</style><script>`). Saving `<style>`/`<link>` needs the `unfiltered_html` capability, which the agent's admin user has; verified on the live page.
**Alternative for production:** writing the palette and fonts into the theme's Global Styles (`theme.json`) through the REST API, which would make them site-wide and editable in the Site Editor. That needs one more MCP tool and a block theme.

## D024 — Google Docs through a service account, without the heavyweight client
**Decision:** `google-auth` mints a short-lived OAuth token from the service account key (scope `documents.readonly`), and `httpx` calls `documents.get`. The document is converted to markdown (headings, bullets, tables) before it reaches the LLM.
**Why:** `google-api-python-client` adds a large discovery-based dependency for a single GET. A service account means no browser consent flow in a server context, and it can only read documents explicitly shared with its email. A 403/404 error tells the user exactly which email to share the doc with.

## D025 — Failure handling: repair in code, retry the model, then retry the node
**Found live:** One writer kept returning a 205-character meta description. After 3 attempts its `StructuredOutputError` failed the **entire run**, though the other five pages were fine.
**Decision, in three layers:**
1. **Repair what code can fix deterministically.** A long meta description is trimmed at a word boundary in the validator. Asking the model again rewrites the whole page (~15 s locally) for a field code can fix in microseconds.
2. **Send back to the model only semantic problems** (HTML, placeholders, sentence-length button labels): `structured_call` feeds the validation error back, up to 3 attempts.
3. **LangGraph `RetryPolicy(max_attempts=2, retry_on=StructuredOutputError)`** on the LLM nodes. If a node still gives up, LangGraph re-runs only that task from scratch; the parallel writers that succeeded are not repeated. A test simulates three bad outputs in a row and checks that the node's second run succeeds.

## D026 — Phase 4 verification
`firstcut run <Google Doc URL> --figma <Figma URL>` (and the same through the Docker API with `gdoc_url`/`figma_url`): the brief comes from a Google Doc read by the service account; the copy uses facts that exist **only** in that Doc (pre-orders close Thursday 6pm, 20-loaf wholesale minimum with Tuesday/Friday delivery, weekend hours taken from a Docs *table*); and every page carries the Figma brand (`#C2410C` buttons, Playfair Display headings), published after approval. The GCP project has billing **disabled**. The Gemini API key is restricted to `generativelanguage.googleapis.com`, and the service account has no IAM roles: it can read only documents shared with it.

## D027 — Cloud models for the hosted demo, chosen by measurement
Full agent runs (Ledgerly brief, preview mode, this account's free tiers, Oct 2026):

| Model | Result |
|---|---|
| Gemini `gemini-2.5-flash` | **404**: "no longer available to new users" |
| Gemini `gemini-3.8-flash` | Works; 53 s for a *single* call (heavy thinking) |
| Gemini `gemini-3.1-flash-lite` | Approved site in 111 s (RPM throttling dominates) |
| **Gemini `gemini-3-flash-preview`** | **Approved site in 39 s → primary** |
| Groq `openai/gpt-oss-20b` | Fails: empty generations in strict JSON mode, and forced tool calls refused 0/2 on the writer prompt |
| **Groq `openai/gpt-oss-120b`** | 2/2 with both methods; full site in ~8 min under 8K TPM → **fallback** |

**Fallback design:** `llm.with_fallbacks()` returns a plain Runnable that loses `with_structured_output`, so the fallback wraps the structured runnables instead (`structured_call(..., fallback=...)`). It fires on provider errors (429, 5xx, 404), not on invalid output, which the retry loop already handles. Verified by pointing the primary at the 404 model: the call completed on Groq.
**Provider quirks absorbed in one place (`structured_call`):**
- Groq uses `method="json_schema"`. Its default forced tool call was refused 1 in 4 times ("Tool choice is required…").
- Providers that validate JSON server-side reject a bad generation with **HTTP 400**. That is retried like invalid output; other errors (401, 429, network) still propagate.
- Groq gets a default client-side limiter of 0.05 req/s: 8K tokens/min ÷ ~2.5K tokens per call. Six parallel writers otherwise produced 429s the SDK's retries couldn't absorb. `max_retries=6` for the free-tier providers.
**Bugs found on the way:**
- `pydantic-settings` reads `.env` without exporting it, while LangChain integrations read API keys from `os.environ`. Fix: `load_dotenv(override=False)` in `get_settings()`. Tests disable it in `conftest.py`, because exporting a developer's `.env` into the test process leaked a real password into a "defaults" test.
- The API module built its app at import time (`app = create_app()`), so importing it had side effects. It now runs with `uvicorn --factory firstcut.api.app:create_app`.

## D028 — The public demo: Gradio on a ZeroGPU Space, two backends
**Decision:** A Gradio app (`app/`) runs the same graph in preview mode (no WordPress, no approval) with two backends:
- **Gemini 3.5 Flash-Lite** with Groq fallback: full site, ~30 s.
- **Qwen3-8B from the Hugging Face Hub** with `transformers` on **ZeroGPU**: the same model family as the local default.

`scripts/deploy_space.py` assembles the Space from source (the `firstcut` package, sample briefs, a Figma fixture so the demo never spends Figma quota) and uploads it. API keys are set as Space **secrets**, never as files, and the build folder is scanned for key patterns before upload.
**ZeroGPU specifics:**
- Weights are placed on `cuda` at import, which ZeroGPU emulates. Each LLM call is one `@spaces.GPU` task, billed to the *visitor's* daily quota (2 min anonymous, 5 min signed in).
- To fit in that quota, the Qwen backend plans 3 pages (`Deps.max_pages`, enforced in code after the planner), skips extra review rounds, and runs one call at a time (`max_concurrency=1`). Measured on the live Space: 46 s end to end.
- Qwen3's thinking mode is disabled in the chat template, so the quota isn't spent on hidden reasoning.
- The wrapper (`ChatZeroGPU`) has no native tool calling, so `structured_call` uses its JSON-in-prompt path, the reason that path was built in phase 1.
**Build failure found on deploy:** HF installs `gradio[mcp]`, which caps `pydantic<=2.12.5`, and adds `torch<=2.13` and `spaces` itself. Pinning `pydantic==2.14.1` made the build unresolvable. The Space now pins only our own stack (LangChain/LangGraph, transformers) and leaves shared libraries to pip; a local `uv pip compile` with the injected packages checks it.
**Alternatives considered:** CPU Basic Spaces (reportedly no longer free for new accounts in 2026); HF Inference Providers (no free credits for free accounts).
