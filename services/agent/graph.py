"""LangGraph agent: article -> summary/importance/category/keywords/sentiment.

Graph (design.md §6):

    prepare -> call_llm -> route ---- done ----> END
                  ^            \
                  +--- retry ---+   (next attempt rotates to the next provider;
                                     max MAX_ATTEMPTS calls per article)

Structured output is enforced by the provider (with_structured_output on the
AIPayload schema); a response that can't validate raises inside call_llm and
becomes a retry. article_id never touches the LLM — we attach it ourselves.
"""

import logging
import time
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from shared.config import Settings, get_settings
from shared.models import AIResult

from .providers import build_llms, enable_tracing

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

CATEGORIES = ("world", "politics", "business", "tech", "science", "health",
              "sports", "entertainment", "other")

PROMPT = """You are a news analyst for a real-time alert system.
Analyze the article below and respond with the structured fields requested.

Guidelines:
- summary: 2-3 plain sentences, factual, no hype.
- importance: 1-10 for a general news audience. 8+ means most people should
  hear about this today (major breaking events); 5-7 notable; 1-4 routine.
- reason: one sentence justifying the importance score.
- keywords: 3-6 lowercase topical keywords.

Source: {source}
Title: {title}

{content}"""


class AIPayload(BaseModel):
    """What the LLM must produce. AIResult = article_id + this."""

    summary: str = Field(description="2-3 sentence factual summary")
    importance: int = Field(ge=1, le=10, description="1-10 importance for a general audience")
    category: Literal["world", "politics", "business", "tech", "science", "health",
                      "sports", "entertainment", "other"]
    keywords: list[str] = Field(min_length=1, max_length=8)
    sentiment: Literal["positive", "neutral", "negative"]
    reason: str = Field(description="one sentence justifying the importance score")


class AgentState(TypedDict, total=False):
    article: dict
    prompt: str
    attempt: int
    payload: Optional[AIPayload]
    model_used: Optional[str]
    error: Optional[str]


def build_graph(llms: list[tuple[str, object]]):
    structured = [(label, llm.with_structured_output(AIPayload)) for label, llm in llms]

    def prepare(state: AgentState) -> AgentState:
        a = state["article"]
        return {
            "prompt": PROMPT.format(
                source=a.get("source", "unknown"),
                title=a.get("title", ""),
                content=(a.get("content_clean") or "")[:1500],
            ),
            "attempt": 0,
        }

    def call_llm(state: AgentState) -> AgentState:
        label, llm = structured[state["attempt"] % len(structured)]
        try:
            payload = llm.invoke(state["prompt"])
            return {"payload": payload, "model_used": label, "attempt": state["attempt"] + 1}
        except Exception as exc:  # provider error or schema-validation failure
            log.warning("llm attempt=%d model=%s failed: %s", state["attempt"], label, exc)
            return {"error": str(exc), "attempt": state["attempt"] + 1}

    def route(state: AgentState) -> str:
        if state.get("payload") is not None or state["attempt"] >= MAX_ATTEMPTS:
            return "done"
        return "retry"

    g = StateGraph(AgentState)
    g.add_node("prepare", prepare)
    g.add_node("call_llm", call_llm)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "call_llm")
    g.add_conditional_edges("call_llm", route, {"done": END, "retry": "call_llm"})
    return g.compile()


class Enricher:
    """Process-lifetime wrapper: build providers + graph once, reuse per article."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        enable_tracing(self.settings)
        self.graph = build_graph(build_llms(self.settings))

    def enrich(self, article: dict) -> tuple[Optional[AIResult], Optional[str]]:
        """Returns (result, model_label); (None, None) when all attempts failed."""
        final: AgentState = self.graph.invoke(
            {"article": article},
            config={"run_name": "enrich_article",
                    "tags": [f"article:{article['article_id'][:12]}"]},
        )
        payload = final.get("payload")
        if payload is None:
            log.error("enrichment failed article_id=%s error=%s",
                      article["article_id"][:12], final.get("error"))
            return None, None
        return (
            AIResult(article_id=article["article_id"], **payload.model_dump()),
            final.get("model_used"),
        )

    def enrich_batch(self, articles: list[dict]) -> list[tuple[AIResult, str]]:
        out: list[tuple[AIResult, str]] = []
        for i, article in enumerate(articles):
            if i:
                time.sleep(self.settings.ai_call_interval_s)  # stay under free-tier RPM
            result, model = self.enrich(article)
            if result is not None:
                out.append((result, model))
        return out
