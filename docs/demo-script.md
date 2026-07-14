# Demo video storyboard (~3 minutes)

Record with QuickTime (screen) or Loom. One take is fine — authenticity beats polish.

| # | ~Time | Show | Say |
|---|---|---|---|
| 1 | 0:00 | README architecture diagram | "This is a real-time news intelligence pipeline running entirely on free tiers — Lambda to Kafka to dbt to a LangGraph agent to a live dashboard." |
| 2 | 0:20 | AWS console → Lambda → Monitor tab (invocations graph) | "EventBridge fires this Lambda every 5 minutes. It fetches RSS and POSTs over an authenticated HTTPS contract — the Kafka port never faces the internet." |
| 3 | 0:45 | Terminal: `ssh … docker compose ps` + `docker compose logs --tail 5 scheduler` | "One t4g.small runs the whole stack in Docker. The scheduler is the single DuckDB writer: consume, dbt build, AI enrichment, metrics — one summary line per cycle." |
| 4 | 1:15 | Dashboard → Alerts page (importance slider) | "The LangGraph agent scores each article's importance and writes a validated summary. Gemini is the primary model with automatic Groq failover when quotas run out." |
| 5 | 1:45 | Dashboard → Ops page | "Observability is built in — cycle durations, AI backlog, failures. You can see the 5-minute heartbeat of the Lambda in the consumption chart." |
| 6 | 2:05 | LangSmith → project → open one trace | "Every agent run is traced in LangSmith — prompt, retries, provider rotation." |
| 7 | 2:25 | Terminal: `terraform plan` (no changes) in infra/terraform | "All infrastructure is Terraform — one apply recreates everything from zero, one destroy tears it down." |
| 8 | 2:45 | README repo layout / CI badge | "Tests and dbt checks run in CI; the repo is on GitHub. Thanks for watching." |

Tips
- Set the browser zoom to 125% so text is readable in the recording.
- Before recording, refresh the dashboard once (30s cache) so charts are current.
- Capture screenshots for the README during the same session:
  Alerts page, Ops page, one LangSmith trace → save to docs/screenshots/,
  then embed at the top of the README.
