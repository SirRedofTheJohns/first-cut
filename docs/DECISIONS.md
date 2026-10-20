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
