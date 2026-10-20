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
