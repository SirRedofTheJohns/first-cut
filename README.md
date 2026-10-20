# First Cut

> Turns a client brief into a reviewed WordPress site draft: sitemap, page copy and style guide, with a human approval step before anything goes live.

🚧 Work in progress. The full README (architecture, demo, provider switching) lands in phase 6.

## Quick start (local)

```bash
cp .env.example .env
docker compose up -d          # WordPress at http://localhost:8080
docker compose logs wpcli     # copy WP_APP_PASSWORD into .env
uv sync
uv run pytest
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
