"""DuckDB access. Standing rule 1: only the scheduler process opens this file
for writing. Everything else (dashboard) must pass read_only=True."""

import logging
import pathlib
from datetime import datetime, timezone

import duckdb

from shared.models import AIResult, NewsMessage

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bronze_news (
    article_id   TEXT NOT NULL,
    payload      JSON NOT NULL,          -- verbatim NewsMessage; duplicates allowed
    kafka_offset BIGINT NOT NULL,
    ingested_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS gold_ai_news (
    article_id   TEXT PRIMARY KEY,      -- shape = shared.models.AIResult
    summary      TEXT NOT NULL,
    importance   INTEGER NOT NULL,
    category     TEXT NOT NULL,
    keywords     TEXT[] NOT NULL,
    sentiment    TEXT NOT NULL,
    reason       TEXT NOT NULL,
    model        TEXT NOT NULL,
    processed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_at       TIMESTAMP NOT NULL,
    fetched      INTEGER,
    published    INTEGER,
    new_articles INTEGER,
    ai_calls     INTEGER,
    failures     INTEGER,
    duration_s   DOUBLE
);
"""


def connect(path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if not read_only:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path, read_only=read_only)
    if not read_only:
        conn.execute(SCHEMA)
    return conn


def insert_bronze(
    conn: duckdb.DuckDBPyConnection, batch: list[tuple[NewsMessage, int]]
) -> int:
    """Append (message, kafka_offset) pairs. Append-only by design — dedup is
    silver's job (dbt), not ingestion's."""
    now = datetime.now(timezone.utc)
    conn.executemany(
        "INSERT INTO bronze_news VALUES (?, ?, ?, ?)",
        [(m.article_id, m.model_dump_json(), offset, now) for m, offset in batch],
    )
    log.info("bronze insert rows=%d", len(batch))
    return len(batch)


def insert_ai_results(
    conn: duckdb.DuckDBPyConnection, results: list[tuple[AIResult, str]]
) -> int:
    """Upsert enrichments keyed on article_id — idempotent, so a re-processed
    article overwrites rather than duplicates.

    Deliberately two autocommit statements, not one transaction: DuckDB's ART
    index can't handle delete+reinsert of the same key within a transaction,
    and INSERT OR REPLACE rejects tables with LIST columns (keywords). Safe
    here because the scheduler is the single writer and an article lost
    between the two statements is simply re-queued by the anti-join.
    """
    now = datetime.now(timezone.utc)
    conn.executemany(
        "DELETE FROM gold_ai_news WHERE article_id = ?",
        [(r.article_id,) for r, _ in results],
    )
    conn.executemany(
        "INSERT INTO gold_ai_news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (r.article_id, r.summary, r.importance, r.category, r.keywords,
             r.sentiment, r.reason, model, now)
            for r, model in results
        ],
    )
    log.info("gold_ai_news upsert rows=%d", len(results))
    return len(results)
