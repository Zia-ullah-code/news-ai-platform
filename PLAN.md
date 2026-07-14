# AI-Powered News Alert System — Final Implementation Plan

**Target: working end-to-end system in 7–10 working days.**
Original spec: Lambda (Terraform) scrapes news → Redpanda/Kafka → dbt + DuckDB → LangGraph
agent judges importance + summarizes → Streamlit dashboard, with LangSmith observability.

---

## Locked decisions (from plan review)

| Decision | Choice | Why |
|---|---|---|
| AWS account model | Credit-based Free Plan ($100 + up to $100 activities, 6-month expiry) | Account created July 2026; old 12-month free tier no longer exists |
| EC2 instance | **t4g.small (ARM, 2 GB), on-demand**, `cpu_credits = "standard"` | Whole stack fits in 2 GB; ~$12/mo from credits; standard mode prevents surprise burst charges |
| Lambda → Redpanda path | **HTTPS POST to Redpanda pandaproxy (8082)** behind Caddy reverse proxy with API key | No Kafka client in Lambda, no advertised-listener config, port 9092 never public |
| Ingestion cadence | **EventBridge `rate(5 minutes)`** | Stays inside Groq/Gemini and LangSmith free quotas; kinder to RSS publishers |
| Orchestration | **Single scheduler loop container**: consume → bronze → dbt → LLM (new rows only) → gold, strictly sequential | One mechanism fixes both "who triggers dbt?" and DuckDB's single-writer locking |
| LLM | Groq (primary) behind a thin provider interface, Gemini as fallback | Both free; interface makes swap trivial |
| LangSmith | **Required**, not optional | Named in the spec; free at deduped 5-min volume (~5k traces/mo cap) |
| Terraform | Provisions EC2 from the start (no manual instance later imported) | Avoids import/recreate mess; `terraform destroy` is the cleanup story |
| Dashboard access | Streamlit behind basic auth (Caddy); DuckDB opened `read_only=True` with retry | Public box will be scanned within hours; readers must not fight the writer |
| DNS/TLS | Free DuckDNS subdomain + Caddy automatic HTTPS; Elastic IP on the instance | Let's Encrypt needs a real domain; EIP keeps it stable across restarts |

## Standing rules (cross-cutting, hold all week)

1. **Single writer:** only the scheduler process ever writes DuckDB.
2. **Identity:** `article_id` is minted in the producer/Lambda and flows through
   everything unchanged. Rule: RSS entry GUID if present → else link URL → else
   `sha256(source + link + published)`. Never hash the title (publishers edit them).
   Bronze stores it, silver dedups on it, `gold_ai_news` keys on it.
3. **Schemas are code:** all message/record shapes are Pydantic models in
   `shared/models` — Lambda, scheduler, agent, dashboard import the same classes.
   `docs/design.md` references them; it never duplicates them.
4. **Retries live at the network boundary only:** RSS fetch, Lambda POST, LLM calls
   get `tenacity` backoff; Kafka produce retries via client config. DuckDB writes are
   never retried — in a single-writer design a failed write is a bug to surface.
5. **Environments differ in config values, never in code paths.** `.env` per
   environment + a compose `local` profile for the dev producer. No MODE switches.
6. **Every scheduler cycle ends with one summary log line:**
   `fetched=N published=N new=N ai_calls=N failures=N duration=Xs`.

## Cost & timeline reality

- Burn: ~$12.30 (t4g.small) + ~$3.70 (public IPv4) + ~$1.60 (20 GB gp3 EBS) ≈ **$18/month from credits**.
- A 1–2 week build + a few months of demo uptime ≈ $40–60 total. Under the base $100 credit.
- **Do the credit-earning activities on day 1** (launch instance, create AWS Budget, etc.) → up to $200.
- Free Plan accounts cannot be billed: credits run out → resources suspend. No bill-shock risk.
- 6-month expiry clock started at account creation (July 2026). Record the demo video early.

## Architecture

