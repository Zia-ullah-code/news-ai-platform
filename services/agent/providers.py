"""Provider interface: chat models built from whichever API keys exist.

Preference order Gemini -> Groq: gemini-2.5-flash is the stronger judge, and
Groq's much larger free daily quota (~4x) makes it the right failover when
Gemini's 250/day runs out. Adding a provider = adding a key to .env."""

import logging
import os

from shared.config import Settings

log = logging.getLogger(__name__)


def enable_tracing(settings: Settings) -> None:
    """Export LangSmith env vars (LangChain reads os.environ, not our Settings).
    Both the modern LANGSMITH_* and legacy LANGCHAIN_* names, to be safe."""
    if settings.langchain_tracing_v2.lower() != "true" or not settings.langchain_api_key:
        return
    for prefix in ("LANGSMITH", "LANGCHAIN"):
        os.environ.setdefault(f"{prefix}_TRACING", "true")
        os.environ.setdefault(f"{prefix}_API_KEY", settings.langchain_api_key)
        os.environ.setdefault(f"{prefix}_PROJECT", settings.langchain_project)
        os.environ.setdefault(f"{prefix}_ENDPOINT", settings.langchain_endpoint)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    log.info("langsmith tracing enabled project=%s", settings.langchain_project)


def build_llms(settings: Settings) -> list[tuple[str, object]]:
    """Return [(label, chat_model), ...] for every configured provider."""
    llms: list[tuple[str, object]] = []
    if settings.gemini_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llms.append(
            (
                f"gemini/{settings.gemini_model}",
                ChatGoogleGenerativeAI(model=settings.gemini_model,
                                       google_api_key=settings.gemini_api_key,
                                       temperature=0.2, max_retries=2),
            )
        )
    if settings.groq_api_key:
        from langchain_groq import ChatGroq

        llms.append(
            (
                f"groq/{settings.groq_model}",
                ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key,
                         temperature=0.2, max_retries=2),
            )
        )
    if not llms:
        raise RuntimeError("no LLM provider configured — set GROQ_API_KEY or GEMINI_API_KEY")
    return llms
