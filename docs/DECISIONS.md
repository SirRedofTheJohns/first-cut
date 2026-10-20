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
