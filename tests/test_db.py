"""Storage-layer tests against a throwaway DuckDB file."""

from services.scheduler import db
from shared.models import AIResult, NewsMessage


def _msg(i: int) -> NewsMessage:
    return NewsMessage(article_id=f"id-{i}", title=f"t{i}", url=f"https://x/{i}", source="test")


def _ai(article_id: str) -> AIResult:
    return AIResult(article_id=article_id, summary="s", importance=5, category="tech",
                    keywords=["k1", "k2"], sentiment="neutral", reason="r")


def test_connect_creates_schema(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"bronze_news", "gold_ai_news", "pipeline_runs"} <= tables


def test_bronze_is_append_only_and_allows_duplicates(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.insert_bronze(conn, [(_msg(1), 0), (_msg(1), 1), (_msg(2), 2)])
    total, distinct = conn.execute(
        "SELECT count(*), count(DISTINCT article_id) FROM bronze_news").fetchone()
    assert (total, distinct) == (3, 2)  # same article twice is fine in bronze


def test_bronze_payload_roundtrips(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.insert_bronze(conn, [(_msg(7), 42)])
    title, offset = conn.execute(
        "SELECT payload->>'title', kafka_offset FROM bronze_news").fetchone()
    assert (title, offset) == ("t7", 42)


def test_ai_upsert_is_idempotent(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.insert_ai_results(conn, [(_ai("a"), "model-1")])
    db.insert_ai_results(conn, [(_ai("a"), "model-2")])  # reprocess same article
    rows = conn.execute("SELECT article_id, model FROM gold_ai_news").fetchall()
    assert rows == [("a", "model-2")]  # replaced, not duplicated


def test_ai_keywords_list_roundtrips(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.insert_ai_results(conn, [(_ai("a"), "m")])
    assert conn.execute("SELECT keywords FROM gold_ai_news").fetchone()[0] == ["k1", "k2"]
