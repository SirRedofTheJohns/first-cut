---
title: First Cut
emoji: 🥖
colorFrom: yellow
colorTo: red
sdk: gradio
sdk_version: 6.30.0
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: Agentic brief-to-website drafts with LangGraph
models:
  - Qwen/Qwen3-8B
---

# First Cut: live demo

Paste a client brief (or pick a sample). A LangGraph agent plans the sitemap, writes every page in parallel, reviews the copy and applies the client's brand colors and fonts taken from Figma.

This Space runs in **preview mode**. The full project, with WordPress drafts through its own MCP server, a signed webhook, SSE streaming and human approval, is on [GitHub](https://github.com/SirRedofTheJohns/first-cut).

Backends:
- **Gemini 3.5 Flash-Lite** (free tier), with automatic fallback to **Groq** (`gpt-oss-120b`).
- **Qwen3-8B** from the Hugging Face Hub on **ZeroGPU**. It uses your daily GPU quota, so sign in to Hugging Face to get more of it.

Please use fictional briefs: free-tier API providers may use inputs to improve their models.
