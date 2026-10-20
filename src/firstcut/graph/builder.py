from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from firstcut.graph import nodes
from firstcut.graph.publish import finalize, publish_drafts
from firstcut.graph.state import Deps, SiteState
from firstcut.structured import StructuredOutputError


def build_graph(checkpointer=None):
    """`checkpointer` is required for runs that reach WordPress: approval uses `interrupt`."""
    builder = StateGraph(SiteState, context_schema=Deps)
    builder.add_node("load_brief", nodes.load_brief)
    builder.add_node("load_style_guide", nodes.load_style_guide)
    # LLM nodes already retry invalid output inside `structured_call`; if a node still gives
    # up, LangGraph re-runs it once from scratch instead of failing the whole run.
    llm_retry = RetryPolicy(max_attempts=2, retry_on=StructuredOutputError)
    builder.add_node("plan_sitemap", nodes.plan_sitemap, retry_policy=llm_retry)
    builder.add_node("write_page", nodes.write_page, retry_policy=llm_retry)
    builder.add_node("review", nodes.review, retry_policy=llm_retry)
    builder.add_node("publish_drafts", publish_drafts)
    builder.add_node("human_approval", nodes.human_approval)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "load_brief")
    builder.add_edge("load_brief", "load_style_guide")
    builder.add_edge("load_style_guide", "plan_sitemap")
    # One parallel `write_page` run per planned page (map step).
    builder.add_conditional_edges("plan_sitemap", nodes.fan_out_writers, ["write_page"])
    # `review` runs once, after every writer in the superstep has finished (reduce step).
    builder.add_edge("write_page", "review")
    builder.add_conditional_edges(
        "review", nodes.route_after_review, ["write_page", "publish_drafts", END]
    )
    # Human in the loop: approve -> finalize; feedback -> rewrite those pages; reject -> end.
    # Routing happens inside `human_approval` via `Command(goto=...)`.
    builder.add_edge("publish_drafts", "human_approval")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
