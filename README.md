# First Cut

> Turns a client brief into a reviewed WordPress site draft: sitemap, page copy and style guide, with a human approval step before anything goes live.

🚧 Work in progress. The full README (architecture, demo, provider switching) lands in phase 6.

## Quick start (local)

```bash
cp .env.example .env                      # set WEBHOOK_SECRET
ollama pull hf.co/Qwen/Qwen3-8B-GGUF:Q8_0
docker compose up -d db wordpress wpcli   # WordPress at http://localhost:8080
docker compose logs wpcli                 # copy WP_APP_PASSWORD into .env
docker compose up -d --build mcp api      # MCP :8765, API :8000
uv sync && uv run pytest
```

### Run it

```bash
# CLI: generate, save drafts, approve in the terminal
uv run firstcut run briefs/masa-bakery.md            # --preview: no WordPress

# API: signed webhook -> SSE progress -> approval
uv run python scripts/send_webhook.py briefs/masa-bakery.md
curl -X POST localhost:8000/runs/<run_id>/approval -H 'Content-Type: application/json'      -d '{"approved": false, "feedback": {"contact": "Mention pre-orders close Thursday 6pm"}}'
curl -X POST localhost:8000/runs/<run_id>/approval -H 'Content-Type: application/json'      -d '{"approved": true}'
```

## WordPress MCP server

```bash
uv run python -m mcp_server                                # stdio
docker compose up -d mcp                                   # streamable HTTP on :8765/mcp
npx @modelcontextprotocol/inspector uv run python -m mcp_server   # debug UI
```

Claude Desktop: copy `mcp_server/claude_desktop_config.example.json` into
`%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`)
and set the repo path. Credentials are read from the repo's `.env`.