```
RSS feeds ──(every 5 min)── EventBridge ── Lambda (feedparser → JSON)
                                              │  HTTPS POST + API key
                                              ▼
                              EC2 t4g.small (Ubuntu, Docker Compose)
        ┌─────────────────────────────────────────────────────────────┐
        │  Caddy :443 (TLS via DuckDNS domain, API key, basic auth)   │
        │    ├── /produce → Redpanda pandaproxy :8082                 │
        │    └── /        → Streamlit :8501                           │
        │                                                             │
        │  Redpanda (single node, tuned: --smp 1 --memory 1G)         │
        │      topic: news.raw                                        │
        │        │                                                    │
        │  Scheduler loop (every 5 min, single writer):               │
        │    1. consume news.raw → bronze_news (DuckDB)               │
        │    2. dbt run  → silver (dedup, normalize) + gold marts     │
        │    3. new unique silver rows → LangGraph agent              │
        │         (Groq/Gemini: summary, importance, category,        │
        │          keywords, sentiment, reason — Pydantic-validated)  │
        │    4. write gold_ai_news                                    │
        │        │                                                    │
        │  Streamlit dashboard (read_only DuckDB, ~30s auto-refresh)  │
        └─────────────────────────────────────────────────────────────┘
                     │ traces                    │ nightly backup
                     ▼                           ▼
                 LangSmith                  S3 (duckdb file)
```

Alert semantics: articles with `importance >= threshold` surface on the dashboard's
Alerts page within ~5 minutes of publication (micro-batch "near-real-time" — say so honestly).

## Day-by-day plan

Week 1 = fully working system locally. Week 2 = cloud, observability, polish.

### Day 1 — Foundation + design-lite (Milestone 0+1 merged)
- Repo scaffold (structure below), venv, `.env` + config loader, structured logging, Git init.
- Write `docs/design.md`: Kafka topic + message schema, DuckDB table schemas
  (bronze/silver/gold/gold_ai_news), LangGraph state shape, pandaproxy API contract
  (endpoint, auth header, payload), Terraform resource list.
- RSS fetch with `feedparser` for 3–5 feeds → prints articles to console.
- AWS: create account budget + do credit-earning activities.
- **Deliverable:** `python -m producer.fetch` prints latest articles; design doc committed.

### Day 2 — Redpanda pipeline (Milestones 2+3+4+8 merged)
- `docker-compose.yml`: Redpanda (tuned flags) + pandaproxy enabled.
- Producer: RSS → JSON → produce to `news.raw` (also test the HTTP pandaproxy path
  with `requests` — this is exactly what Lambda will do later).
- Consumer: `news.raw` → DuckDB `bronze_news` (raw JSON + ingested_at). No cleaning.
  ⚠ Build the consumer as an importable module, run manually for testing today.
  It is **not** a long-running container — on Day 3 it becomes step 1 of the
  scheduler loop. There must never be two processes writing DuckDB.
- **Deliverable:** article published to Redpanda lands in DuckDB.

### Day 3 — dbt + scheduler (Milestones 5+6 merged)
- dbt project on DuckDB: `silver_news` (dedup by article GUID/link hash, normalized
  columns, `not_null`/`unique` tests, docs), `gold_news` (reading time, length,
  source domain, publish hour).
- Scheduler container: the sequential loop (consume → dbt run → mark new rows),
  each stage an explicit function; `run_cycle()` times, logs, and error-wraps each.
  All writes go through this one process — nothing else opens DuckDB for writing, ever.
- Create `pipeline_runs` table now (cycle metrics: counts, failures, duration) and
  emit the standing-rules summary log line per cycle.
- **Deliverable:** `docker compose up` runs the full pipeline every 5 minutes locally.

### Day 4 — LangGraph agent (Milestones 13+14 merged)
- Graph: fetch article → LLM call → parse → Pydantic validate → retry-on-invalid →
  write `gold_ai_news` (summary, importance 1–10, category, keywords, sentiment, reason).
- Provider interface: Groq primary, Gemini fallback; rate-limit aware (backoff, and a
  hard daily-call budget so a busy news day degrades gracefully instead of erroring).
- Set LangSmith env vars now (`LANGCHAIN_TRACING_V2=true` etc.) — tracing from day one.
- Wire into scheduler step 3: **only new, deduped silver rows** reach the LLM.
  "New" is defined mechanically: silver rows whose `article_id` has no row in
  `gold_ai_news` (anti-join). No flags, no timestamps-as-state.
- **Deliverable:** new unique articles get AI enrichment within one 5-min cycle.

### Day 5 — Streamlit dashboard (Milestone 7, moved after AI)
- Pages: **Alerts** (importance ≥ threshold, newest first), **Latest News**, **Search**,
  **Statistics** (by source/category/hour, from gold marts).
- `duckdb.connect(read_only=True)` + retry/backoff; `st.fragment`/auto-refresh ~30s.
- **Checkpoint: end of week 1 = complete working system on the laptop via one
  `docker compose up`. Everything after this is deployment + polish.**

