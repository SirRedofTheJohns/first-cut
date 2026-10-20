"""First Cut demo (Hugging Face Space): brief in, sitemap and branded page copy out.

Preview mode: the same LangGraph agent as the full project (plan -> parallel writers ->
reviewer), without WordPress or the approval step. Two backends:
- Qwen3-8B from the Hugging Face Hub on ZeroGPU (uses the visitor's free GPU quota);
- Gemini on its free tier, with Groq as automatic fallback.
"""

import html
import json
import os
import time
from pathlib import Path

import gradio as gr

from firstcut.config import get_settings
from firstcut.graph import Deps, build_graph
from firstcut.integrations.figma import extract_style_guide
from firstcut.llm import get_chat_model, get_fallback_model
from firstcut.render import render_blocks

HERE = Path(__file__).parent
SAMPLES = {
    "Masa Bakery (sourdough bakery, Austin)": "masa-bakery.md",
    "Northline Physical Therapy (clinic, Denver)": "northline-physio.md",
    "Ledgerly (SaaS for freelancers)": "ledgerly-saas.md",
}
BRAND = extract_style_guide(json.loads((HERE / "brand_fixture.json").read_text(encoding="utf-8")))
MAX_BRIEF_CHARS = 6000

ZEROGPU = os.getenv("FIRSTCUT_ENABLE_ZEROGPU") == "1"
if ZEROGPU:
    from zerogpu import ChatZeroGPU  # loads Qwen3-8B at startup, as ZeroGPU expects

GEMINI = "Gemini 3.5 Flash-Lite (free tier, Groq fallback)"
QWEN = "Qwen3-8B on ZeroGPU (Hugging Face, uses your GPU quota)"
BACKENDS = [GEMINI, QWEN] if ZEROGPU else [GEMINI]
graph = build_graph()  # preview mode: no checkpointer, no WordPress


def load_sample(name: str) -> str:
    return (HERE / "briefs" / SAMPLES[name]).read_text(encoding="utf-8")


def generate(brief: str, use_brand: bool, backend: str):
    brief = (brief or "").strip()
    if len(brief) < 40:
        raise gr.Error("Paste a brief (at least a few sentences) or pick a sample.")
    if len(brief) > MAX_BRIEF_CHARS:
        raise gr.Error(f"Briefs are limited to {MAX_BRIEF_CHARS} characters in the demo.")

    settings = get_settings()
    if backend == QWEN:
        # Few LLM calls, one at a time, to fit a visitor's daily ZeroGPU quota.
        deps = Deps(llm=ChatZeroGPU(), max_pages=3, max_revisions=0)
        config = {"max_concurrency": 1}
    else:
        deps = Deps(llm=get_chat_model(settings), fallback_llm=get_fallback_model(settings))
        config = {}

    graph_input = {"brief": brief} | ({"style_guide": BRAND} if use_brand else {})
    log, state, started = [], {}, time.perf_counter()
    for mode, chunk in graph.stream(
        graph_input, config, context=deps, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            state = chunk
            continue
        for node, update in chunk.items():
            log.append(f"`{time.perf_counter() - started:5.1f}s` ✓ **{node}** {_detail(update)}")
        yield "\n\n".join(log), _sitemap_md(state), _preview(state), ""
    log.append(f"Done in {time.perf_counter() - started:.0f}s.")
    yield "\n\n".join(log), _sitemap_md(state), _preview(state), _review_md(state)


def _detail(update) -> str:
    if not isinstance(update, dict):
        return ""
    if "pages" in update:
        return " ".join(f"`/{slug}`" for slug in update["pages"])
    if "sitemap" in update:
        return f"{len(update['sitemap'].pages)} pages planned"
    if "review" in update:
        return (
            "approved" if update["review"].approved else f"{len(update['review'].issues)} issue(s)"
        )
    return ""


def _sitemap_md(state: dict) -> str:
    sitemap = state.get("sitemap")
    if not sitemap:
        return "*Planning…*"
    rows = "\n".join(f"| {p.title} | `/{p.slug}` | {p.purpose} |" for p in sitemap.pages)
    return (
        f"### {sitemap.site_name}\n*{sitemap.tagline}*\n\n"
        f"**Audience:** {sitemap.audience}  \n**Tone:** {sitemap.tone}\n\n"
        f"| Page | Slug | Purpose |\n|---|---|---|\n{rows}"
    )


def _preview(state: dict) -> str:
    pages = state.get("pages") or {}
    order = [p.slug for p in state["sitemap"].pages] if state.get("sitemap") else list(pages)
    cards = []
    for slug in order:
        if slug not in pages:
            continue
        page = pages[slug]
        cards.append(
            '<div class="fc-card">'
            f'<div class="fc-meta">/{html.escape(slug)} · {html.escape(page.meta_description)}</div>'
            f"<h1>{html.escape(page.title)}</h1>"
            f"{render_blocks(page, state.get('style_guide'))}</div>"
        )
    return "".join(cards) or "<p>Pages appear here as they are written.</p>"


def _review_md(state: dict) -> str:
    review = state.get("review")
    if not review:
        return ""
    if review.approved and not review.issues:
        return "**AI review:** approved. In the full product, a human approves before publishing."
    issues = "\n".join(f"- `/{i.slug}`: {i.problem}" for i in review.issues)
    return f"**AI review — open issues for the human editor:**\n{issues}"


CSS = """
.fc-card {background:#fff;color:#1c1917;border-radius:12px;padding:24px 28px;margin:0 0 16px;
          box-shadow:0 1px 3px rgba(0,0,0,.15)}
.fc-card h1 {font-size:1.6rem;margin:4px 0 8px}
.fc-meta {font-size:.8rem;color:#78716c}
.fc-card .wp-block-button__link {display:inline-block;padding:10px 18px;border-radius:8px;
          text-decoration:none;background:#1c1917;color:#fff}
"""

with gr.Blocks(title="First Cut: brief to website draft") as demo:
    gr.Markdown(
        "# First Cut\n"
        "An agentic workflow that turns a client brief into a website draft: a sitemap, "
        "copy for every page, and the client's brand from Figma. Built with **LangGraph**. "
        "This demo is *preview mode*; the full project also saves drafts to WordPress through "
        "its own **MCP server** and waits for **human approval** before publishing. "
        "[Source code](https://github.com/SirRedofTheJohns/first-cut)"
    )
    with gr.Row():
        with gr.Column(scale=2):
            sample = gr.Dropdown(list(SAMPLES), label="Sample brief", value=list(SAMPLES)[0])
            brief = gr.Textbox(label="Client brief", lines=14, value=load_sample(list(SAMPLES)[0]))
            use_brand = gr.Checkbox(
                label="Apply the sample Figma brand (Masa Bakery: colors + fonts)", value=True
            )
            backend = gr.Radio(BACKENDS, label="LLM backend", value=BACKENDS[0])
            run = gr.Button("Generate site draft", variant="primary")
            log = gr.Markdown(label="Progress")
        with gr.Column(scale=3):
            sitemap = gr.Markdown("*The sitemap appears here.*")
            review = gr.Markdown()
            preview = gr.HTML()

    sample.change(load_sample, sample, brief)
    run.click(
        generate,
        [brief, use_brand, backend],
        [log, sitemap, preview, review],
        concurrency_limit=2,
    )

if __name__ == "__main__":
    demo.queue(max_size=20).launch(css=CSS)
