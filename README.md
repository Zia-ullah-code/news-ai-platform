# AI-Powered News Alert System

RSS news → AWS Lambda (Terraform) → Redpanda → dbt + DuckDB → LangGraph agent
(importance + summary via Groq/Gemini) → Streamlit dashboard. LangSmith tracing.

**Status: Day 1 — foundations + RSS ingestion.** See [PLAN.md](PLAN.md) for the
full build plan and [docs/design.md](docs/design.md) for contracts.

## Quickstart (current state)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m services.producer.fetch     # fetch latest articles, print to console
```