### Day 6 — Terraform + EC2 deploy (Milestones 9+10+12 partially merged)
- Terraform: VPC (default is fine), security group (22 from your IP only, 443 open),
  t4g.small + `credit_specification { cpu_credits = "standard" }`, Elastic IP,
  20 GB gp3, `user_data` installing Docker/Compose + 2 GB swap file.
- DuckDNS subdomain → EIP; Caddy service added to compose (TLS, API key on `/produce`,
  basic auth on dashboard). Build images multi-arch or `--platform linux/arm64`.
- Deploy: git pull on EC2 → `docker compose up -d`. Nightly cron: DuckDB file → S3.
- **Deliverable:** dashboard live at `https://<name>.duckdns.org`; `terraform apply`
  recreates the box from nothing.

### Day 7 — Lambda + EventBridge (Milestone 11)
- Lambda (Python): fetch RSS → JSON → POST to `https://<domain>/produce` with API key.
  Dependencies are just `feedparser` + `requests` — small zip, no Kafka client.
- Terraform additions: Lambda, IAM role, EventBridge `rate(5 minutes)`, CloudWatch logs.
- Disable the local/EC2 fetch path; Lambda is now the only producer.
- **Deliverable:** fully cloud-driven end-to-end flow, `terraform apply` from zero.

### Day 8 — Observability + hardening (Milestone 15)
- Health checks per container, DLQ topic (`news.dead`) for poison messages,
  surface `pipeline_runs` (created Day 3) on a dashboard "Ops" page.
- Verify LangSmith traces end-to-end; tag runs with article id.
- Confirm swap in use, memory headroom, and that a full instance reboot self-recovers
  (compose `restart: always`).

### Days 9–10 — Portfolio polish + buffer (Milestone 16)
- Sequence diagrams (Mermaid, in README): normal flow, failure flow
  (timeout → retry → fallback → DLQ), deployment flow. Cheap and great in interviews.
- README (with the architecture diagram), screenshots, deployment guide,
  `.env.example`, tests (schema/unit for producer, consumer, agent parsing),
  GitHub Actions: lint + pytest + `dbt build` on PR.
- Record the demo video **now**, not "someday" (credits clock).
- Buffer for whatever slipped.

## Repo structure

```
news-ai-platform/
├── infra/
│   └── terraform/      # EC2, SG, EIP, Lambda, EventBridge, IAM, S3
├── services/
│   ├── lambda/         # RSS fetch → POST pandaproxy
│   ├── producer/       # local dev producer (compose profile "local" only)
│   ├── scheduler/      # the sequential loop — consume/bronze/dbt/AI stages as
│   │                   #   explicit functions; run_cycle() times+logs each stage.
│   │                   #   Owns ALL DuckDB writes (consumer logic lives here).
│   ├── agent/          # LangGraph graph, provider interface (Groq→Gemini)
│   └── dashboard/      # Streamlit (read-only)
├── shared/
│   ├── models/         # Pydantic: KafkaMessage, BronzeRecord, AIResult
│   ├── config/         # pydantic-settings Settings — sole source of config
│   └── utils/          # article_id minting, retry decorators, logging setup
├── dbt_project/        # bronze → silver → gold models + tests
├── docker/             # Dockerfiles (build context = repo root, to COPY shared/), Caddyfile
├── docker-compose.yml
├── tests/
└── docs/               # design.md, architecture + sequence diagrams (Mermaid), screenshots
```

## What was cut from the original 16-milestone plan (deliberately)

- The RSS→DuckDB-direct stage that Kafka later replaces (M3/M8) — architecture is
  settled, build the final pipeline once.
- Separate raw/bronze milestones (M3/M4) — one deliverable.
- Manual EC2 before Terraform (M10 vs M12) — Terraform from the start.
- "Dashboard before AI" ordering — AI first, so the dashboard is built against real
  enriched data.

## Risks to watch

1. **LLM daily caps** — mitigated by dedup + 5-min cadence + hard daily budget in code.
2. **Memory pressure** — t4g.small + swap should hold; watch `docker stats` on day 6.
3. **DuckDB locking** — safe only while the scheduler stays the sole writer. Never add
   a second writing process.
4. **Credit clock** — ~$18/mo burn; destroy with `terraform destroy` once the demo
   video + screenshots exist, re-apply on demand.
