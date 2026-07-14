"""Cross-cutting helpers: logging setup, article identity, network retry policy."""

import hashlib
import logging
import sys

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,  # AWS Lambda pre-installs a WARNING-level handler that
    )                # basicConfig would otherwise silently defer to


def mint_article_id(guid: str | None, link: str | None, source: str, published: str) -> str:
    """Deterministic article identity (standing rule 2).

    Identity source: feed GUID -> link URL -> composite of source+link+published.
    Never the title — publishers edit titles after publication.
    The chosen identity string is hashed so IDs are uniform, key-safe hex.
    """
    identity = guid or link or f"{source}|{link}|{published}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


# Standing rule 4: retries live at the network boundary only.
retry_network = retry(
    retry=retry_if_exception_type((requests.RequestException, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
