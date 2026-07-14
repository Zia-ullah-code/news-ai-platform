"""Fetch RSS feeds and map entries to NewsMessage.

The fetch/map functions here are pure and importable: the Lambda handler (Day 7)
and the local dev producer (Day 2) both reuse them; this module's __main__ just
prints to console (Day 1 deliverable).
"""

import calendar
import html
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

from shared.config import get_settings
from shared.models import NewsMessage
from shared.utils import mint_article_id, retry_network, setup_logging

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
USER_AGENT = "news-ai-platform/0.1 (+portfolio demo)"


@retry_network
def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def _parse_published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def _source_from(feed_url: str) -> str:
    return urlparse(feed_url).netloc.removeprefix("www.").removeprefix("feeds.")


def fetch_feed(feed_url: str) -> list[NewsMessage]:
    """Fetch one feed and return its entries as NewsMessage objects.

    Entries that can't be mapped are logged and skipped — one bad entry must not
    drop the whole feed.
    """
    parsed = feedparser.parse(_download(feed_url))
    source = _source_from(feed_url)
    messages: list[NewsMessage] = []
    for entry in parsed.entries:
        try:
            published = _parse_published(entry)
            messages.append(
                NewsMessage(
                    article_id=mint_article_id(
                        guid=entry.get("id"),
                        link=entry.get("link"),
                        source=source,
                        published=str(published or ""),
                    ),
                    title=html.unescape(entry.get("title", "")).strip(),
                    url=entry.get("link", ""),
                    source=source,
                    published=published,
                    content=html.unescape(entry.get("summary", "")),
                )
            )
        except Exception:
            log.exception("skipping unparseable entry from %s", source)
    return messages


def fetch_all(feed_urls: list[str]) -> list[NewsMessage]:
    """Fetch every configured feed. A feed that fails after retries is logged
    and skipped — partial data beats no data."""
    messages: list[NewsMessage] = []
    for url in feed_urls:
        try:
            batch = fetch_feed(url)
            log.info("fetched feed=%s articles=%d", url, len(batch))
            messages.extend(batch)
        except Exception:
            log.exception("feed failed after retries: %s", url)
    return messages


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    messages = fetch_all(settings.feed_urls)

    for msg in sorted(messages, key=lambda m: m.published or m.fetched_at, reverse=True)[:15]:
        ts = msg.published.strftime("%Y-%m-%d %H:%M") if msg.published else "????-??-?? --:--"
        print(f"[{ts}] ({msg.source}) {msg.title}")
        print(f"    id={msg.article_id[:12]}… {msg.url}")

    log.info("cycle summary fetched=%d feeds=%d", len(messages), len(settings.feed_urls))


if __name__ == "__main__":
    main()
