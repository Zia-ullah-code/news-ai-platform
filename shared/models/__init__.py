"""Message and record schemas — the single source of truth (standing rule 3).
Every component imports these; docs/design.md references them by name."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class NewsMessage(BaseModel):
    """One article as it travels: Lambda/producer -> Kafka `news.raw` -> bronze.

    `article_id` is minted at the producer (shared.utils.mint_article_id) and is
    the identity of the article everywhere downstream (standing rule 2).
    """

    article_id: str
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    content: str = ""  # raw summary/description from the feed, uncleaned
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIResult(BaseModel):
    """LangGraph agent output, validated before writing gold_ai_news (Day 4)."""

    article_id: str
    summary: str
    importance: int = Field(ge=1, le=10)
    category: str
    keywords: list[str] = Field(default_factory=list)
    sentiment: str
    reason: str
