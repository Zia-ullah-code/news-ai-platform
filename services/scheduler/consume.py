"""Consume news.raw -> bronze_news.

Importable module, not a resident service: on Day 3 this becomes stage 1 of the
scheduler's run_cycle(). Offsets are committed only AFTER the DuckDB write
succeeds — a crash mid-batch re-delivers, and bronze tolerates duplicates.
Messages that fail schema validation go to the news.dead DLQ with error
context instead of being silently dropped.

Run manually for testing: python -m services.scheduler.consume
"""

import json
import logging
from datetime import datetime, timezone

from confluent_kafka import Consumer, KafkaError, Producer

from shared.config import get_settings
from shared.models import NewsMessage
from shared.utils import setup_logging

from . import db

log = logging.getLogger(__name__)

POLL_TIMEOUT_S = 5.0  # one quiet poll = topic drained; the 5-min cycle re-runs anyway


def make_consumer(bootstrap: str, group: str = "scheduler") -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # commit manually, after the write
        }
    )


def _dead_letter(producer: Producer, msg, error: Exception) -> None:
    """Route a poison message to news.dead, wrapped with error context."""
    producer.produce(
        "news.dead",
        key=msg.key(),
        value=json.dumps(
            {
                "error": str(error),
                "source_topic": msg.topic(),
                "source_offset": msg.offset(),
                "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
                "original_value": (msg.value() or b"").decode("utf-8", errors="replace"),
            }
        ),
    )


def consume_to_bronze(consumer: Consumer, conn) -> int:
    """Drain currently-available messages into bronze_news. Returns row count."""
    settings = get_settings()
    consumer.subscribe([settings.kafka_topic])
    dlq = Producer({"bootstrap.servers": settings.kafka_bootstrap})
    batch: list[tuple[NewsMessage, int]] = []
    dead = 0
    while True:
        msg = consumer.poll(POLL_TIMEOUT_S)
        if msg is None:
            break
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                break
            log.error("kafka error: %s", msg.error())
            continue
        try:
            batch.append((NewsMessage.model_validate_json(msg.value()), msg.offset()))
        except Exception as exc:
            log.warning("dead-lettering unparseable message at offset=%s: %s", msg.offset(), exc)
            _dead_letter(dlq, msg, exc)
            dead += 1

    if dead:
        dlq.flush(timeout=10)
        log.info("dead-lettered %d message(s) to news.dead", dead)
    if batch:
        db.insert_bronze(conn, batch)
    if batch or dead:
        consumer.commit(asynchronous=False)
    return len(batch)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    consumer = make_consumer(settings.kafka_bootstrap)
    conn = db.connect(settings.duckdb_path)
    try:
        n = consume_to_bronze(consumer, conn)
        total = conn.execute("SELECT count(*) FROM bronze_news").fetchone()[0]
        log.info("consumed=%d bronze_total=%d", n, total)
    finally:
        consumer.close()
        conn.close()


if __name__ == "__main__":
    main()
