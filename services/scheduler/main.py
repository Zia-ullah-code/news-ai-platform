"""The scheduler: run_cycle() every CYCLE_INTERVAL_S seconds.

Stages (design.md §5), each an explicit function, run strictly in sequence:
  1. consume news.raw -> bronze_news
  2. dbt build       -> silver_news, gold_news (+ tests)
  3. AI enrichment   -> gold_ai_news            (Day 4; placeholder here)
  4. record pipeline_runs row + summary log line

Single-writer discipline: every stage opens its own DuckDB connection and
closes it before the next stage starts; dbt (a subprocess) therefore never
overlaps with this process holding the file. A stage failure aborts the cycle
after logging — every stage is idempotent (offsets / dedup / anti-join), so
the next cycle simply retries.

Run: python -m services.scheduler.main [--once]
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from shared.config import Settings, get_settings
from shared.utils import setup_logging

from . import db
from .consume import consume_to_bronze, make_consumer

log = logging.getLogger(__name__)

DBT_ARGS = ["build", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"]


def _dbt_executable() -> str:
    venv_dbt = Path(sys.executable).with_name("dbt")
    return str(venv_dbt) if venv_dbt.exists() else "dbt"


def _table_count(settings: Settings, table: str) -> int:
    try:
        conn = duckdb.connect(settings.duckdb_path, read_only=True)
        try:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()
    except duckdb.Error:
        return 0  # table doesn't exist before the first dbt build


def stage_consume(settings: Settings) -> int:
    consumer = make_consumer(settings.kafka_bootstrap)
    conn = db.connect(settings.duckdb_path)
    try:
        return consume_to_bronze(consumer, conn)
    finally:
        consumer.close()
        conn.close()


def stage_dbt() -> None:
    result = subprocess.run(
        [_dbt_executable(), *DBT_ARGS], capture_output=True, text=True, timeout=600
    )
    if result.returncode != 0:
        log.error("dbt build failed:\n%s", result.stdout[-3000:])
        raise RuntimeError("dbt build failed")
    log.info("dbt build ok")


def stage_ai(settings: Settings) -> int:
    """Day 4: anti-join silver vs gold_ai_news -> LangGraph -> write results."""
    return 0


def run_cycle(settings: Settings) -> None:
    start = time.monotonic()
    consumed = new_articles = ai_calls = failures = 0
    silver_before = _table_count(settings, "silver_news")

    try:
        consumed = stage_consume(settings)
        stage_dbt()
        new_articles = _table_count(settings, "silver_news") - silver_before
        ai_calls = stage_ai(settings)
    except Exception:
        failures = 1
        log.exception("cycle aborted at failed stage; next cycle will retry")

    duration = time.monotonic() - start
    conn = db.connect(settings.duckdb_path)
    try:
        conn.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc), consumed, consumed, new_articles,
             ai_calls, failures, round(duration, 2)),
        )
    finally:
        conn.close()

    # Standing rule 6: one summary line per cycle.
    log.info(
        "cycle summary fetched=%d published=%d new=%d ai_calls=%d failures=%d duration=%.1fs",
        consumed, consumed, new_articles, ai_calls, failures, duration,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)

    if args.once:
        run_cycle(settings)
        return

    log.info("scheduler started interval=%ds", settings.cycle_interval_s)
    while True:
        cycle_start = time.monotonic()
        run_cycle(settings)
        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, settings.cycle_interval_s - elapsed))


if __name__ == "__main__":
    main()
