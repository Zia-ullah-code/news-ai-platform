# Design Contracts

Companion to [PLAN.md](../PLAN.md). This doc pins the interfaces between
components. **Message/record shapes live as Pydantic models in `shared/models`
(standing rule 3) — this doc references them, it never redefines them.**
If a contract must change: update here + `shared/models` first, then code.

## 1. Article identity (standing rule 2)

Minted once, at the producer/Lambda, by `shared.utils.mint_article_id`:

```
identity = feed GUID  →  else link URL  →  else source|link|published
article_id = sha256(identity)          # 64-char hex, key-safe
```

Never derived from the title (publishers edit titles). Bronze stores it, silver
deduplicates on it, `gold_ai_news` uses it as primary key, LangSmith runs are
tagged with it.

## 2. Kafka topic design

| Topic | Partitions | Retention | Value |
|---|---|---|---|
| `news.raw` | 1 (single consumer, single broker — no parallelism to buy) | 24h / 256 MB | `NewsMessage` JSON |
| `news.dead` | 1 | 7d | poison messages + error context (Day 8) |

Keyed by `article_id` (would preserve per-article ordering if partitions ever grow).

## 3. Ingest API contract (Lambda → EC2)

```
POST https://<name>.duckdns.org/produce/topics/news.raw
Authorization: Bearer <INGEST_API_KEY>          # checked by Caddy, not Redpanda
Content-Type: application/vnd.kafka.json.v2+json

{"records": [{"key": "<article_id>", "value": {<NewsMessage as JSON>}}]}
```

Caddy terminates TLS (Let's Encrypt via DuckDNS domain), verifies the bearer
token, strips `/produce`, and proxies to pandaproxy `:8082`. Port 9092 is never
exposed publicly. Responses: 200 (offsets), 401 (bad key), 5xx → Lambda retries
with backoff (standing rule 4).

## 4. DuckDB schemas

One file (`DUCKDB_PATH`), one writer: the scheduler (standing rule 1).
Dashboard connects `read_only=True`.

```
bronze_news        article_id TEXT, payload JSON (verbatim NewsMessage),
                   kafka_offset BIGINT, ingested_at TIMESTAMP
                   -- append-only, duplicates allowed

silver_news        article_id TEXT (unique), title, url, source, published,
(dbt)              content_clean, fetched_at
                   -- dedup on article_id, normalized types, dbt tests

gold_news          silver + reading_time_min, article_length, source_domain,
(dbt)              publish_hour

gold_ai_news       article_id TEXT PK, summary, importance INT (1-10), category,
                   keywords TEXT[], sentiment, reason, model, processed_at
                   -- shape = shared.models.AIResult; written by scheduler stage 4

pipeline_runs      run_at TIMESTAMP, fetched INT, published INT, new_articles INT,
                   ai_calls INT, failures INT, duration_s DOUBLE
                   -- one row per scheduler cycle (standing rule 6)
```

"New for AI" is mechanical: `silver_news ANTI JOIN gold_ai_news USING (article_id)`.

## 5. Scheduler cycle (every 5 min, sequential)

```
run_cycle():
  1. consume news.raw (batch, commit offsets after write) → bronze_news
  2. dbt run                                              → silver, gold
  3. anti-join for new articles → LangGraph agent         → AIResult list
  4. write gold_ai_news + pipeline_runs row + summary log line
```

Each stage is a function; `run_cycle` times, logs, and error-wraps each stage.
A stage failure aborts the cycle after logging — next cycle retries naturally
because every stage is idempotent (offsets, dedup, anti-join).

## 6. LangGraph agent state

```
state: { article: NewsMessage-like row, attempt: int,
         raw_response: str | None, result: AIResult | None, error: str | None }

nodes: prepare_prompt → call_llm (Groq, fallback Gemini) → parse_validate
       (Pydantic AIResult; on failure loop to call_llm, max 2 attempts)
       → END (result or error; errored articles go to news.dead context table)
```

Budget guard: `LLM_DAILY_CALL_BUDGET` checked before call_llm; over budget →
article stays unprocessed (picked up by a later cycle's anti-join).

## 7. Terraform resource map (infra/terraform)

| Resource | Notes |
|---|---|
| aws_instance | t4g.small, Ubuntu 24.04 arm64, `cpu_credits="standard"`, user_data: docker + compose + 2GB swap |
| aws_eip | stable public IP → DuckDNS record |
| aws_security_group | 22 from my IP, 443 from anywhere; nothing else |
| aws_s3_bucket | nightly DuckDB backup |
| aws_lambda_function | python3.12, arm64; feedparser+requests layer; env: feed list, ingest URL+key |
| aws_scheduler / EventBridge rule | `rate(5 minutes)` → Lambda |
| aws_iam_role/policy | Lambda logs; EC2 instance profile for S3 backup |
| aws_cloudwatch_log_group | Lambda logs, 7-day retention |

## 8. Assumptions & trade-offs

- Single partition / single broker: fine at ~dozens of articles per cycle; the
  Kafka layer exists to demonstrate the pattern, not for throughput.
- Micro-batch (5 min) — "near-real-time", stated honestly on the dashboard.
- DuckDB over Postgres: zero ops, perfect for single-writer analytics; the
  single-writer constraint is a deliberate design, not an accident.
- 6-month AWS credit window: `terraform destroy` after demo assets captured.
