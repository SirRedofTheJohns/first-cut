# Demo video script (2 minutes)

**Goal:** show one real run end to end: brief in, branded WordPress drafts, a human edit, live pages. Then show it's built to production standards. Record at 1080p; keep the terminal font large.

**Before recording:**
- `docker compose up -d` (WordPress, MCP, API).
- Clear old pages: `docker compose run --rm --entrypoint sh wpcli -c 'wp post delete $(wp post list --post_type=page --format=ids) --force'`.
- Open these tabs: the Google Doc brief, the Figma file, WordPress admin → Pages, the GitHub repo, the Hugging Face Space.
- Use Gemini Flash-Lite so the run takes ~30 s on camera: `LLM_PROVIDER=google_genai`, `LLM_MODEL=gemini-3.5-flash-lite`.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:12 | Google Doc brief, then the Figma file | "Every agency project starts the same way: a client brief and a brand file. First Cut turns these two into a reviewed WordPress draft, and nothing goes live until a person approves it." |
| 0:12–0:30 | Terminal: `scripts/send_webhook.py --gdoc … --figma …`; the SSE events scroll | "A signed webhook starts the run. The API checks an HMAC signature, then streams progress over server-sent events: it reads the Doc through a Google service account, pulls the brand styles from Figma, and plans the sitemap." |
| 0:30–0:50 | Events: parallel `write_page` lines, `review`, `publish_drafts` | "LangGraph writes every page in parallel, a reviewer node checks the copy against the brief, and a tool-calling agent saves the drafts to WordPress. It never calls WordPress directly: it goes through my own MCP server, the same one Claude Desktop can use." |
| 0:50–1:05 | WordPress admin → Pages (all Drafts); open Home preview: terracotta buttons, Playfair headings | "Here are the drafts, with the client's colors and fonts from Figma, in normal editable blocks." |
| 1:05–1:25 | `curl … /approval` with feedback for `/contact`; events show only `write_page /contact`; refresh the page | "The run is paused with LangGraph's interrupt and checkpointed in SQLite, so it survives a restart. I ask for a change on one page, and only that page is rewritten." |
| 1:25–1:35 | `curl … {"approved": true}`; Pages list flips to Published | "Approve, and the pages go live." |
| 1:35–1:50 | GitHub: README diagram, then `docs/DECISIONS.md` scrolling | "The model layer switches providers with environment variables: local Qwen from Hugging Face, Gemini, Groq, Claude or OpenAI. Every non-obvious choice is documented, including what broke during testing and how I measured the fix." |
| 1:50–2:00 | Hugging Face Space generating a site | "You can try the preview yourself on Hugging Face. Thanks for watching." |

**If something fails on camera:** say so. The fallback to Groq or a validation retry is a feature worth showing.
