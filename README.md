# AI-Powered News Alert System

RSS news → AWS Lambda (Terraform) → Redpanda → dbt + DuckDB → LangGraph agent
(importance + summary via Groq/Gemini) → Streamlit dashboard. LangSmith tracing.

**Status: Day 6 — deployed to AWS ✅: Terraform-managed EC2, live at https://zia-news.duckdns.org (dashboard behind basic auth).** See
[PLAN.md](PLAN.md) for the full build plan and [docs/design.md](docs/design.md)
for contracts.

## Quickstart (current state)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

docker compose up -d                      # single-node Redpanda + pandaproxy
python -m services.producer.fetch         # RSS -> console (no Kafka needed)
python -m services.producer.publish       # RSS -> news.raw (add --http for the
                                          #   pandaproxy path the Lambda uses)
python -m services.scheduler.main --once  # one full cycle: consume -> dbt -> AI -> metrics
python -m services.scheduler.main          # the real thing: a cycle every 5 min
streamlit run services/dashboard/app.py    # dashboard at http://localhost:8501
pytest tests/                             # contract tests
```
