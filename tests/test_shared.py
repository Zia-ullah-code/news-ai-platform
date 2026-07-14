"""Contract tests for shared/ — the pieces every service depends on."""

from datetime import datetime, timezone

from shared.models import NewsMessage
from shared.utils import mint_article_id


class TestMintArticleId:
    def test_guid_wins_over_link(self):
        a = mint_article_id(guid="guid-1", link="https://x/a", source="s", published="p")
        b = mint_article_id(guid="guid-1", link="https://x/DIFFERENT", source="s", published="p")
        assert a == b

    def test_link_fallback_when_no_guid(self):
        a = mint_article_id(guid=None, link="https://x/a", source="s", published="p1")
        b = mint_article_id(guid=None, link="https://x/a", source="s", published="p2")
        assert a == b

    def test_composite_fallback_when_neither(self):
        a = mint_article_id(guid=None, link=None, source="s", published="2026-07-14")
        b = mint_article_id(guid=None, link=None, source="s", published="2026-07-15")
        assert a != b

    def test_deterministic_hex(self):
        a = mint_article_id(guid="g", link=None, source="s", published="p")
        assert a == mint_article_id(guid="g", link=None, source="s", published="p")
        assert len(a) == 64
        int(a, 16)  # valid hex


class TestNewsMessage:
    def test_roundtrip_json(self):
        msg = NewsMessage(
            article_id="a" * 64,
            title="t",
            url="https://x/a",
            source="x",
            published=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        assert NewsMessage.model_validate_json(msg.model_dump_json()) == msg

    def test_fetched_at_defaults_utc(self):
        msg = NewsMessage(article_id="a", title="t", url="u", source="s")
        assert msg.fetched_at.tzinfo is not None
