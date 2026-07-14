"""Publish fetched articles to Redpanda `news.raw`.

Two paths, deliberately:
- publish_kafka: native Kafka protocol — the local dev producer's default.
- publish_http: pandaproxy REST — byte-for-byte what the Lambda does on Day 7,
  kept here so the ingest contract (docs/design.md §3) is exercised from Day 2.

Run: python -m services.producer.publish [--http]
"""

import argparse
import logging

import requests

from shared.config import get_settings
from shared.models import NewsMessage
from shared.utils import retry_network, setup_logging

from .fetch import fetch_all

log = logging.getLogger(__name__)


def publish_kafka(messages: list[NewsMessage], bootstrap: str, topic: str) -> int:
    # imported here, not module-top: the Lambda package ships without the
    # Kafka client on purpose (it only ever uses publish_http)
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": bootstrap})
    for msg in messages:
        producer.produce(topic, key=msg.article_id, value=msg.model_dump_json())
    remaining = producer.flush(timeout=30)
    if remaining:
        raise RuntimeError(f"{remaining} messages not delivered")
    return len(messages)


@retry_network
def publish_http(messages: list[NewsMessage], base_url: str, topic: str, api_key: str) -> int:
    """POST to pandaproxy — the Lambda ingest path (design.md §3). Locally the
    Authorization header is ignored; in the cloud Caddy enforces it."""
    resp = requests.post(
        f"{base_url}/topics/{topic}",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "records": [
                {"key": m.article_id, "value": m.model_dump(mode="json")} for m in messages
            ]
        },
        timeout=30,
    )
    resp.raise_for_status()
    return len(messages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="publish via pandaproxy REST")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)

    messages = fetch_all(settings.feed_urls)
    if args.http:
        n = publish_http(messages, settings.pandaproxy_url, settings.kafka_topic, settings.ingest_api_key)
    else:
        n = publish_kafka(messages, settings.kafka_bootstrap, settings.kafka_topic)
    log.info("cycle summary fetched=%d published=%d via=%s", len(messages), n, "http" if args.http else "kafka")


if __name__ == "__main__":
    main()
