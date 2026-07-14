"""AWS Lambda entrypoint: fetch RSS -> POST to the EC2 ingest endpoint.

The whole function is a composition of code proven earlier in the pipeline:
fetch_all (Day 1) + publish_http (Day 2, the pandaproxy contract of
design.md §3). EventBridge invokes this every 5 minutes; it is stateless and
exits — dedup is downstream's job (silver), so re-sending articles is safe.

Configuration comes from Lambda environment variables, read by the same
shared.config.Settings as every other component:
  NEWS_FEEDS, PANDAPROXY_URL (https://<domain>/produce), INGEST_API_KEY,
  KAFKA_TOPIC, LOG_LEVEL.

Packaged by scripts/build_lambda.sh with this file at the zip root
(handler.lambda_handler) plus shared/ and services/.
"""

import logging

from shared.config import get_settings
from shared.utils import setup_logging

from services.producer.fetch import fetch_all
from services.producer.publish import publish_http

log = logging.getLogger(__name__)
_configured = False


def lambda_handler(event, context):
    global _configured
    settings = get_settings()
    if not _configured:  # warm invocations reuse the runtime
        setup_logging(settings.log_level)
        _configured = True

    messages = fetch_all(settings.feed_urls)
    published = publish_http(
        messages, settings.pandaproxy_url, settings.kafka_topic, settings.ingest_api_key
    )
    log.info("cycle summary fetched=%d published=%d via=lambda", len(messages), published)
    return {"fetched": len(messages), "published": published}
